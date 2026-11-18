import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np

from backend import review, silence
from backend.media import MediaError, MediaService
from backend.models import ModelStore
from backend.transcription import (DEFAULT_MODEL, PROFILES, TranscriptionService, build_review, canonical,
                                   normalize_segments)
from backend.workspace import Workspace, WorkspaceConfig

AUDIO = 'a' * 64
CONFIDENT = {'avg_logprob': -0.2, 'no_speech_prob': 0.01, 'compression_ratio': 1.2}
SPEECH = {'inconclusive': False, 'regions_ms': [[0, 60000]]}


def raw(start, end, text, **confidence):
    return dict({'start': start, 'end': end, 'text': text}, **dict(CONFIDENT, **confidence))


def identity(prompt='以下是普通话简体中文转写。'):
    return {'audio_sha256': AUDIO, 'options': {'initial_prompt': prompt}}


def codes(segment):
    return [reason['code'] for reason in segment['review']['reasons']]


def write_wav(path, samples):
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, 16000, len(samples), 'NONE', 'not compressed'))
        output.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())


class SilenceGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'speech.wav'
        self.rng = np.random.default_rng(0)

    def test_bursts_between_quiet_noise_become_padded_regions(self):
        audio = self.rng.normal(0, 0.0005, 16000 * 6)
        for start in (1, 4):
            audio[start * 16000:(start + 1) * 16000] += 0.3 * np.sin(np.arange(16000) / 5)
        write_wav(self.path, audio)
        analysis = silence.analyze(self.path)
        self.assertFalse(analysis['inconclusive'])
        self.assertEqual(len(analysis['regions_ms']), 2)
        first, second = analysis['regions_ms']
        self.assertAlmostEqual(first[0], 750, delta=40)
        self.assertAlmostEqual(second[1], 5250, delta=40)
        self.assertEqual(silence.clip_timestamps(analysis), [v / 1000 for r in analysis['regions_ms'] for v in r])
        self.assertEqual(analysis, silence.analyze(self.path))  # Deterministic for identical bytes.

    def test_constant_level_audio_is_inconclusive_and_never_discarded(self):
        write_wav(self.path, 0.3 * np.sin(np.arange(16000 * 3) / 5))
        analysis = silence.analyze(self.path)
        self.assertTrue(analysis['inconclusive'])
        self.assertEqual(analysis['regions_ms'], [[0, 3000]])

    def test_digital_silence_has_no_regions(self):
        write_wav(self.path, np.zeros(16000 * 2))
        analysis = silence.analyze(self.path)
        self.assertEqual((analysis['regions_ms'], analysis['inconclusive']), ([], False))
        self.assertEqual(silence.clip_timestamps(analysis), [])

    def test_quiet_contrasty_audio_below_absolute_floor_is_decoded_in_full(self):
        # Review B1: real -63 dBFS bursts over a -90 dB floor must never yield "nothing to decode".
        audio = self.rng.normal(0, 10 ** (-90 / 20), 16000 * 10)
        for start in range(16000, 160000, 48000):
            audio[start:start + 16000] += self.rng.normal(0, 10 ** (-63 / 20), 16000)
        regions, _, inconclusive = silence.detect_regions(silence.frame_levels(audio), 10000)
        self.assertEqual((regions, inconclusive), ([[0, 10000]], True))
        quiet_noise = self.rng.normal(0, 10 ** (-80 / 20), 16000 * 2)
        self.assertEqual(silence.detect_regions(silence.frame_levels(quiet_noise), 2000)[1:][1], True)

    def test_rejects_unexpected_wav_format(self):
        with wave.open(str(self.path), 'wb') as output:
            output.setparams((2, 2, 16000, 0, 'NONE', 'not compressed'))
        with self.assertRaises(ValueError):
            silence.analyze(self.path)


