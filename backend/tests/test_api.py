import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import SCHEMA_VERSION
from app.main import create_app


def test_health_reports_schema_version(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "schema_version": SCHEMA_VERSION}


def test_startup_fails_without_a_database_and_does_not_create_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.sqlite"
    monkeypatch.setenv("LAMP_DB_PATH", str(missing))
    app = create_app(frontend_dist=tmp_path / "no-dist")
    with pytest.raises(RuntimeError, match="init_db.py"), TestClient(app):
        pass
    assert not missing.exists()


def test_startup_fails_on_a_schema_version_mismatch(db_path: Path, tmp_path: Path) -> None:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA user_version = 99")
    app = create_app(frontend_dist=tmp_path / "no-dist")
    with pytest.raises(RuntimeError, match="schema version 99"), TestClient(app):
        pass


def test_serves_the_built_frontend_without_shadowing_the_api(db_path: Path, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text('<div id="root"></div>')
    with TestClient(create_app(frontend_dist=dist)) as client:
        assert '<div id="root">' in client.get("/").text
        assert client.get("/api/health").json()["status"] == "ok"
