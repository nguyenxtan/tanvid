"""Reusable local video validation/import service and JSON command line interface."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import signal
import subprocess
import sys
import tempfile
from uuid import uuid4

from backend.workspace import StorageError, Workspace, WorkspaceConfig

MANIFEST_BUDGET = 65_536


class MediaError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def validate_probe(payload: dict, size_bytes: int) -> dict:
    """Normalize FFprobe metadata; reject absent or unusable video/audio fields."""
    try:
        container = payload['format']
        duration = float(container['duration'])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('Duration must be finite and positive')
        if size_bytes <= 0 or int(container['size']) != size_bytes:
            raise ValueError('Probe file size does not match the actual file')

        def positive(value):
            if isinstance(value, bool):
                raise ValueError('Invalid integer')
            result = int(value)
            if result <= 0 or str(result) != str(value):
                raise ValueError('Expected positive integer')
            return result

        videos, audios = [], []
        for stream in payload['streams']:
            kind = stream.get('codec_type')
            if kind not in ('video', 'audio'):
                continue
            if kind == 'video' and stream.get('disposition', {}).get('attached_pic', 0):
                continue
            codec = stream.get('codec_name')
            if not isinstance(codec, str) or codec in ('', 'unknown', 'none'):
                raise ValueError('Missing or unknown codec')
            track = {'index': int(stream['index']), 'codec': codec}
            if kind == 'video':
                track.update(width=positive(stream['width']), height=positive(stream['height']))
                videos.append(track)
            else:
                track.update(channels=positive(stream['channels']), sample_rate=positive(stream['sample_rate']))
                if stream.get('duration') not in (None, 'N/A'):
                    track_duration = float(stream['duration'])
                    if not math.isfinite(track_duration) or track_duration <= 0:
                        raise ValueError('Invalid audio stream duration')
                    track['duration_seconds'] = track_duration
                audios.append(track)
        if not videos:
            raise ValueError('At least one real video track is required')
        return {'duration_seconds': duration, 'size_bytes': size_bytes,
                'container': container['format_name'], 'video_tracks': videos, 'audio_tracks': audios}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise MediaError('invalid_metadata', 'Invalid media metadata: ' + str(exc)) from exc


class MediaService:
    def __init__(self, workspace: Workspace, ffprobe: str = 'ffprobe', timeout_seconds: float = 15):
        self.workspace = workspace
        self.ffprobe = ffprobe
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _source(path: Path) -> tuple[Path, os.stat_result]:
        path = Path(path).expanduser().absolute()
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
                raise MediaError('invalid_file', 'Source must be a non-empty regular local file')
            return path, info
        except OSError as exc:
            raise MediaError('invalid_file', 'Source is missing or inaccessible') from exc

    def inspect(self, source: Path) -> dict:
        path, before = self._source(source)
        try:
            result = subprocess.run([
                self.ffprobe, '-v', 'error', '-protocol_whitelist', 'file',
                '-format_whitelist', 'mov,matroska,webm,avi',
                '-show_entries', 'format=duration,size,format_name:stream=index,codec_type,codec_name,width,height,channels,sample_rate,duration:stream_disposition=attached_pic',
                '-of', 'json', '-i', str(path),
            ], capture_output=True, text=True, errors='replace', timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise MediaError('probe_timeout', 'FFprobe timed out') from exc
        except OSError as exc:
            raise MediaError('probe_unavailable', 'FFprobe could not be executed') from exc
        if result.returncode != 0:
            raise MediaError('invalid_media', 'FFprobe rejected the input or its container is unsupported')
        try:
            payload = json.loads(result.stdout)
        except (ValueError, TypeError) as exc:
            raise MediaError('invalid_probe', 'FFprobe returned invalid JSON') from exc
        metadata = validate_probe(payload, before.st_size)
        _, after = self._source(path)
        if self._identity(before) != self._identity(after):
            raise MediaError('source_changed', 'Source changed while it was being probed')
        return metadata

    @staticmethod
    def _identity(info: os.stat_result):
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns

    def import_video(self, source: Path) -> dict:
        source, before = self._source(source)
        metadata = self.inspect(source)
        required = before.st_size + MANIFEST_BUDGET
        with self.workspace.locked():
            self.workspace.preflight(required)
            staging = self.workspace.root / '.staging'
            imports = self.workspace.root / 'imports'
            stage = None
            try:
                staging.mkdir(exist_ok=True)
                imports.mkdir(exist_ok=True)
                stage = Path(tempfile.mkdtemp(prefix='import-', dir=staging))
                identifier = uuid4().hex
                suffix = source.suffix.lower()
                if len(suffix) > 12 or not suffix[1:].isalnum():
                    suffix = '.video'
                filename = 'source' + suffix
                target = stage / filename
                digest = hashlib.sha256()
                copied = 0
                # Bound copy size so a growing source cannot defeat the reservation.
                with source.open('rb') as reader, target.open('xb') as writer:
                    if self._identity(os.fstat(reader.fileno())) != self._identity(before):
                        raise MediaError('source_changed', 'Source changed before copying')
                    while chunk := reader.read(min(1024 * 1024, before.st_size - copied + 1)):
                        copied += len(chunk)
                        if copied > before.st_size:
                            raise MediaError('source_changed', 'Source grew while copying')
                        writer.write(chunk)
                        digest.update(chunk)
                _, after = self._source(source)
                if copied != before.st_size or self._identity(before) != self._identity(after):
                    raise MediaError('source_changed', 'Source changed while copying')
                staged_metadata = self.inspect(target)
                if staged_metadata != metadata:
                    raise MediaError('source_changed', 'Staged metadata differs from source')
                final = imports / identifier
                record = {'id': identifier, 'path': str(final / filename),
                          'original_name': source.name, 'sha256': digest.hexdigest(), 'metadata': staged_metadata}
                manifest = (json.dumps(record, indent=2, allow_nan=False) + '\n').encode()
                if len(manifest) > MANIFEST_BUDGET:
                    raise MediaError('metadata_too_large', 'Metadata exceeds reserved capacity')
                (stage / 'metadata.json').write_bytes(manifest)
                # Count the staged files and recheck physical headroom immediately before publication.
                self.workspace.preflight(0)
                stage.rename(final)
                return record
            except OSError as exc:
                raise MediaError('import_failed', 'Unable to copy or publish media') from exc
            finally:
                if stage is not None and stage.exists():
                    shutil.rmtree(stage)

    def extract_audio(self, source: Path, audio_track: int = 0, preserve_original: bool = False) -> dict:
        from backend.audio import AudioService
        return AudioService(self).extract(source, audio_track, preserve_original)

    def transcribe(self, source: Path, model: str = 'small', audio_track: int = 0, force: bool = False) -> dict:
        from backend.transcription import TranscriptionService
        return TranscriptionService(self).transcribe(source, model, audio_track, force)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('probe', 'import'):
        commands.add_parser(name).add_argument('source', type=Path)
    commands.add_parser('storage').add_argument('--incoming-bytes', type=int, default=0)
    extraction = commands.add_parser('extract-audio')
    extraction.add_argument('source', type=Path)
    extraction.add_argument('--audio-track', type=int, default=0)
    extraction.add_argument('--preserve-original', action='store_true')
    transcription = commands.add_parser('transcribe')
    transcription.add_argument('source', type=Path)
    transcription.add_argument('--model', choices=('small', 'medium'), default='small')
    transcription.add_argument('--audio-track', type=int, default=0)
    transcription.add_argument('--force', action='store_true', help='Run fresh inference instead of using a valid result')
    args = parser.parse_args()
    try:
        workspace = Workspace(WorkspaceConfig.from_env())
        service = MediaService(workspace)
        if args.command == 'probe':
            result = service.inspect(args.source)
        elif args.command == 'import':
            result = service.import_video(args.source)
        elif args.command in ('extract-audio', 'transcribe'):
            # Signal handlers are CLI-only; library callers own cancellation.
            previous = signal.getsignal(signal.SIGTERM)
            def interrupted(signum, frame):
                raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, interrupted)
            try:
                if args.command == 'transcribe':
                    result = service.transcribe(args.source, args.model, args.audio_track, args.force)
                else:
                    result = service.extract_audio(args.source, args.audio_track, args.preserve_original)
            finally:
                signal.signal(signal.SIGTERM, previous)
        else:
            result = workspace.status(args.incoming_bytes)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 1 if args.command == 'storage' and not result['can_import'] else 0
    except (MediaError, StorageError, ValueError) as exc:
        print(json.dumps({'error': getattr(exc, 'code', 'storage_error'), 'message': str(exc)}), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(json.dumps({'error': 'interrupted', 'message': 'Media processing interrupted; incomplete result not published'}), file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
