#!/usr/bin/env python3
"""Create a fresh local database from the committed template, db/schema.sql.

    python3 scripts/init_db.py [PATH]

PATH defaults to $LAMP_DB_PATH (taken relative to the repo root, as the backend
does), then data/lamp.sqlite. Uses only the standard library, so it works
before any backend dependencies are installed.

It never overwrites an existing file, because the live database holds data
that exists nowhere else. Delete the file yourself to start over.
"""

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "db" / "schema.sql"
DEFAULT_DB = ROOT / "data" / "lamp.sqlite"
MIN_SQLITE = (3, 37, 0)  # first release with STRICT tables


def main() -> int:
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
    else:
        target = Path(os.environ.get("LAMP_DB_PATH", DEFAULT_DB))
        if not target.is_absolute():
            target = ROOT / target

    if sqlite3.sqlite_version_info < MIN_SQLITE:
        sys.exit(f"SQLite {sqlite3.sqlite_version} is too old; the template needs 3.37 or newer.")
    if target.exists():
        sys.exit(f"{target} already exists; refusing to overwrite it.")

    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    try:
        conn.executescript(TEMPLATE.read_text(encoding="utf-8"))
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    except BaseException:
        conn.close()
        target.unlink(missing_ok=True)  # don't leave a half-built database behind
        raise
    conn.close()

    print(f"Created {target} from {TEMPLATE.relative_to(ROOT)} (schema version {version}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
