from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from unittest.mock import patch

from backend.audio import AudioService
from backend.media import MediaError, MediaService
from backend.workspace import StorageError, Workspace, WorkspaceConfig

ROOT = Path(__file__).resolve().parent.parent


class AudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = tempfile.TemporaryDirectory()
        cls.sample = Path(cls.fixtures.name) / 'authorized stereo.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                        'color=c=green:s=160x120:r=10:d=3', '-f', 'lavfi', '-i',
                        'sine=frequency=440:sample_rate=48000:duration=3', '-c:v', 'libx264',
                        '-ac', '2', '-c:a', 'aac', '-shortest', str(cls.sample)],
                       check=True, capture_output=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.fixtures.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = (Path(self.temp.name) / 'workspace').resolve()
        self.workspace = Workspace(WorkspaceConfig(self.root))
        self.media = MediaService(self.workspace)
        self.audio = AudioService(self.media)

    def assert_clean(self):
        self.assertEqual(list((self.root / '.staging').glob('audio-*')), [])
        self.assertEqual(list((self.root / 'audio').glob('*')), [])

    def test_real_pcm_and_preserved_original(self):
        before = hashlib.sha256(self.sample.read_bytes()).hexdigest()
        result = self.media.extract_audio(self.sample, preserve_original=True)
        speech = result['speech']
        with wave.open(speech['path'], 'rb') as wav:
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 16000))
            self.assertAlmostEqual(wav.getnframes() / wav.getframerate(), 3, delta=0.1)
        self.assertEqual(speech['codec'], 'pcm_s16le')
        self.assertEqual(speech['sha256'], hashlib.sha256(Path(speech['path']).read_bytes()).hexdigest())
        original = result['original']
        self.assertEqual(original['tracks'][0]['codec'], 'aac')
        self.assertEqual(original['tracks'][0]['channels'], 2)
        self.assertEqual(original['tracks'][0]['sample_rate'], 48000)
        self.assertEqual(hashlib.sha256(self.sample.read_bytes()).hexdigest(), before)
        self.assertGreater(result['elapsed_seconds'], 0)

    def test_reuse_valid_output_without_rewriting_and_repair_corruption(self):
        first = self.audio.extract(self.sample)
        path = Path(first['speech']['path'])
        modified = path.stat().st_mtime_ns
        second = self.audio.extract(self.sample)
        self.assertTrue(second['reused'])
        self.assertEqual(path.stat().st_mtime_ns, modified)
        path.write_bytes(path.read_bytes()[:-20])
        repaired = self.audio.extract(self.sample)
        self.assertFalse(repaired['reused'])
        self.assertEqual(repaired['speech']['sha256'], first['speech']['sha256'])

    def test_preservation_upgrade_reuses_speech(self):
        first = self.audio.extract(self.sample)
        upgraded = self.audio.extract(self.sample, preserve_original=True)
        self.assertTrue(upgraded['speech_reused'])
        self.assertEqual(upgraded['speech']['sha256'], first['speech']['sha256'])
        self.assertTrue(Path(upgraded['original']['path']).is_file())

    def test_no_audio_and_invalid_input(self):
        silent = Path(self.temp.name) / 'silent.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(self.sample), '-an', '-c:v', 'copy', str(silent)], check=True, capture_output=True)
        with self.assertRaises(MediaError) as error:
            self.audio.extract(silent)
        self.assertEqual(error.exception.code, 'no_audio')
        bad = Path(self.temp.name) / 'bad.mp4'
        bad.write_bytes(b'corrupted')
        with self.assertRaises(MediaError):
            self.audio.extract(bad)
        with self.assertRaises(MediaError):
            self.audio.extract(self.sample, audio_track=99)

    def test_quota_rejects_before_any_output(self):
        workspace = Workspace(WorkspaceConfig(self.root, quota_bytes=100, reserve_bytes=0))
        with self.assertRaises(StorageError):
            AudioService(MediaService(workspace)).extract(self.sample)
        self.assert_clean()

    def test_missing_ffmpeg_and_timeout_cleanup(self):
        with self.assertRaises(MediaError):
            AudioService(self.media, ffmpeg='/missing/ffmpeg').extract(self.sample)
        self.assert_clean()
        slow = Path(self.temp.name) / 'slow-ffmpeg'
        slow.write_text('#!/bin/sh\nexec /bin/sleep 5\n')
        slow.chmod(0o755)
        with self.assertRaises(MediaError) as error:
            AudioService(self.media, ffmpeg=str(slow), timeout_seconds=0.05).extract(self.sample)
        self.assertEqual(error.exception.code, 'extraction_timeout')
        self.assert_clean()

    def test_competing_extractions_reuse_one_output(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            outputs = list(pool.map(lambda _: self.audio.extract(self.sample), range(2)))
        self.assertCountEqual([entry['reused'] for entry in outputs], [True, False])
        self.assertEqual(outputs[0]['speech']['path'], outputs[1]['speech']['path'])

    def test_cli_and_sigterm_cleanup(self):
        env = dict(os.environ, DRAMAFLOW_WORKSPACE=str(self.root))
        result = subprocess.run([str(ROOT / 'scripts/media.sh'), 'extract-audio', str(self.sample)], cwd='/tmp', env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['speech']['sample_rate'], 16000)
        # Different workspace avoids a cache hit. A slow wrapper exposes a marker
        # after FFmpeg starts; SIGTERM must reap it before removing staging.
        env['DRAMAFLOW_WORKSPACE'] = str(self.root / 'interrupted')
        bindir = Path(self.temp.name) / 'bin'
        bindir.mkdir()
        marker = Path(self.temp.name) / 'child.pid'
        wrapper = bindir / 'ffmpeg'
        wrapper.write_text('#!/bin/sh\necho $$ > "' + str(marker) + '"\nexec /bin/sleep 20\n')
        wrapper.chmod(0o755)
        env['PATH'] = str(bindir) + os.pathsep + env['PATH']
        process = subprocess.Popen([sys.executable, '-m', 'backend.media', 'extract-audio', str(self.sample)], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), 'FFmpeg child did not start')
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=5)
            self.assertNotEqual(process.returncode, 0)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(marker.read_text()), 0)
            self.assertEqual(list((Path(env['DRAMAFLOW_WORKSPACE']) / '.staging').glob('audio-*')), [])
            self.assertEqual(list((Path(env['DRAMAFLOW_WORKSPACE']) / 'audio').glob('*')), [])
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_malformed_cache_manifest_is_not_reused(self):
        first = self.audio.extract(self.sample)
        manifest = Path(first['speech']['path']).parent / 'metadata.json'
        payload = json.loads(manifest.read_text())
        del payload['speech']['sha256']
        manifest.write_text(json.dumps(payload))
        result = self.audio.extract(self.sample)
        self.assertFalse(result['reused'])

    def test_original_audio_shorter_than_video(self):
        shorter = Path(self.temp.name) / 'short-audio.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                        'color=s=160x120:r=10:d=3', '-f', 'lavfi', '-i',
                        'sine=duration=1:sample_rate=48000', '-c:v', 'libx264', '-c:a', 'aac', str(shorter)],
                       check=True, capture_output=True, timeout=15)
        result = self.audio.extract(shorter, preserve_original=True)
        self.assertAlmostEqual(result['speech']['duration_seconds'], 1, delta=0.1)
        self.assertAlmostEqual(result['original']['duration_seconds'], 1, delta=0.1)

    def test_child_file_size_limit_prevents_unbounded_output(self):
        oversized = Path(self.temp.name) / 'oversized-ffmpeg'
        oversized.write_text('#!' + sys.executable + '\nimport sys\nwith open(sys.argv[-1], "wb") as out:\n out.write(b"x" * (2 * 1024 * 1024))\n')
        oversized.chmod(0o755)
        with self.assertRaises(MediaError):
            AudioService(self.media, ffmpeg=str(oversized)).extract(self.sample)
        self.assert_clean()

    def test_corrupted_audio_packets_fail_without_publication(self):
        corrupt = Path(self.temp.name) / 'damaged-audio.mp4'
        shutil.copyfile(self.sample, corrupt)
        packet_info = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_packets',
                                      '-show_entries', 'packet=pos,size', '-of', 'json', str(corrupt)],
                                     check=True, capture_output=True, text=True)
        with corrupt.open('r+b') as output:
            for packet in json.loads(packet_info.stdout)['packets'][:3]:
                output.seek(int(packet['pos']))
                output.write(b'\xff' * int(packet['size']))
        self.media.inspect(corrupt)  # Header/metadata remain usable.
        with self.assertRaises(MediaError) as error:
            self.audio.extract(corrupt)
        self.assertEqual(error.exception.code, 'extraction_failed')
        self.assert_clean()

    def test_authorized_180_second_video(self):
        sample = Path(self.temp.name) / 'authorized-180s.mp4'
        subprocess.run([str(ROOT / 'scripts/create_audio_sample.sh'), str(sample)], check=True, capture_output=True, timeout=45)
        result = self.audio.extract(sample, preserve_original=True)
        self.assertAlmostEqual(result['speech']['duration_seconds'], 180, delta=0.1)
        self.assertEqual(result['speech']['sample_rate'], 16000)
        self.assertEqual(result['speech']['channels'], 1)
        self.assertGreater(result['speech']['size_bytes'], 180 * 32000)
        self.assertTrue(self.audio.extract(sample, preserve_original=True)['reused'])

    def test_selected_track_and_preservation_of_all_tracks(self):
        multiple = Path(self.temp.name) / 'multiple.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(self.sample), '-f', 'lavfi', '-i',
                        'sine=frequency=880:duration=3:sample_rate=32000', '-map', '0:v', '-map', '0:a', '-map', '1:a',
                        '-c:v', 'copy', '-c:a', 'aac', str(multiple)], check=True, capture_output=True, timeout=15)
        first = self.audio.extract(multiple, audio_track=0)
        second = self.audio.extract(multiple, audio_track=1, preserve_original=True)
        self.assertNotEqual(first['speech']['sha256'], second['speech']['sha256'])
        self.assertEqual(len(second['original']['tracks']), 2)
        self.assertEqual(second['original']['tracks'][1]['sample_rate'], 32000)

    def test_cross_process_cache_serialization(self):
        env = dict(os.environ, DRAMAFLOW_WORKSPACE=str(self.root))
        command = [sys.executable, '-m', 'backend.media', 'extract-audio', str(self.sample)]
        children = [subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        try:
            records = []
            for child in children:
                stdout, stderr = child.communicate(timeout=15)
                self.assertEqual(child.returncode, 0, stderr)
                records.append(json.loads(stdout))
            self.assertCountEqual([record['reused'] for record in records], [True, False])
            self.assertEqual(records[0]['speech']['path'], records[1]['speech']['path'])
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.communicate()

    def test_publish_failure_retains_valid_existing_speech(self):
        first = self.audio.extract(self.sample)
        original_rename = Path.rename
        def fail_publication(path, target):
            if path.name.startswith('audio-') and path.parent.name == '.staging':
                raise OSError('Simulated publish failure')
            return original_rename(path, target)
        with patch('backend.audio.Path.rename', new=fail_publication):
            with self.assertRaises(MediaError):
                self.audio.extract(self.sample, preserve_original=True)
        self.assertEqual(hashlib.sha256(Path(first['speech']['path']).read_bytes()).hexdigest(), first['speech']['sha256'])
        self.assertTrue(self.audio.extract(self.sample)['reused'])

    def test_failed_publication_and_rollback_retains_recovery_backup(self):
        first = self.audio.extract(self.sample)
        original_rename = Path.rename
        def fail_staging_rename(path, target):
            if path.parent.name == '.staging':
                raise OSError('Simulated publish and rollback failure')
            return original_rename(path, target)
        with patch('backend.audio.Path.rename', new=fail_staging_rename):
            with self.assertRaises(MediaError):
                self.audio.extract(self.sample, preserve_original=True)
        backups = list((self.root / '.staging').glob('replaced-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(hashlib.sha256((backups[0] / 'speech.wav').read_bytes()).hexdigest(), first['speech']['sha256'])

    def test_exited_child_is_not_signalled_again(self):
        failed = Path(self.temp.name) / 'failed-ffmpeg'
        failed.write_text('#!/bin/sh\nexit 2\n')
        failed.chmod(0o755)
        with patch('backend.audio.os.killpg', side_effect=AssertionError('Reaped child group must not be signalled')):
            with self.assertRaises(MediaError) as error:
                AudioService(self.media, ffmpeg=str(failed)).extract(self.sample)
        self.assertEqual(error.exception.code, 'extraction_failed')

    def test_cleanup_failure_does_not_mask_success(self):
        self.audio.extract(self.sample)
        with patch('backend.audio.shutil.rmtree', side_effect=OSError('Cleanup denied')):
            with self.assertLogs('backend.audio', level='WARNING'):
                result = self.audio.extract(self.sample, preserve_original=True)
        self.assertTrue(Path(result['speech']['path']).is_file())
        self.assertTrue(Path(result['original']['path']).is_file())
        self.assertEqual(len(list((self.root / '.staging').glob('replaced-*'))), 1)

    def test_interruption_after_backup_rename_restores_existing_output(self):
        first = self.audio.extract(self.sample)
        original_rename = Path.rename
        def interrupt_after_rename(path, target):
            result = original_rename(path, target)
            if Path(target).name.startswith('replaced-'):
                raise KeyboardInterrupt
            return result
        with patch('backend.audio.Path.rename', new=interrupt_after_rename):
            with self.assertRaises(KeyboardInterrupt):
                self.audio.extract(self.sample, preserve_original=True)
        self.assertEqual(hashlib.sha256(Path(first['speech']['path']).read_bytes()).hexdigest(), first['speech']['sha256'])


if __name__ == '__main__':
    unittest.main()
