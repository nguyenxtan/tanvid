# DF-002: Environment and runtime foundation

Scope: implement the PO's DF-002 request only. No upstream integration,
models, frontend, or paid APIs. Use the existing independent repository.

Design: a local FastAPI application, SQLite through Python's standard library,
and an isolated Python 3.12 virtual environment. Use Uvicorn without optional
extras and standard-library unittest with HTTPX for ASGI smoke tests.
Pin the complete resolved dependency set. Do not install missing media tools.

- [x] Verify OS, architecture, runtimes, media tools, RAM, and free disk.
- [x] Write smoke tests for endpoint responses, database persistence and failure,
      missing tools, and bounded tool probes; run them before implementation.
- [x] Add `backend/main.py` (application factory and endpoints),
      `backend/database.py` (SQLite lifecycle), and `backend/system.py`
      (read-only environment checks).
- [x] Add cwd-independent setup/start/test scripts and document configuration.
- [x] Run the full smoke suite, dependency checks, and live localhost HTTP checks.
- [x] Request Claude cross-review, resolve material findings, record results.
- [x] Create the initial Git commit; report evidence and stop for PO approval (commit is the final step of this plan).

Contracts: `/health` reports backend/database readiness (503 if database fails).
`/api/system/status` reports actual runtime, RAM, free disk, tool availability,
and database state; missing tools produce degraded status without preventing
backend startup. SQLite is initialized at startup, with a configurable path
(`DRAMAFLOW_DB_PATH`); the default is ignored `data/dramaflow.sqlite3`.
Bind to `127.0.0.1:8000` by default. Bound external version probes with timeouts.

Review focus: missing executables, failed/timed-out probes, database loss,
restart persistence, scripts run from outside the repository, ignored runtime data.
