import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from backend.media import MediaError, MediaService, validate_probe
from backend.workspace import StorageError, Workspace, WorkspaceConfig


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = tempfile.TemporaryDirectory()
        cls.sample = Path(cls.fixtures.name) / 'authorized sample.mp4'
        subprocess.run([
            'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'color=c=blue:s=320x240:r=25:d=2',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '64k',
            '-shortest', '-movflags', '+faststart', str(cls.sample),
        ], check=True, capture_output=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.fixtures.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = (Path(self.temp.name) / 'workspace').resolve()
        self.workspace = Workspace(WorkspaceConfig(self.root))
        self.service = MediaService(self.workspace)

    def test_real_mp4_metadata(self):
        metadata = self.service.inspect(self.sample)
        self.assertAlmostEqual(metadata['duration_seconds'], 2, places=1)
        self.assertEqual(metadata['size_bytes'], self.sample.stat().st_size)
        self.assertEqual(metadata['video_tracks'][0]['width'], 320)
        self.assertEqual(metadata['video_tracks'][0]['height'], 240)
        self.assertEqual(metadata['video_tracks'][0]['codec'], 'h264')
        self.assertEqual(len(metadata['audio_tracks']), 1)
        self.assertEqual(metadata['audio_tracks'][0]['codec'], 'aac')
        self.assertEqual(metadata['audio_tracks'][0]['sample_rate'], 48000)
        self.assertEqual(metadata['audio_tracks'][0]['channels'], 1)

    def test_import_preserves_source_and_writes_manifest(self):
        before = self.sample.read_bytes()
        result = self.service.import_video(self.sample)
        imported = Path(result['path'])
        self.assertTrue(imported.is_relative_to(self.root))
        self.assertEqual(imported.read_bytes(), before)
        self.assertEqual(self.sample.read_bytes(), before)
        self.assertEqual(result['sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(json.loads((imported.parent / 'metadata.json').read_text()), result)
        self.assertGreater(self.workspace.status()['used_bytes'], len(before))
        self.assertEqual(list((self.root / '.staging').iterdir()), [])

    def test_invalid_local_inputs(self):
        empty = Path(self.temp.name) / 'empty.mp4'
        empty.touch()
        corrupt = Path(self.temp.name) / 'corrupt.mp4'
        corrupt.write_bytes(b'not a video')
        for source in (empty, corrupt, self.root, Path(self.temp.name) / 'missing.mp4'):
            with self.subTest(source=source), self.assertRaises(MediaError):
                self.service.inspect(source)

    def test_audio_only_is_not_a_video_and_silent_video_is_valid(self):
        silent = Path(self.temp.name) / 'silent.mp4'
        audio = Path(self.temp.name) / 'audio.m4a'
        for output, flags in ((silent, ['-an', '-c:v', 'copy']), (audio, ['-vn', '-c:a', 'copy'])):
            subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-i', str(self.sample), *flags, str(output)], check=True, capture_output=True, timeout=10)
        self.assertEqual(self.service.inspect(silent)['audio_tracks'], [])
        with self.assertRaises(MediaError):
            self.service.inspect(audio)

    def test_probe_missing_timeout_and_malformed_json(self):
        for name, body in (
            ('slow', '#!/bin/sh\nexec /bin/sleep 5\n'),
            ('bad-json', '#!/bin/sh\nprintf "not-json"\n'),
            ('failed', '#!/bin/sh\nexit 2\n'),
        ):
            executable = Path(self.temp.name) / name
            executable.write_text(body)
            executable.chmod(0o755)
            with self.subTest(name=name), self.assertRaises(MediaError):
                MediaService(self.workspace, ffprobe=str(executable), timeout_seconds=0.05).inspect(self.sample)
        with self.assertRaises(MediaError):
            MediaService(self.workspace, ffprobe='/does/not/exist').inspect(self.sample)

    def test_invalid_metadata_is_rejected(self):
        valid = {'format': {'duration': '2', 'size': '100', 'format_name': 'mov,mp4'},
                 'streams': [{'index': 0, 'codec_type': 'video', 'codec_name': 'h264', 'width': 320, 'height': 240},
                             {'index': 1, 'codec_type': 'audio', 'codec_name': 'aac', 'channels': 1, 'sample_rate': '48000'}]}
        self.assertEqual(validate_probe(valid, 100)['duration_seconds'], 2.0)
        for field, value in (('duration', 'NaN'), ('duration', 'Infinity'), ('duration', '0'), ('size', '99')):
            payload = copy.deepcopy(valid)
            payload['format'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(MediaError):
                validate_probe(payload, 100)
        for track, field, value in ((0, 'width', 0), (0, 'height', -1), (0, 'codec_name', 'unknown'),
                                    (1, 'channels', 0), (1, 'sample_rate', 'N/A'), (1, 'codec_name', None)):
            payload = copy.deepcopy(valid)
            payload['streams'][track][field] = value
            with self.subTest(field=field), self.assertRaises(MediaError):
                validate_probe(payload, 100)
        for payload in ({}, [], {'streams': []}, {'format': valid['format'], 'streams': [valid['streams'][1]]}):
            with self.subTest(payload=payload), self.assertRaises(MediaError):
                validate_probe(payload, 100)

    def test_failed_staged_validation_rolls_back(self):
        inspect = self.service.inspect
        def reject_staged(path):
            if Path(path).is_relative_to(self.root):
                raise MediaError('invalid_media', 'Rejected staged file')
            return inspect(path)
        with patch.object(self.service, 'inspect', side_effect=reject_staged):
            with self.assertRaises(MediaError):
                self.service.import_video(self.sample)
        self.assertEqual(list((self.root / '.staging').iterdir()), [])
        self.assertEqual(list((self.root / 'imports').iterdir()), [])

    def test_quota_prevents_concurrent_overcommit(self):
        workspace = Workspace(WorkspaceConfig(self.root, quota_bytes=self.sample.stat().st_size + 65536, reserve_bytes=0))
        def run_import(_):
            try:
                MediaService(workspace).import_video(self.sample)
                return 'ok'
            except StorageError:
                return 'full'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(run_import, range(2))), ['ok', 'full'])
        self.assertEqual(len(list((self.root / 'imports').iterdir())), 1)

    def test_source_change_before_copy_rolls_back(self):
        source = Path(self.temp.name) / 'changing.mp4'
        shutil.copyfile(self.sample, source)
        inspect = self.service.inspect
        def change_after_probe(path):
            metadata = inspect(path)
            if Path(path) == source:
                with source.open('ab') as output:
                    output.write(b'changed')
            return metadata
        with patch.object(self.service, 'inspect', side_effect=change_after_probe):
            with self.assertRaises(MediaError) as error:
                self.service.import_video(source)
        self.assertEqual(error.exception.code, 'source_changed')
        self.assertEqual(list((self.root / '.staging').iterdir()), [])
        self.assertEqual(list((self.root / 'imports').iterdir()), [])

    def test_failed_copy_rolls_back(self):
        original_open = Path.open
        def fail_output(path, mode='r', *args, **kwargs):
            if mode == 'xb':
                raise OSError('Simulated full disk')
            return original_open(path, mode, *args, **kwargs)
        with patch('backend.media.Path.open', new=fail_output):
            with self.assertRaises(MediaError):
                self.service.import_video(self.sample)
        self.assertEqual(list((self.root / '.staging').iterdir()), [])
        self.assertEqual(list((self.root / 'imports').iterdir()), [])

    def test_symlink_and_playlist_input_are_rejected(self):
        link = Path(self.temp.name) / 'linked.mp4'
        link.symlink_to(self.sample)
        playlist = Path(self.temp.name) / 'playlist.mp4'
        playlist.write_text('#EXTM3U\nhttps://example.invalid/video.ts\n')
        for source in (link, playlist):
            with self.subTest(source=source), self.assertRaises(MediaError):
                self.service.inspect(source)

    def test_invalid_workspace_layout_reports_import_error(self):
        self.root.mkdir()
        (self.root / 'imports').write_text('Not a directory')
        with self.assertRaises(MediaError) as error:
            self.service.import_video(self.sample)
        self.assertEqual(error.exception.code, 'import_failed')


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = (Path(self.temp.name) / 'workspace').resolve()

    def test_default_config_and_environment(self):
        config = WorkspaceConfig(self.root)
        self.assertEqual(config.quota_bytes, 60000000000)
        self.assertEqual(config.reserve_bytes, 1073741824)
        with patch.dict(os.environ, {'DRAMAFLOW_WORKSPACE': str(self.root)}):
            self.assertEqual(WorkspaceConfig.from_env().root, self.root)

    def test_existing_files_and_staging_count_and_exact_quota_boundary(self):
        workspace = Workspace(WorkspaceConfig(self.root, quota_bytes=100, reserve_bytes=0))
        self.root.mkdir()
        (self.root / 'existing').write_bytes(b'x' * 30)
        (self.root / '.staging').mkdir()
        (self.root / '.staging' / 'partial').write_bytes(b'x' * 20)
        self.assertEqual(workspace.status()['used_bytes'], 50)
        workspace.preflight(50)
        with self.assertRaises(StorageError):
            workspace.preflight(51)

    def test_physical_capacity_and_failed_disk_probe(self):
        workspace = Workspace(WorkspaceConfig(self.root, quota_bytes=10000, reserve_bytes=100))
        with patch('backend.workspace.shutil.disk_usage', return_value=shutil._ntuple_diskusage(1000, 850, 150)):
            workspace.preflight(50)
            with self.assertRaises(StorageError):
                workspace.preflight(51)
        with patch('backend.workspace.shutil.disk_usage', side_effect=OSError('unavailable')):
            with self.assertRaises(StorageError):
                workspace.preflight(1)

    def test_symlinks_are_rejected(self):
        self.root.mkdir()
        (self.root / 'outside').symlink_to(Path(self.temp.name), target_is_directory=True)
        with self.assertRaises(StorageError):
            Workspace(WorkspaceConfig(self.root)).preflight(1)


if __name__ == '__main__':
    unittest.main()
