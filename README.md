# DramaFlow

Independent local backend and media foundation for DramaFlow (DF-003).

The upstream reference is a separate, unchanged sibling checkout at
`../hongguo-drama`. See [upstream sources](docs/UPSTREAM_SOURCES.md) for provenance.

Requirements: macOS ARM64 and Python 3.12. Node.js, Git, FFmpeg, and FFprobe
are detected for diagnostics; missing media tools do not prevent backend startup.
The media service and its tests require FFmpeg/FFprobe. Install with
`brew install ffmpeg`; verify both with `file -L /opt/homebrew/bin/ffmpeg /opt/homebrew/bin/ffprobe`.

```sh
./scripts/setup.sh
./scripts/test.sh
./scripts/start.sh
```

If Python is outside PATH:
`PYTHON=/opt/homebrew/bin/python3.12 ./scripts/setup.sh`.
Setup installs the fully pinned `requirements.txt` into `.venv` only.
The scripts work from any current directory. Stop the server with Ctrl-C.

- `GET http://127.0.0.1:8000/health`: HTTP 200 when SQLite is ready;
  HTTP 503 if it becomes unavailable.
- `GET http://127.0.0.1:8000/api/system/status`: HTTP 200 diagnostic snapshot
  of runtime, total RAM, free/total project-volume disk, tool versions, and SQLite.
  Overall status is `degraded` when a required tool or SQLite is unavailable.
  Failed resource probes report `null` rather than an invented value.

The server binds only to `127.0.0.1`. Set `PORT` to override 8000.
SQLite initializes on startup at `data/dramaflow.sqlite3`; set
`DRAMAFLOW_DB_PATH` to override it. Relative paths are resolved against the
repository root. Runtime data, virtual environments, and caches are ignored.
The initial schema contains only a schema-version table. Startup fails visibly
if the database cannot be initialized; readiness probes never recreate a missing DB.

No AI models, upstream code integration, frontend, or paid APIs are included.
See [DF-002 verification](docs/DF-002_ENVIRONMENT.md) for environment and results.

## Local video import

```sh
./scripts/create_sample.sh
./scripts/media.sh probe data/samples/authorized-generated.mp4
./scripts/media.sh storage --incoming-bytes 86446
./scripts/media.sh import data/samples/authorized-generated.mp4
./scripts/media.sh storage
```

The sample script generates original synthetic color and sine-wave content,
and refuses to overwrite an existing sample. No downloaded or upstream assets.
For a file of another size, preflight with its size **plus 65,536 bytes** for
metadata. The import command always performs its own serialized preflight.
CLI commands emit JSON; errors and denied capacity checks exit nonzero.
Scripts resolve relative source paths against the repository root.

Reusable Python interfaces: `MediaService(workspace).inspect(path)` and
`.import_video(path)` in `backend/media.py`; `WorkspaceConfig`, `Workspace.status()`
and `.preflight(incoming_bytes)` in `backend/workspace.py`.

Set `DRAMAFLOW_WORKSPACE` to change the workspace directory (relative paths are
rooted at the repository); default: ignored `data/workspace`. Keep a custom
workspace outside Git or explicitly ignore it. The default storage quota is
**60 GB = 60,000,000,000 bytes**, with **1 GiB = 1,073,741,824 bytes** physical
disk headroom. Logical file sizes count toward quota, including manifests,
staging and existing files. Files elsewhere, including the source, virtual
environment, SQLite database and sample outside the workspace, are subject
to physical disk checks but do not consume the workspace quota.

The service accepts local regular MOV/MP4, Matroska/WebM, and AVI containers.
It requires positive finite duration, positive video dimensions, known codec
names, valid audio channels/sample rates for every audio track, and matching
nonzero file size. Silent video is allowed; audio-only and cover-image-only
inputs are rejected. No network protocols or playlist demuxers are enabled.
Each FFprobe run has a 15-second timeout.

Imports preserve the source and create a UUID directory containing the copied
media and a JSON manifest with metadata and SHA-256. Copies are bounded to the
preflighted size, re-probed, and published with an atomic directory rename.
An advisory file lock serializes cooperating imports. Failed staging is removed;
crash leftovers remain counted toward quota. Symlinks within the workspace
are rejected. Use a dedicated local workspace; unrelated external writers are
not controlled by its advisory lock. FFprobe checks metadata, not full decode
integrity, and recognized codecs are not a guarantee of future processing support.
Atomic publication is not a power-loss durability guarantee: files/directories
are not fsynced. Lock acquisition waits without a timeout.

See [DF-003 verification](docs/DF-003_MEDIA.md) for actual media and storage results.
