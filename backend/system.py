"""Read-only, bounded checks of the host runtime."""

import platform
import shutil
import subprocess
from pathlib import Path


def tool_status(name: str, flag: str, timeout: float = 2) -> dict:
    executable = shutil.which(name)
    if executable is None:
        return {'available': False, 'version': None, 'error': 'not_found'}
    try:
        result = subprocess.run([executable, flag], capture_output=True, text=True, errors='replace', timeout=timeout)
        lines = (result.stdout or result.stderr).splitlines()
        return {
            'available': result.returncode == 0,
            'version': lines[0] if lines else None,
            'error': None if result.returncode == 0 else 'probe_failed',
        }
    except subprocess.TimeoutExpired:
        return {'available': False, 'version': None, 'error': 'timeout'}
    except OSError:
        return {'available': False, 'version': None, 'error': 'probe_failed'}


def snapshot(disk_path: Path) -> dict:
    ram = None
    if platform.system() == 'Darwin':
        try:
            result = subprocess.run(['/usr/sbin/sysctl', '-n', 'hw.memsize'], capture_output=True, text=True, timeout=2, check=True)
            ram = int(result.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    try:
        disk = shutil.disk_usage(disk_path)
        disk_total, disk_free = disk.total, disk.free
    except OSError:
        disk_total, disk_free = None, None
    return {
        'runtime': {
            'os': platform.system(),
            'os_version': platform.mac_ver()[0] or platform.release(),
            'architecture': platform.machine(),
            'python': platform.python_version(),
        },
        'resources': {'ram_total_bytes': ram, 'disk_total_bytes': disk_total, 'disk_free_bytes': disk_free},
        'tools': {name: tool_status(name, flag) for name, flag in (
            ('node', '--version'), ('git', '--version'), ('ffmpeg', '-version'), ('ffprobe', '-version')
        )},
    }
