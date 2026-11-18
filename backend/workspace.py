"""Local workspace configuration, accounting, and serialized storage preflight."""

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent


class StorageError(RuntimeError):
    """Storage cannot safely accept the requested import."""


@dataclass(frozen=True)
class WorkspaceConfig:
    root: Path
    quota_bytes: int = 60_000_000_000
    reserve_bytes: int = 1_073_741_824

    def __post_init__(self):
        path = Path(self.root).expanduser()
        object.__setattr__(self, 'root', (ROOT / path).resolve())
        if self.quota_bytes <= 0 or self.reserve_bytes < 0:
            raise ValueError('Quota must be positive; disk reserve must be non-negative')

    @classmethod
    def from_env(cls):
        value = os.environ.get('DRAMAFLOW_WORKSPACE', 'data/workspace')
        if not value.strip():
            raise ValueError('DRAMAFLOW_WORKSPACE must name a directory')
        return cls(Path(value))


class Workspace:
    def __init__(self, config: WorkspaceConfig):
        self.config = config
        self.root = config.root

    def _prepare(self):
        self.root.mkdir(parents=True, exist_ok=True)

    def _used_bytes(self) -> int:
        def walk(directory):
            total = 0
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        raise StorageError('Symlinks are not allowed inside the workspace')
                    if entry.is_dir(follow_symlinks=False):
                        total += walk(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    else:
                        raise StorageError('Workspace contains a non-regular file')
            return total
        return walk(self.root)

    def status(self, incoming_bytes: int = 0) -> dict:
        if not isinstance(incoming_bytes, int) or isinstance(incoming_bytes, bool) or incoming_bytes < 0:
            raise ValueError('Incoming bytes must be a non-negative integer')
        try:
            self._prepare()
            used = self._used_bytes()
            free = shutil.disk_usage(self.root).free
        except OSError as exc:
            raise StorageError('Unable to check workspace capacity') from exc
        remaining = max(0, self.config.quota_bytes - used)
        physical = max(0, free - self.config.reserve_bytes)
        return {
            'root': str(self.root), 'quota_bytes': self.config.quota_bytes,
            'used_bytes': used, 'remaining_bytes': remaining,
            'disk_free_bytes': free, 'disk_reserve_bytes': self.config.reserve_bytes,
            'incoming_bytes': incoming_bytes,
            'can_import': used + incoming_bytes <= self.config.quota_bytes
                          and incoming_bytes + self.config.reserve_bytes <= free,
            'effective_available_bytes': min(remaining, physical),
        }

    def preflight(self, incoming_bytes: int) -> dict:
        result = self.status(incoming_bytes)
        if not result['can_import']:
            raise StorageError('Import exceeds workspace quota or available disk headroom')
        return result

    @contextmanager
    def locked(self):
        try:
            self._prepare()
            fd = os.open(self.root / '.import.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            raise StorageError('Unable to open workspace import lock') from exc
        with os.fdopen(fd, 'r+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
