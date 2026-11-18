"""Mandarin transcription, validated reuse, and reference-based CER scoring."""

import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata

from backend.audio import AudioService, checksum
from backend.media import MediaError
from backend.models import ModelStore
from backend import review, silence

# DF-005 decoding options, unchanged; the baseline every DF-006 setting is compared with.
OPTIONS = {'language': 'zh', 'task': 'transcribe', 'temperature': 0.0,
           'condition_on_previous_text': False, 'word_timestamps': False, 'fp16': True,
           'initial_prompt': '以下是普通话简体中文转写。'}
# Named, benchmarked decoding profiles. Only `gate` changes which audio is decoded.
PROFILES = {
    'df005': {'options': OPTIONS, 'gate': None,
              'description': 'DF-005 baseline: greedy temperature 0, no previous-text conditioning'},
    'energy_gate': {'options': OPTIONS, 'gate': silence.GATE,
                    'description': 'Baseline options, decoding only energy-gate non-silent regions (clip_timestamps)'},
    'energy_gate_coarse': {'options': OPTIONS, 'gate': dict(silence.GATE, merge_gap_ms=3000, pad_ms=500),
                           'description': 'Energy gate merging gaps < 3 s and padding 0.5 s: skips only long silences'},
    'temperature_fallback': {'options': dict(OPTIONS, temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0]), 'gate': None,
                             'description': 'Whisper temperature fallback on compression/logprob failure, seed 0'},
    'silence_skip': {'options': dict(OPTIONS, word_timestamps=True, hallucination_silence_threshold=2.0), 'gate': None,
                     'description': 'MLX Whisper word timestamps + built-in hallucination_silence_threshold=2.0 s'},
}
DEFAULT_MODEL = 'medium'  # Provisional DF-006 default from measured DF-005/DF-006 CER.
DEFAULT_PROFILE = 'df005'
SCHEMA = 3
RESULT_LIMIT = 4 * 1024 * 1024
RESERVATION = 16 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()


def normalize_segments(raw, duration_ms, diagnostics=None):
    """DF-005 normalized segments (unchanged schema and behaviour)."""
    return [segment for _, segment, _ in normalize_indexed(raw, duration_ms, diagnostics)]


def normalize_indexed(raw, duration_ms, diagnostics=None, excluded=None):
    """Yield (raw_index, segment, raw_end_ms); record excluded raw segments with reasons."""
    if not isinstance(raw, list):
        raise MediaError('invalid_transcription', 'Segments must be a list')
    result, previous = [], 0
    excluded = [] if excluded is None else excluded
    counts = {'dropped_empty': 0, 'dropped_zero_length': 0, 'dropped_outside_audio': 0, 'clipped_end': 0}
    try:
        for index, segment in enumerate(raw):
            start, end = float(segment['start']), float(segment['end'])
            text = segment['text']
            if not isinstance(text, str) or not math.isfinite(start) or not math.isfinite(end):
                raise ValueError('Invalid text/timestamps')
            if not text.strip():
                counts['dropped_empty'] += 1
                excluded.append({'raw_index': index, 'reason': 'empty_text'})
                continue
            start, end = round(start * 1000), round(end * 1000)
            if start < 0 or end < start:
                raise ValueError('Out-of-range or unordered timestamps')
            if end == start:
                counts['dropped_zero_length'] += 1
                excluded.append({'raw_index': index, 'reason': 'zero_length_timestamp', 'start_ms': start})
                continue
            if start >= duration_ms:
                counts['dropped_outside_audio'] += 1
                excluded.append({'raw_index': index, 'reason': 'starts_after_audio_end', 'start_ms': start,
                                 'audio_duration_ms': duration_ms})
                continue
            if start < previous:
                raise ValueError('Unordered timestamps')
            if end > duration_ms:
                counts['clipped_end'] += 1
            raw_end = end
            end = min(end, duration_ms)
            confidence = {}
            for name in ('avg_logprob', 'no_speech_prob', 'compression_ratio'):
                value = segment.get(name)
                if value is not None:
                    value = float(value)
                    if not math.isfinite(value) or (name == 'no_speech_prob' and not 0 <= value <= 1):
                        raise ValueError('Invalid confidence metric')
                    if (name == 'avg_logprob' and value > 0) or (name == 'compression_ratio' and value < 0):
                        raise ValueError('Invalid confidence range')
                confidence[name] = value
            result.append((index, {'start_ms': start, 'end_ms': end, 'original_text': text.strip(),
                                   'confidence': confidence}, raw_end))
            previous = start
    except (TypeError, KeyError, ValueError, OverflowError) as exc:
        raise MediaError('invalid_transcription', 'Invalid structured segment: ' + str(exc)) from exc
    if diagnostics is not None:
        diagnostics.update(counts)
    return result


