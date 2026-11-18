import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class SmokeTests(unittest.TestCase):
    def setUp(self):
        from backend.main import create_app
        self.create_app = create_app
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'nested' / 'test.sqlite3'

    def test_health_and_persistent_sqlite(self):
        for _ in range(2):
            with TestClient(self.create_app(self.db)) as client:
                response = client.get('/health')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {'status': 'ok', 'database': 'ok'})
            with sqlite3.connect(self.db) as connection:
                self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(connection.execute('SELECT version FROM schema_version').fetchall(), [(1,)])

    def test_system_reports_real_resources_and_missing_tools(self):
        with TestClient(self.create_app(self.db)) as client:
            with patch.dict(os.environ, {'PATH': ''}):
                response = client.get('/api/system/status')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['status'], 'degraded')
        self.assertEqual(body['database']['status'], 'ok')
        self.assertTrue(body['runtime']['python'])
        self.assertTrue(body['runtime']['architecture'])
        self.assertGreater(body['resources']['ram_total_bytes'], 0)
        self.assertGreater(body['resources']['disk_free_bytes'], 0)
        for name in ('node', 'git', 'ffmpeg', 'ffprobe'):
            self.assertFalse(body['tools'][name]['available'])

    def test_database_loss_returns_503(self):
        with TestClient(self.create_app(self.db)) as client:
            self.db.unlink()
            response = client.get('/health')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()['database'], 'unavailable')
            self.assertEqual(client.get('/api/system/status').json()['database']['status'], 'unavailable')
        self.assertFalse(self.db.exists(), 'Readiness checks must not silently create a database')

    def test_tool_probe_timeout_is_reported(self):
        from backend.system import tool_status
        executable = Path(self.temp.name) / 'slow-tool'
        executable.write_text('#!/bin/sh\nexec /bin/sleep 5\n')
        executable.chmod(0o755)
        with patch.dict(os.environ, {'PATH': self.temp.name}):
            result = tool_status('slow-tool', '--version', timeout=0.05)
        self.assertFalse(result['available'])
        self.assertEqual(result['error'], 'timeout')

    def test_configured_database_path(self):
        with patch.dict(os.environ, {'DRAMAFLOW_DB_PATH': str(self.db)}):
            with TestClient(self.create_app()) as client:
                self.assertEqual(client.get('/health').status_code, 200)
        self.assertTrue(self.db.is_file())

    def test_disk_probe_failure_is_reported_as_unknown(self):
        with TestClient(self.create_app(self.db)) as client:
            with patch('backend.system.shutil.disk_usage', side_effect=OSError('unavailable')):
                response = client.get('/api/system/status')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['resources']['disk_free_bytes'])
        self.assertIsNone(response.json()['resources']['disk_total_bytes'])
        self.assertEqual(response.json()['status'], 'degraded')

    def test_non_utf8_tool_output_does_not_crash(self):
        from backend.system import tool_status
        executable = Path(self.temp.name) / 'binary-version'
        executable.write_bytes(b'#!/bin/sh\nprintf "version \\377\\n"\n')
        executable.chmod(0o755)
        with patch.dict(os.environ, {'PATH': self.temp.name}):
            result = tool_status('binary-version', '--version')
        self.assertTrue(result['available'])
        self.assertTrue(result['version'].startswith('version '))


if __name__ == '__main__':
    unittest.main()
