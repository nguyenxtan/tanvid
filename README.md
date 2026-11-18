# DramaFlow

Independent local backend foundation for DramaFlow (DF-002).

The upstream reference is a separate, unchanged sibling checkout at
`../hongguo-drama`. See [upstream sources](docs/UPSTREAM_SOURCES.md) for provenance.

Requirements: macOS ARM64 and Python 3.12. Node.js, Git, FFmpeg, and FFprobe
are detected for diagnostics; missing media tools do not prevent backend startup.

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
