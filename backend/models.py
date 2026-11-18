"""Pinned, checksummed MLX model files contained in the workspace quota."""

import json
import http.client
import logging
from pathlib import Path
import shutil
import tempfile
import urllib.request
from uuid import uuid4

from backend.audio import checksum
from backend.media import MediaError
from backend.workspace import ROOT


class ModelStore:
    def __init__(self, workspace, specs=None):
        self.workspace = workspace
        self.specs = specs if specs is not None else json.loads((ROOT / 'models.lock.json').read_text())

    def spec(self, name):
        if name not in self.specs:
            raise MediaError('unknown_model', 'Choose a pinned multilingual model: ' + ', '.join(self.specs))
        return self.specs[name]

    def _valid(self, path, spec):
        try:
            allowed = {f['name'] for f in spec['files']} | {'provenance.json'}
            if any(p.name not in allowed for p in path.iterdir()):
                return False
            return all((path / f['name']).is_file() and not (path / f['name']).is_symlink()
                       and (path / f['name']).stat().st_size == f['size_bytes']
                       and checksum(path / f['name']) == f['sha256'] for f in spec['files'])
        except (OSError, MediaError):
            return False

    def ensure(self, name):
        spec = self.spec(name)
        if any(Path(f['name']).name != f['name'] or f['name'] in ('.', '..') for f in spec['files']):
            raise MediaError('invalid_model_spec', 'Invalid model filename')
        with self.workspace.locked():
            self.workspace.preflight(0)
            final = self.workspace.root / 'models' / (name + '-' + spec['revision'])
            if self._valid(final, spec):
                return final
            required = sum(f['size_bytes'] for f in spec['files']) + 65536
            self.workspace.preflight(required)
            stage = backup = None
            published = False
            try:
                final.parent.mkdir(exist_ok=True)
                staging = self.workspace.root / '.staging'
                staging.mkdir(exist_ok=True)
                stage = Path(tempfile.mkdtemp(prefix='model-', dir=staging))
                for item in spec['files']:
                    url = f"https://huggingface.co/{spec['repo']}/resolve/{spec['revision']}/{item['name']}"
                    count = 0
                    with urllib.request.urlopen(url, timeout=60) as response, (stage / item['name']).open('xb') as output:
                        while chunk := response.read(1024 * 1024):
                            count += len(chunk)
                            if count > item['size_bytes']:
                                raise MediaError('model_size_mismatch', 'Download exceeded pinned model size')
                            output.write(chunk)
                    if count != item['size_bytes'] or checksum(stage / item['name']) != item['sha256']:
                        raise MediaError('model_integrity', 'Model download size or SHA-256 mismatch')
                (stage / 'provenance.json').write_text(json.dumps(spec, indent=2) + '\n')
                self.workspace.preflight(0)
                try:
                    if final.exists():
                        backup = staging / ('replaced-model-' + uuid4().hex)
                        final.rename(backup)
                    stage.rename(final)
                    published = True
                except BaseException:
                    if backup and backup.exists():
                        backup.rename(final)
                        backup = None
                    raise
                return final
            except (OSError, http.client.HTTPException) as exc:
                raise MediaError('model_download_failed', 'Unable to download or publish pinned model') from exc
            finally:
                for path in (stage, backup if published else None):
                    if path is not None and path.exists():
                        try:
                            shutil.rmtree(path)
                        except OSError:
                            logging.getLogger(__name__).warning('Retained model staging for recovery: %s', path)
