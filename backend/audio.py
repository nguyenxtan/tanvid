"""Quota-bounded, validated local audio extraction and reusable output cache."""

import hashlib
import json
import logging
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import wave
from uuid import uuid4

from backend.media import MANIFEST_BUDGET, MediaError, MediaService

MIB = 1024 * 1024
PROFILE = 'pcm_s16le-mono-16000-v1'


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open('rb') as source:
            while chunk := source.read(MIB):
                digest.update(chunk)
    except OSError as exc:
        raise MediaError('invalid_file', 'Unable to read file for integrity verification') from exc
    return digest.hexdigest()


class AudioService:
    def __init__(self, media: MediaService, ffmpeg: str = 'ffmpeg', timeout_seconds: float = 600):
        self.media = media
        self.workspace = media.workspace
        self.ffmpeg = ffmpeg
        self.timeout_seconds = timeout_seconds

    def _run(self, arguments: list[str], limit: int):
        executable = shutil.which(self.ffmpeg)
        if executable is None:
            raise MediaError('ffmpeg_unavailable', 'FFmpeg is not executable')
        command = [sys.executable, str(Path(__file__).with_name('limited_exec.py')), str(limit), executable,
                   '-nostdin', '-hide_banner', '-v', 'error', '-xerror', *arguments]
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            raise MediaError('ffmpeg_unavailable', 'FFmpeg could not start') from exc
        try:
            returncode = process.wait(timeout=self.timeout_seconds)
            if returncode != 0:
                raise MediaError('extraction_failed', f'FFmpeg failed (exit {returncode}); input may be corrupt or output exceeded its reserved size')
        except BaseException as exc:
            # Reap before removing staging, including KeyboardInterrupt/SIGTERM.
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()
            if isinstance(exc, subprocess.TimeoutExpired):
                raise MediaError('extraction_timeout', 'FFmpeg timed out') from exc
            raise

    def _probe(self, path: Path, demuxer: str) -> dict:
        _, info = self.media._source(path)
        try:
            result = subprocess.run([self.media.ffprobe, '-v', 'error', '-protocol_whitelist', 'file',
                                     '-format_whitelist', demuxer, '-show_streams', '-show_format', '-of', 'json',
                                     '-i', str(path)], capture_output=True, text=True, errors='replace',
                                    timeout=self.media.timeout_seconds)
            if result.returncode:
                raise ValueError('FFprobe rejected audio')
            payload = json.loads(result.stdout)
            duration = float(payload['format']['duration'])
            if not math.isfinite(duration) or duration <= 0 or int(payload['format']['size']) != info.st_size:
                raise ValueError('Invalid audio size/duration')
            tracks = []
            for stream in payload['streams']:
                if stream['codec_type'] != 'audio':
                    raise ValueError('Unexpected non-audio stream')
                track = {'codec': stream['codec_name'], 'channels': int(stream['channels']),
                         'sample_rate': int(stream['sample_rate'])}
                if track['channels'] <= 0 or track['sample_rate'] <= 0 or not track['codec']:
                    raise ValueError('Invalid audio stream')
                tracks.append(track)
            if not tracks:
                raise ValueError('Audio tracks missing')
            return {'path': str(path), 'duration_seconds': duration, 'size_bytes': info.st_size, 'tracks': tracks}
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError) as exc:
            raise MediaError('invalid_audio', 'Audio metadata could not be validated') from exc

    @staticmethod
    def _duration_matches(actual: float, expected: float):
        if abs(actual - expected) > max(0.25, expected * 0.001):
            raise MediaError('duration_mismatch', 'Extracted audio duration differs from source')

    def _speech_info(self, path: Path, expected: float) -> dict:
        result = self._probe(path, 'wav')
        if result.pop('tracks') != [{'codec': 'pcm_s16le', 'channels': 1, 'sample_rate': 16000}]:
            raise MediaError('invalid_audio', 'Speech audio must be PCM 16-bit mono 16 kHz')
        try:
            with wave.open(str(path), 'rb') as source:
                if (source.getsampwidth(), source.getnchannels(), source.getframerate()) != (2, 1, 16000):
                    raise ValueError('Invalid WAV format')
                frames = source.getnframes()
                actual = 0
                while chunk := source.readframes(65536):
                    actual += len(chunk)
                if frames <= 0 or actual != frames * 2:
                    raise ValueError('Truncated PCM frames')
                duration = frames / 16000
        except (OSError, EOFError, ValueError, wave.Error) as exc:
            raise MediaError('invalid_audio', 'WAV frame integrity check failed') from exc
        self._duration_matches(duration, expected)
        self._duration_matches(result['duration_seconds'], duration)
        result.update(codec='pcm_s16le', channels=1, sample_rate=16000, sample_width_bytes=2,
                      duration_seconds=duration, sha256=checksum(path))
        return result

    def _original_info(self, path: Path, metadata: dict) -> dict:
        result = self._probe(path, 'matroska,webm')
        expected = [{key: track[key] for key in ('codec', 'channels', 'sample_rate')}
                    for track in metadata['audio_tracks']]
        if result['tracks'] != expected:
            raise MediaError('invalid_audio', 'Original audio track format was not preserved')
        expected_duration = max(track.get('duration_seconds', metadata['duration_seconds'])
                                for track in metadata['audio_tracks'])
        self._duration_matches(result['duration_seconds'], expected_duration)
        self._run(['-err_detect', 'explode', '-protocol_whitelist', 'file', '-format_whitelist', 'matroska,webm',
                   '-i', str(path), '-map', '0:a', '-f', 'null', '-'], MIB)
        result['sha256'] = checksum(path)
        return result

    def _cached(self, final: Path, source_hash: str, metadata: dict, duration: float, audio_track: int) -> tuple:
        speech = original = None
        try:
            manifest = final / 'metadata.json'
            if manifest.stat().st_size > MANIFEST_BUDGET:
                return None, None
            record = json.loads(manifest.read_text())
            if (record['source_sha256'], record['profile'], record['audio_track']) != (source_hash, PROFILE, audio_track):
                return None, None
            candidate = self._speech_info(final / 'speech.wav', duration)
            if candidate['sha256'] == record['speech']['sha256']:
                speech = candidate
            if record.get('original'):
                try:
                    candidate = self._original_info(final / 'original.mka', metadata)
                    if candidate['sha256'] == record['original']['sha256']:
                        original = candidate
                except MediaError:
                    original = None
        except (OSError, ValueError, KeyError, TypeError, MediaError):
            pass
        return speech, original

    def extract(self, source: Path, audio_track: int = 0, preserve_original: bool = False) -> dict:
        started = time.monotonic()
        source, before = self.media._source(source)
        metadata = self.media.inspect(source)
        if not metadata['audio_tracks']:
            raise MediaError('no_audio', 'Video contains no audio tracks')
        if isinstance(audio_track, bool) or not isinstance(audio_track, int) or not 0 <= audio_track < len(metadata['audio_tracks']):
            raise MediaError('invalid_audio_track', 'Audio track ordinal is out of range')
        track = metadata['audio_tracks'][audio_track]
        duration = track.get('duration_seconds', metadata['duration_seconds'])
        speech_limit = math.ceil((duration + max(0.25, duration * 0.001)) * 32000) + 4096
        if speech_limit >= 2**32:
            raise MediaError('audio_too_large', 'Speech output exceeds supported classic WAV size')
        source_hash = checksum(source)
        if self.media._identity(before) != self.media._identity(self.media._source(source)[1]):
            raise MediaError('source_changed', 'Source changed before extraction')
        key = hashlib.sha256(f'{source_hash}:{PROFILE}:{audio_track}'.encode()).hexdigest()
        with self.workspace.locked():
            # Check workspace layout even on cache hits (including symlink rejection).
            self.workspace.preflight(0)
            if self.media._identity(before) != self.media._identity(self.media._source(source)[1]):
                raise MediaError('source_changed', 'Source changed while waiting for workspace lock')
            final = self.workspace.root / 'audio' / key
            speech, original = self._cached(final, source_hash, metadata, duration, audio_track)
            if speech and (original or not preserve_original):
                return self._record(source_hash, audio_track, speech, original, started, True, True)
            original_limit = before.st_size + MIB if preserve_original else 0
            self.workspace.preflight(speech_limit + original_limit + MANIFEST_BUDGET)
            stage = backup = None
            published = False
            try:
                final.parent.mkdir(exist_ok=True)
                staging = self.workspace.root / '.staging'
                staging.mkdir(exist_ok=True)
                stage = Path(tempfile.mkdtemp(prefix='audio-', dir=staging))
                input_args = ['-err_detect', 'explode', '-protocol_whitelist', 'file',
                              '-format_whitelist', 'mov,matroska,webm,avi', '-i', str(source)]
                reused_speech = speech is not None
                if speech:
                    shutil.copyfile(final / 'speech.wav', stage / 'speech.wav')
                else:
                    self._run([*input_args, '-map', f"0:{track['index']}", '-vn', '-sn', '-dn',
                               '-map_metadata', '-1', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le',
                               '-rf64', 'never', '-f', 'wav', '-n', str(stage / 'speech.wav')], speech_limit)
                speech = self._speech_info(stage / 'speech.wav', duration)
                original = None
                if preserve_original:
                    self._run([*input_args, '-map', '0:a', '-vn', '-sn', '-dn', '-map_metadata', '-1',
                               '-map_chapters', '-1', '-c:a', 'copy', '-f', 'matroska', '-n', str(stage / 'original.mka')], original_limit)
                    original = self._original_info(stage / 'original.mka', metadata)
                if self.media._identity(before) != self.media._identity(self.media._source(source)[1]):
                    raise MediaError('source_changed', 'Source changed during extraction')
                speech['path'] = str(final / 'speech.wav')
                if original:
                    original['path'] = str(final / 'original.mka')
                record = self._record(source_hash, audio_track, speech, original, started, False, reused_speech)
                encoded = (json.dumps(record, indent=2, allow_nan=False) + '\n').encode()
                if len(encoded) > MANIFEST_BUDGET:
                    raise MediaError('metadata_too_large', 'Audio manifest exceeds reservation')
                (stage / 'metadata.json').write_bytes(encoded)
                self.workspace.preflight(0)
                try:
                    if final.exists():
                        backup = staging / ('replaced-' + uuid4().hex)
                        final.rename(backup)
                    stage.rename(final)
                    published = True
                except BaseException:
                    if backup and backup.exists():
                        backup.rename(final)
                        backup = None
                    raise
                return record
            except OSError as exc:
                raise MediaError('extraction_failed', 'Unable to read, write or publish audio') from exc
            finally:
                if stage is not None and stage.exists():
                    self._cleanup(stage)
                # If rollback itself fails, retain the old output for manual recovery.
                if published and backup is not None and backup.exists():
                    self._cleanup(backup)

    @staticmethod
    def _cleanup(path: Path):
        try:
            shutil.rmtree(path)
        except OSError:
            logging.getLogger(__name__).warning('Recovery cleanup required; retained workspace files at %s', path)

    @staticmethod
    def _record(source_hash, audio_track, speech, original, started, reused, speech_reused):
        return {'profile': PROFILE, 'source_sha256': source_hash, 'audio_track': audio_track,
                'speech': speech, 'original': original, 'reused': reused, 'speech_reused': speech_reused,
                'elapsed_seconds': round(time.monotonic() - started, 6)}
