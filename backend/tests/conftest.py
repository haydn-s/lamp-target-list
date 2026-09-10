import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import REPO_ROOT
from app.main import create_app

TEMPLATE = REPO_ROOT / "db" / "schema.sql"


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh database built from the committed template, and pointed to by LAMP_DB_PATH."""
    path = tmp_path / "lamp.sqlite"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(TEMPLATE.read_text(encoding="utf-8"))
    monkeypatch.setenv("LAMP_DB_PATH", str(path))
    return path


@pytest.fixture
def client(db_path: Path, tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(frontend_dist=tmp_path / "no-dist")) as client:
        yield client