def character_error_rate(reference, hypothesis):
    def normalize(text):
        return ''.join(c.lower() for c in unicodedata.normalize('NFKC', text)
                       if not c.isspace() and unicodedata.category(c)[0] not in ('P', 'S'))
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        raise ValueError('Reference must contain scored characters')
    row = list(range(len(hyp) + 1))
    for i, a in enumerate(ref, 1):
        new = [i]
        for j, b in enumerate(hyp, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j-1] + (a != b)))
        row = new
    return {'cer': row[-1] / len(ref), 'edits': row[-1], 'reference_characters': len(ref),
            'hypothesis_characters': len(hyp), 'normalization': 'NFKC, lowercase, remove whitespace/punctuation/symbols; no script conversion'}


def build_review(raw_segments, identity, duration_ms, analysis, diagnostics=None):
    """Normalized, ID'd, flagged segments derived deterministically from raw output."""
    excluded = []
    entries = normalize_indexed(raw_segments, duration_ms, diagnostics, excluded)
    prompt = identity['options'].get('initial_prompt')
    segments = review.review_segments(entries, identity['audio_sha256'], duration_ms, analysis, prompt)
    return segments, excluded, review.summarize(segments, excluded, analysis)


def decode_options(profile, path, analysis):
    """Effective worker options; gated profiles decode only their gate's regions."""
    options = dict(PROFILES[profile]['options'])
    gate = PROFILES[profile]['gate']
    if gate is not None:
        gated = analysis if gate == silence.GATE else silence.analyze(path, gate)
        options['clip_timestamps'] = silence.clip_timestamps(gated)
    return json.loads(canonical(options))


