import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import wave
import subprocess
import sys
from unittest.mock import patch

from backend.media import MediaError, MediaService
from backend.workspace import Workspace, WorkspaceConfig, StorageError
from backend.transcription import normalize_segments, character_error_rate, TranscriptionService, canonical, decode_options
from backend.models import ModelStore


class SegmentTests(unittest.TestCase):
    def test_cli_lists_bounded_opening(self):
        result = subprocess.run([sys.executable, '-m', 'backend.media', 'transcribe', '--help'],
                                check=True, capture_output=True, text=True)
        self.assertIn('bounded_opening', result.stdout)

    def test_bounded_opening_decodes_contiguous_intervals(self):
        baseline = decode_options('df005', None, None, 45000)
        for duration_ms, expected in ((9000, [0]), (10000, [0]), (10005, [0]),
                                      (10010, [0, 10, 10]),
                                      (17000, [0, 10, 10]),
                                      (45000, [0, 10, 10, 20, 20, 30, 30])):
            with self.subTest(duration_ms=duration_ms):
                self.assertEqual(decode_options('bounded_opening', None, None, duration_ms),
                                 dict(baseline, clip_timestamps=expected))

    def test_segments_preserve_chinese_and_confidence(self):
        raw = [{'start': 0.12, 'end': 1.25, 'text': ' 你好，中国。', 'avg_logprob': -0.2,
                'no_speech_prob': 0.01, 'compression_ratio': 1.1}]
        result = normalize_segments(raw, 2000)
        self.assertEqual((result[0]['start_ms'], result[0]['end_ms']), (120, 1250))
        self.assertEqual(result[0]['original_text'], '你好，中国。')
        self.assertEqual(result[0]['confidence']['avg_logprob'], -0.2)
        self.assertIsNone(normalize_segments([{'start':0,'end':1,'text':'测试'}],2000)[0]['confidence']['avg_logprob'])

    def test_invalid_segments_rejected(self):
        for raw in ([{'start': 1, 'end': 0, 'text': '错'}], [{'start': float('nan'), 'end':1,'text':'错'}],
                    [{'start': -1, 'end': 1, 'text': '错'}], [{'start':0,'end':1,'text':23}],
                    [{'start':0,'end':1,'text':'错','no_speech_prob':2}]):
            with self.subTest(raw=raw), self.assertRaises(MediaError):
                normalize_segments(raw,2000)

    def test_empty_zero_length_whisper_segment_is_ignored(self):
        raw=[{'start':0,'end':1,'text':'你好'},{'start':1,'end':1,'text':''}]
        diagnostics={}
        self.assertEqual(len(normalize_segments(raw,2000,diagnostics)),1)
        self.assertEqual(diagnostics['dropped_empty'],1)

    def test_tail_window_is_clipped_and_outside_segments_dropped(self):
        raw=[{'start':1,'end':30,'text':'你好'},{'start':3,'end':30,'text':'尾部幻觉'}]
        diagnostics={}
        result=normalize_segments(raw,2000,diagnostics)
        self.assertEqual(len(result),1)
        self.assertEqual((result[0]['start_ms'],result[0]['end_ms']),(1000,2000))
        self.assertEqual((diagnostics['clipped_end'],diagnostics['dropped_outside_audio']),(1,1))

    def test_cer_uses_reference_not_hypothesis(self):
        self.assertEqual(character_error_rate('你好，中国！','你好中国')['cer'],0)
        result=character_error_rate('你好中国','你好中')
        self.assertEqual((result['edits'],result['reference_characters'],result['cer']),(1,4,0.25))
        self.assertEqual(character_error_rate('你好','你号')['cer'],0.5)
        with self.assertRaises(ValueError):character_error_rate('','你好')


class ModelStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.workspace=Workspace(WorkspaceConfig(self.root/'workspace'))
        raw=b'fake model bytes'
        self.spec={'repo':'test/model','revision':'a'*40,'files':[{'name':'weights.npz','size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}]}
        self.raw=raw

    def test_pinned_download_and_corruption_detection(self):
        store=ModelStore(self.workspace,{'test':self.spec})
        import io
        with patch('backend.models.urllib.request.urlopen',return_value=io.BytesIO(self.raw)):
            path=store.ensure('test')
        self.assertEqual((path/'weights.npz').read_bytes(),self.raw)
        with patch('backend.models.urllib.request.urlopen',side_effect=AssertionError('Valid local model must not download')):
            self.assertEqual(store.ensure('test'),path)
        (path/'weights.npz').write_bytes(b'bad')
        with patch('backend.models.urllib.request.urlopen',return_value=io.BytesIO(self.raw)):
            self.assertEqual(store.ensure('test'),path)

    def test_oversize_download_never_publishes(self):
        import io
        store=ModelStore(self.workspace,{'test':self.spec})
        with patch('backend.models.urllib.request.urlopen',return_value=io.BytesIO(self.raw+b'oversized')):
            with self.assertRaises(MediaError):store.ensure('test')
        self.assertEqual(list((self.workspace.root/'models').glob('*')),[])

    def test_quota_denied_before_network(self):
        workspace=Workspace(WorkspaceConfig(self.root/'small',quota_bytes=1,reserve_bytes=0))
        with patch('backend.models.urllib.request.urlopen',side_effect=AssertionError('No network after capacity denial')):
            with self.assertRaises(StorageError):ModelStore(workspace,{'test':self.spec}).ensure('test')

    def test_unpinned_preferred_weights_are_not_loaded(self):
        import io
        store=ModelStore(self.workspace,{'test':self.spec})
        with patch('backend.models.urllib.request.urlopen',return_value=io.BytesIO(self.raw)):
            path=store.ensure('test')
        (path/'weights.safetensors').write_bytes(b'unverified preferred weights')
        with patch('backend.models.urllib.request.urlopen',return_value=io.BytesIO(self.raw)):
            store.ensure('test')
        self.assertFalse((path/'weights.safetensors').exists())

    def test_truncated_http_body_reports_media_error(self):
        import io
        from http.client import IncompleteRead
        class Truncated(io.BytesIO):
            def read(self,*args):raise IncompleteRead(b'partial',100)
        with patch('backend.models.urllib.request.urlopen',return_value=Truncated()):
            with self.assertRaises(MediaError):ModelStore(self.workspace,{'test':self.spec}).ensure('test')


class TranscriptionCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.workspace=Workspace(WorkspaceConfig(self.root/'workspace'))
        self.media=MediaService(self.workspace)
        self.service=TranscriptionService(self.media)
        self.wav=self.root/'speech.wav'
        with wave.open(str(self.wav),'wb') as output:
            output.setparams((1,2,16000,16000,'NONE','not compressed'));output.writeframes(b'\0'*32000)
        self.audio={'speech':{'path':str(self.wav),'sha256':hashlib.sha256(self.wav.read_bytes()).hexdigest(),'duration_seconds':1}}
        self.spec={'repo':'test/model','revision':'b'*40,'files':[{'name':'weights.npz','size_bytes':1,'sha256':hashlib.sha256(b'x').hexdigest()}]}
        self.service.models=ModelStore(self.workspace,{'test':self.spec})
        path=self.workspace.root/'models'/('test-'+'b'*40);path.mkdir(parents=True)
        (path/'weights.npz').write_bytes(b'x')
        self.raw={'segments':[{'start':0,'end':1,'text':'你好中国','avg_logprob':-0.1}],
                  'metrics':{'model_load_seconds':0.1,'inference_seconds':0.2,'peak_rss_bytes':10000,'mlx_peak_bytes':5000}}
        pipeline=patch('backend.transcription.AudioService.extract',return_value=self.audio)
        pipeline.start();self.addCleanup(pipeline.stop)

    def worker(self,audio,model,output,log,options=None):
        output.write_text(json.dumps(self.raw))

    def test_validated_reuse_and_checksum_repair(self):
        with patch.object(self.service,'_worker',side_effect=self.worker):
            first=self.service.transcribe(self.wav,model='test')
        with patch.object(self.service,'_worker',side_effect=AssertionError('Valid result must be reused')):
            second=self.service.transcribe(self.wav,model='test')
        self.assertTrue(second['reused'])
        self.assertEqual(second['segments'][0]['original_text'],'你好中国')
        path=Path(first['result_path']);path.write_text('corrupt')
        with patch.object(self.service,'_worker',side_effect=self.worker):
            self.assertFalse(self.service.transcribe(self.wav,model='test')['reused'])

    def test_bounded_opening_has_its_own_validated_cache(self):
        with patch.object(self.service, '_worker', side_effect=self.worker):
            baseline = self.service.transcribe(self.wav, model='test')
            bounded = self.service.transcribe(self.wav, model='test', profile='bounded_opening')
        self.assertNotEqual(baseline['result_path'], bounded['result_path'])
        self.assertEqual(bounded['raw_inference']['decode_options']['clip_timestamps'], [0])
        with patch.object(self.service, '_worker', side_effect=AssertionError('Expected a cache hit')):
            cached = self.service.transcribe(self.wav, model='test', profile='bounded_opening')
        self.assertTrue(cached['reused'])

    def test_inconsistent_cached_text_is_rejected(self):
        with patch.object(self.service,'_worker',side_effect=self.worker):
            first=self.service.transcribe(self.wav,model='test')
        path=Path(first['result_path']);envelope=json.loads(path.read_text())
        envelope['payload']['text']='错误的缓存正文'
        envelope['sha256']=hashlib.sha256(canonical(envelope['payload'])).hexdigest()
        path.write_text(json.dumps(envelope))
        with patch.object(self.service,'_worker',side_effect=self.worker):
            self.assertFalse(self.service.transcribe(self.wav,model='test')['reused'])

    def test_interrupted_worker_never_publishes(self):
        with patch.object(self.service,'_worker',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.service.transcribe(self.wav,model='test')
        self.assertEqual(list((self.workspace.root/'transcripts').glob('*.json')),[])
        self.assertEqual(list((self.workspace.root/'.staging').iterdir()),[])
        with patch.object(self.service,'_worker',side_effect=self.worker):
            self.assertFalse(self.service.transcribe(self.wav,model='test')['reused'])

    def test_timeout_reaps_real_child(self):
        self.service.timeout_seconds=0.05
        popen=subprocess.Popen
        def slow(command,**kwargs):
            return popen([sys.executable,'-c','import time; time.sleep(10)'],**kwargs)
        with patch('backend.transcription.subprocess.Popen',side_effect=slow):
            with self.assertRaises(MediaError) as error:self.service.transcribe(self.wav,model='test')
        self.assertEqual(error.exception.code,'transcription_timeout')
        self.assertEqual(list((self.workspace.root/'transcripts').glob('*.json')),[])

    def test_result_reservation_quota_denied(self):
        self.workspace.config=WorkspaceConfig(self.workspace.root,quota_bytes=1000,reserve_bytes=0)
        with patch.object(self.service,'_worker',side_effect=AssertionError('Inference must not start')):
            with self.assertRaises(StorageError):self.service.transcribe(self.wav,model='test')

    def test_submillisecond_duration_preserves_exact_rtf_and_reuses(self):
        frames=32005
        with wave.open(str(self.wav),'wb') as output:
            output.setparams((1,2,16000,frames,'NONE','not compressed'));output.writeframes(b'\0'*(frames*2))
        self.audio['speech'].update(sha256=hashlib.sha256(self.wav.read_bytes()).hexdigest(),duration_seconds=frames/16000)
        self.raw['metrics']['inference_seconds']=1.0
        with patch.object(self.service,'_worker',side_effect=self.worker):
            result=self.service.transcribe(self.wav,model='test')
        self.assertAlmostEqual(result['metrics']['real_time_factor'],16000/frames)
        with patch.object(self.service,'_worker',side_effect=AssertionError('Valid fractional-duration result must reuse')):
            self.assertTrue(self.service.transcribe(self.wav,model='test')['reused'])


if __name__=='__main__':unittest.main()