class ReviewFlagTests(unittest.TestCase):
    def review(self, segments, duration_ms=60000, analysis=SPEECH, **kwargs):
        return build_review(segments, identity(**kwargs), duration_ms, analysis)

    def test_clean_segments_are_unflagged_not_verified(self):
        segments, excluded, summary = self.review([raw(0, 2, '你好，中国。'), raw(2, 4, '今天天气很好。')])
        self.assertEqual([s['review']['status'] for s in segments], ['unflagged', 'unflagged'])
        self.assertEqual((excluded, summary['needs_review'], summary['unflagged']), ([], 0, 2))
        self.assertIn('not verified correct', summary['disclaimer'])

    def test_original_text_and_timestamps_are_never_changed(self):
        source = [raw(0, 1.5, ' 谢谢观看 '), raw(1.5, 1.6, '哈哈哈哈哈哈哈哈哈哈', compression_ratio=3.0)]
        segments, _, _ = self.review(source)
        self.assertEqual([(s['start_ms'], s['end_ms'], s['original_text'], s['confidence']) for s in segments],
                         [(s['start_ms'], s['end_ms'], s['original_text'], s['confidence'])
                          for s in normalize_segments(source, 60000)])
        self.assertEqual(segments[0]['original_text'], '谢谢观看')

    def test_ids_are_stable_unique_and_traceable_to_raw_index(self):
        source = [raw(0, 1, ''), raw(1, 2, '你好'), raw(2, 3, '你好')]
        first, excluded, _ = self.review(source)
        second, _, _ = self.review(copy.deepcopy(source))
        self.assertEqual([s['id'] for s in first], [s['id'] for s in second])
        self.assertEqual(len({s['id'] for s in first}), 2)
        self.assertEqual([s['raw_index'] for s in first], [1, 2])
        self.assertEqual(excluded, [{'raw_index': 0, 'reason': 'empty_text'}])
        self.assertTrue(first[0]['id'].startswith('seg-0001-'))

    def test_duplicate_and_repetition_flags(self):
        segments, _, summary = self.review([
            raw(0, 2, '我爱你。'), raw(2, 4, '我爱你！'), raw(4, 8, '对不起对不起对不起对不起'),
            raw(8, 9, '对对对对')])
        self.assertIn('duplicate_of_previous_segment', codes(segments[1]))
        self.assertIn('repeated_text_pattern', codes(segments[2]))
        self.assertNotIn('repeated_text_pattern', codes(segments[3]))  # Short natural run allowed.
        self.assertEqual(summary['category_counts']['duplicate'], 1)

    def test_suspected_hallucination_flags_are_labeled_heuristic(self):
        segments, _, _ = self.review([
            raw(0, 3, '一二三四五六七八九十', compression_ratio=2.9),
            raw(3, 6, '请不吝点赞 订阅 转发 打赏支持明镜与点点栏目'),
            raw(6, 9, '以下是普通话简体中文转写。'), raw(9, 10, '是。'), raw(10, 11, '中文')])
        self.assertIn('high_compression_ratio', codes(segments[0]))
        self.assertIn('known_artefact_phrase', codes(segments[1]))
        self.assertIn('prompt_echo', codes(segments[2]))
        self.assertEqual((codes(segments[3]), codes(segments[4])), ([], []))  # Short replies are not echoes.
        for segment in segments[:3]:
            for reason in segment['review']['reasons']:
                self.assertTrue(reason['heuristic'])
                self.assertEqual(reason['category'], 'suspected_hallucination')

    def test_window_no_speech_probability_alone_is_not_flagged(self):
        segments, _, _ = self.review([raw(0, 3, '他已经回来了。', no_speech_prob=0.9),
                                      raw(3, 6, '他在做什么？', no_speech_prob=0.9, avg_logprob=-1.4)])
        self.assertEqual(codes(segments[0]), [])
        self.assertEqual(codes(segments[1]), ['likely_non_speech', 'low_average_logprob'])

    def test_text_over_measured_silence(self):
        analysis = {'inconclusive': False, 'regions_ms': [[0, 2000]]}
        segments, _, _ = self.review([raw(0, 2, '你好'), raw(5, 8, '谢谢', no_speech_prob=0.7)], analysis=analysis)
        self.assertEqual(codes(segments[0]), [])
        self.assertEqual(codes(segments[1]), ['text_over_detected_silence', 'likely_non_speech'])
        inconclusive = {'inconclusive': True, 'regions_ms': [[0, 60000]]}
        segments, _, _ = self.review([raw(5, 8, '谢谢')], analysis=inconclusive)
        self.assertEqual(codes(segments[0]), [])

    def test_timestamp_flags(self):
        segments, excluded, summary = self.review([
            raw(0, 4, '你好'), raw(3, 3.5, '这是一个非常非常长的句子说得太快了'), raw(4, 10, '嗯'),
            raw(12, 12, '零长度'), raw(59, 75, '结尾'), raw(61, 62, '外面')], duration_ms=60000)
        self.assertIn('long_span_little_text', codes(segments[0]))
        self.assertIn('overlaps_previous_segment', codes(segments[1]))
        self.assertIn('implausibly_fast_speech_rate', codes(segments[1]))
        self.assertIn('long_span_little_text', codes(segments[2]))
        self.assertEqual(codes(segments[3]), ['timestamp_clipped_to_audio_end'])
        self.assertEqual(segments[3]['review']['reasons'][0]['evidence']['raw_end_ms'], 75000)
        self.assertEqual(segments[3]['end_ms'], 60000)
        self.assertEqual([e['reason'] for e in excluded], ['zero_length_timestamp', 'starts_after_audio_end'])
        self.assertEqual(summary['excluded_raw_segments'], 2)

    def test_missed_speech_reports_uncovered_measured_sound(self):
        analysis = {'inconclusive': False, 'regions_ms': [[0, 6000], [30000, 31000], [40000, 50000]]}
        segments, _, summary = self.review([raw(0, 2.5, '第一句'), raw(40, 50, '最后一句话说完了')],
                                           analysis=analysis)
        self.assertEqual([(m['start_ms'], m['end_ms']) for m in summary['possible_missed_speech']], [(2500, 6000)])
        self.assertEqual(summary['possible_missed_speech_ms'], 3500)
        _, _, nothing = self.review([], analysis={'inconclusive': True, 'regions_ms': [[0, 60000]]})
        self.assertEqual(nothing['possible_missed_speech'], [])

    def test_malformed_raw_timestamps_still_fail(self):
        for bad in ([raw(2, 1, '错')], [raw(float('nan'), 1, '错')], [raw(2, 3, '一'), raw(1, 4, '二')]):
            with self.subTest(bad=bad), self.assertRaises(MediaError):
                self.review(bad)


class ProfileServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.workspace = Workspace(WorkspaceConfig(root / 'workspace'))
        self.service = TranscriptionService(MediaService(self.workspace))
        self.wav = root / 'speech.wav'
        audio = np.random.default_rng(1).normal(0, 0.0005, 16000 * 4)
        audio[16000:32000] += 0.3 * np.sin(np.arange(16000) / 5)
        write_wav(self.wav, audio)
        self.audio = {'speech': {'path': str(self.wav), 'sha256': hashlib.sha256(self.wav.read_bytes()).hexdigest(),
                                 'duration_seconds': 4}}
        spec = {'repo': 'test/model', 'revision': 'c' * 40,
                'files': [{'name': 'weights.npz', 'size_bytes': 1, 'sha256': hashlib.sha256(b'x').hexdigest()}]}
        self.service.models = ModelStore(self.workspace, {'test': spec})
        model = self.workspace.root / 'models' / ('test-' + 'c' * 40)
        model.mkdir(parents=True)
        (model / 'weights.npz').write_bytes(b'x')
        self.raw = {'segments': [{'id': 0, 'seek': 0, 'start': 1.0, 'end': 2.0, 'text': '你好', 'tokens': [1, 2],
                                  'temperature': 0.0, 'avg_logprob': -0.1, 'compression_ratio': 1.0,
                                  'no_speech_prob': 0.1}],
                    'metrics': {'model_load_seconds': 0.1, 'inference_seconds': 0.2, 'peak_rss_bytes': 1,
                                'mlx_peak_bytes': 1}}
        self.options = []
        extract = patch('backend.transcription.AudioService.extract', return_value=self.audio)
        extract.start()
        self.addCleanup(extract.stop)

    def worker(self, audio, model, output, log, options):
        self.options.append(json.loads(Path(options).read_text()))
        output.write_text(json.dumps(self.raw, ensure_ascii=False))

    def run_profile(self, profile='df005'):
        with patch.object(self.service, '_worker', side_effect=self.worker):
            return self.service.transcribe(self.wav, model='test', profile=profile)

    def test_raw_inference_is_preserved_verbatim_before_review(self):
        result = self.run_profile()
        self.assertEqual(result['raw_inference']['segments'], self.raw['segments'])
        self.assertEqual(result['segments'][0]['original_text'], '你好')
        self.assertEqual(result['segments'][0]['review']['status'], 'unflagged')
        self.assertEqual(result['identity']['profile'], 'df005')
        self.assertEqual(self.options[0], json.loads(canonical(PROFILES['df005']['options'])))

    def test_gated_profiles_decode_only_measured_regions(self):
        result = self.run_profile('energy_gate')
        clips = self.options[0]['clip_timestamps']
        self.assertEqual(len(clips), 2)
        self.assertAlmostEqual(clips[0], 0.75, delta=0.04)
        self.assertEqual(result['raw_inference']['decode_options'], self.options[0])
        self.run_profile('energy_gate_coarse')
        self.assertIn('clip_timestamps', self.options[1])
        self.run_profile('temperature_fallback')
        self.assertEqual(self.options[2]['temperature'], [0.0, 0.2, 0.4, 0.6, 0.8, 1.0])

    def test_gated_profiles_never_publish_empty_result_for_quiet_dialogue(self):
        # Review B1 end to end: quiet bursts below the absolute floor decode the whole audio.
        rng = np.random.default_rng(2)
        audio = rng.normal(0, 10 ** (-90 / 20), 16000 * 4)
        audio[16000:32000] += rng.normal(0, 10 ** (-63 / 20), 16000)
        write_wav(self.wav, audio)
        self.audio['speech']['sha256'] = hashlib.sha256(self.wav.read_bytes()).hexdigest()
        for profile in ('energy_gate', 'energy_gate_coarse'):
            result = self.run_profile(profile)
            self.assertEqual(self.options[-1]['clip_timestamps'], [0.0, 4.0])
            self.assertTrue(result['silence']['inconclusive'])
            self.assertEqual(result['segments'][0]['original_text'], '你好')
            self.assertNotIn('text_over_detected_silence', [r['code'] for r in result['segments'][0]['review']['reasons']])

    def test_profiles_have_separate_cache_identities_and_validated_reuse(self):
        first = self.run_profile('df005')
        second = self.run_profile('silence_skip')
        self.assertNotEqual(first['result_path'], second['result_path'])
        with patch.object(self.service, '_worker', side_effect=AssertionError('Valid result must be reused')):
            self.assertTrue(self.service.transcribe(self.wav, model='test', profile='df005')['reused'])

    def test_tampered_review_or_raw_output_is_rejected_and_rerun(self):
        for mutate in (lambda p: p['segments'][0]['review'].update(status='verified'),
                       lambda p: p['raw_inference']['segments'][0].update(text='篡改'),
                       lambda p: p['review'].update(needs_review=5)):
            first = self.run_profile()
            path = Path(first['result_path'])
            envelope = json.loads(path.read_text())
            mutate(envelope['payload'])
            envelope['sha256'] = hashlib.sha256(canonical(envelope['payload'])).hexdigest()
            path.write_text(json.dumps(envelope, ensure_ascii=False))
            self.assertFalse(self.run_profile()['reused'])

    def test_unknown_profile_rejected_before_work(self):
        with patch.object(self.service, '_worker', side_effect=AssertionError('No inference')):
            with self.assertRaises(MediaError) as error:
                self.service.transcribe(self.wav, model='test', profile='magic')
        self.assertEqual(error.exception.code, 'unknown_profile')

    def test_medium_is_the_provisional_default(self):
        import inspect
        self.assertEqual(DEFAULT_MODEL, 'medium')
        self.assertEqual(inspect.signature(TranscriptionService.transcribe).parameters['model'].default, 'medium')
        self.assertEqual(inspect.signature(MediaService.transcribe).parameters['model'].default, 'medium')
        self.assertEqual(inspect.signature(MediaService.transcribe).parameters['profile'].default, 'df005')


if __name__ == '__main__':
    unittest.main()
