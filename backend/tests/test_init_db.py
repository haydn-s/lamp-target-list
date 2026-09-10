"""scripts/init_db.py: how a fresh clone gets its database."""

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from app.db import REPO_ROOT, SCHEMA_VERSION

SCRIPT = REPO_ROOT / "scripts" / "init_db.py"


def run_init(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, check=False
    )


def test_builds_the_database_from_the_template(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "lamp.sqlite"
    result = run_init(str(target))
    assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(target)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_refuses_to_overwrite_an_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "lamp.sqlite"
    target.write_bytes(b"irreplaceable")
    result = run_init(str(target))
    assert result.returncode != 0
    assert "refusing to overwrite" in result.stderr
    assert target.read_bytes() == b"irreplaceable"


def test_honors_lamp_db_path(tmp_path: Path) -> None:
    target = tmp_path / "from-env.sqlite"
    result = run_init(env={**os.environ, "LAMP_DB_PATH": str(target)})
    assert result.returncode == 0, result.stderr
    assert target.exists()
