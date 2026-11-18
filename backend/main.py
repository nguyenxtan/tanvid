"""FastAPI application; importing this module has no database side effects."""

from contextlib import asynccontextmanager
import os
from pathlib import Path
import sqlite3

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend import database
from backend.system import snapshot

ROOT = Path(__file__).resolve().parent.parent


def create_app(db_path: Path | None = None) -> FastAPI:
    configured = Path(db_path or os.environ.get('DRAMAFLOW_DB_PATH', ROOT / 'data/dramaflow.sqlite3')).expanduser()
    path = (ROOT / configured).resolve() if not configured.is_absolute() else configured.resolve()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.initialize(path)
        yield

    app = FastAPI(title='DramaFlow', version='0.1.0', lifespan=lifespan)

    @app.get('/health')
    def health():
        ready = database.is_ready(path)
        return JSONResponse(
            {'status': 'ok' if ready else 'degraded', 'database': 'ok' if ready else 'unavailable'},
            status_code=200 if ready else 503,
        )

    @app.get('/api/system/status')
    def system_status():
        result = snapshot(ROOT)
        ready = database.is_ready(path)
        result['database'] = {'status': 'ok' if ready else 'unavailable', 'sqlite_version': sqlite3.sqlite_version}
        healthy = (ready and all(tool['available'] for tool in result['tools'].values())
                   and all(value is not None for value in result['resources'].values()))
        result['status'] = 'ok' if healthy else 'degraded'
        return result

    return app