class TranscriptionService:
    def __init__(self, media, timeout_seconds=1800):
        self.media = media
        self.workspace = media.workspace
        self.models = ModelStore(self.workspace)
        self.timeout_seconds = timeout_seconds

    def _worker(self, audio, model, output, log, options):
        env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                   HF_HOME=str(self.workspace.root / 'models' / 'offline-hf'),
                   PYTHONDONTWRITEBYTECODE='1', NUMBA_DISABLE_JIT='1')
        command = [sys.executable, '-I', str(Path(__file__).with_name('limited_exec.py')), str(RESULT_LIMIT),
                   sys.executable, '-m', 'backend.whisper_worker', str(audio), str(model), str(output), str(options)]
        from backend.workspace import ROOT
        with log.open('wb') as stderr:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=stderr, start_new_session=True)
            try:
                code = process.wait(timeout=self.timeout_seconds)
                if code:
                    detail = log.read_text(errors='replace')[-2000:]
                    raise MediaError('transcription_failed', 'MLX worker failed: ' + detail)
            except BaseException as exc:
                if process.returncode is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                process.wait()
                if isinstance(exc, subprocess.TimeoutExpired):
                    raise MediaError('transcription_timeout', 'MLX transcription timed out') from exc
                raise

    def _validate_payload(self, payload, identity, duration_ms, duration_seconds, analysis, options):
        if payload['identity'] != identity or payload['silence'] != analysis:
            raise ValueError('Cached identity/silence mismatch')
        raw = payload['raw_inference']
        if raw['decode_options'] != options:
            raise ValueError('Cached decoding options mismatch')
        adjustments = {}
        segments, excluded, summary = build_review(raw['segments'], identity, duration_ms, analysis, adjustments)
        if (segments != payload['segments'] or excluded != payload['excluded_raw_segments']
                or summary != payload['review'] or adjustments != payload['segment_adjustments']):
            raise ValueError('Cached segment/review schema mismatch')
        if (payload['text'] != ''.join(s['original_text'] for s in payload['segments'])
                or payload['language'] != 'zh' or payload['duration_ms'] != duration_ms
                or payload['duration_seconds'] != duration_seconds):
            raise ValueError('Cached text/language/duration mismatch')
        for key in ('model_load_seconds', 'inference_seconds', 'peak_rss_bytes', 'mlx_peak_bytes'):
            value = payload['metrics'][key]
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid benchmark metric')
        expected_rtf = payload['metrics']['inference_seconds'] / duration_seconds
        if abs(payload['metrics']['real_time_factor'] - expected_rtf) > 1e-6:
            raise ValueError('Cached RTF mismatch')

    def transcribe(self, source, model=DEFAULT_MODEL, audio_track=0, force=False, profile=DEFAULT_PROFILE):
        started = time.monotonic()
        if profile not in PROFILES:
            raise MediaError('unknown_profile', 'Choose a decoding profile: ' + ', '.join(PROFILES))
        # Audio pipeline takes its own lock; complete it before acquiring inference lock.
        audio = AudioService(self.media).extract(source, audio_track=audio_track)['speech']
        spec = self.models.spec(model)
        model_path = self.models.ensure(model)
        identity = {'audio_sha256': audio['sha256'], 'model': spec, 'profile': profile,
                    'options': PROFILES[profile]['options'], 'decode_gate': PROFILES[profile]['gate'],
                    'silence_gate': silence.GATE,
                    'review_version': review.REVIEW_VERSION,
                    'mlx_whisper_version': importlib.metadata.version('mlx-whisper'),
                    'mlx_version': importlib.metadata.version('mlx'), 'schema': SCHEMA}
        identity = json.loads(canonical(identity))
        key = hashlib.sha256(canonical(identity)).hexdigest()
        duration_ms = max(1, round(audio['duration_seconds'] * 1000))
        with self.workspace.locked():
            self.workspace.preflight(0)
            try:
                analysis = json.loads(canonical(silence.analyze(Path(audio['path']))))
                options = decode_options(profile, Path(audio['path']), analysis)
            except (OSError, ValueError, EOFError) as exc:
                raise MediaError('invalid_audio', 'Unable to analyze speech audio: ' + str(exc)) from exc
            final = self.workspace.root / 'transcripts' / (key + '.json')
            if not force and final.is_file() and final.stat().st_size <= RESULT_LIMIT:
                try:
                    envelope = json.loads(final.read_text())
                    payload = envelope['payload']
                    if hashlib.sha256(canonical(payload)).hexdigest() != envelope['sha256']:
                        raise ValueError('Cache checksum mismatch')
                    self._validate_payload(payload, identity, duration_ms, audio['duration_seconds'], analysis, options)
                    return dict(payload, reused=True, elapsed_seconds=time.monotonic() - started, result_path=str(final))
                except (OSError, ValueError, KeyError, TypeError, MediaError):
                    pass
            self.workspace.preflight(RESERVATION)
            stage = None
            try:
                final.parent.mkdir(exist_ok=True)
                staging = self.workspace.root / '.staging'
                staging.mkdir(exist_ok=True)
                stage = Path(tempfile.mkdtemp(prefix='transcribe-', dir=staging))
                output = stage / 'raw.json'
                (stage / 'options.json').write_bytes(canonical(options))
                self._worker(Path(audio['path']), model_path, output, stage / 'worker.log', stage / 'options.json')
                if output.stat().st_size > RESULT_LIMIT:
                    raise MediaError('invalid_transcription', 'Inference result exceeded output limit')
                raw = json.loads(output.read_text())
                adjustments = {}
                # Raw model output is kept verbatim; normalization/flags are derived from it.
                segments, excluded, summary = build_review(raw['segments'], identity, duration_ms, analysis, adjustments)
                if checksum(Path(audio['path'])) != identity['audio_sha256']:
                    raise MediaError('source_changed', 'Audio changed during transcription')
                payload = {'identity': identity, 'language': 'zh', 'duration_ms': duration_ms,
                           'duration_seconds': audio['duration_seconds'], 'silence': analysis,
                           'raw_inference': {'segments': raw['segments'], 'decode_options': options},
                           'segment_adjustments': adjustments, 'segments': segments,
                           'excluded_raw_segments': excluded, 'review': summary,
                           'text': ''.join(s['original_text'] for s in segments), 'metrics': raw['metrics']}
                payload['metrics']['real_time_factor'] = raw['metrics']['inference_seconds'] / audio['duration_seconds']
                payload['metrics']['model_bytes'] = sum(f['size_bytes'] for f in spec['files'])
                payload = json.loads(canonical(payload))
                self._validate_payload(payload, identity, duration_ms, audio['duration_seconds'], analysis, options)
                envelope = {'payload': payload, 'sha256': hashlib.sha256(canonical(payload)).hexdigest()}
                encoded = canonical(envelope)
                if len(encoded) > RESULT_LIMIT:
                    raise MediaError('invalid_transcription', 'Structured result exceeded output limit')
                pending = stage / 'complete.json'
                pending.write_bytes(encoded)
                self.workspace.preflight(0)
                pending.replace(final)
                return dict(payload, reused=False, elapsed_seconds=time.monotonic() - started, result_path=str(final))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise MediaError('invalid_transcription', 'Unable to validate/publish transcription: ' + str(exc)) from exc
            finally:
                if stage is not None:
                    AudioService._cleanup(stage)
