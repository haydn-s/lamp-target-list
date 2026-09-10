"""SQLite access: one short-lived connection per request, plain SQL, no ORM."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "data" / "lamp.sqlite"

# Must match `PRAGMA user_version` in db/schema.sql. The app refuses to start
# against a database built from any other version of the template.
SCHEMA_VERSION = 1


def database_path() -> Path:
    # A relative LAMP_DB_PATH is taken from the repo root, where
    # scripts/init_db.py is run, not from wherever uvicorn was started.
    path = Path(os.environ.get("LAMP_DB_PATH", DEFAULT_DB))
    return path if path.is_absolute() else REPO_ROOT / path


def connect(path: Path | None = None) -> sqlite3.Connection:
    # mode=rw never creates the file. A missing database is a setup error, and
    # quietly starting an empty one would look exactly like data loss.
    uri = f"{(path or database_path()).resolve().as_uri()}?mode=rw"
    # check_same_thread=False: FastAPI may run a dependency and its endpoint on
    # different worker threads. Each connection still serves only one request.
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite defaults this to off on every connection
    return conn


def check_database(path: Path | None = None) -> None:
    """Fail at startup, with the fix in the message, if the database is missing or stale."""
    path = path or database_path()
    try:
        conn = connect(path)
    except sqlite3.OperationalError as e:
        raise RuntimeError(
            f"Cannot open the database at {path} ({e}). Create it with: python3 scripts/init_db.py"
        ) from None
    with closing(conn):
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        raise RuntimeError(
            f"The database at {path} is schema version {version}, "
            f"but this code expects version {SCHEMA_VERSION}."
        )


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: a connection that lives for one request."""
    with closing(connect()) as conn:
        yield conn
