"""FastAPI entry point.

Development: `uv run uvicorn app.main:app --reload`, with the Vite dev server
proxying /api here. Local production: once the UI is built, this process
serves it too, so the whole app is one process on one port.
"""

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.db import REPO_ROOT, check_database, get_db

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

Db = Annotated[sqlite3.Connection, Depends(get_db)]

api = APIRouter(prefix="/api")


class Health(BaseModel):
    status: Literal["ok"]
    schema_version: int


@api.get("/health")
def health(db: Db) -> Health:
    version = db.execute("PRAGMA user_version").fetchone()[0]
    return Health(status="ok", schema_version=version)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    check_database()
    yield


def create_app(frontend_dist: Path = FRONTEND_DIST) -> FastAPI:
    app = FastAPI(title="LAMP Target List", lifespan=lifespan)
    app.include_router(api)
    # Mounted after the router, so /api/* always reaches the API.
    if frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    return app


app = create_app()
