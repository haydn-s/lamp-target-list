"""Rules the database enforces on its own, whatever writes to it.

See "Where rules are enforced" in the README. Rules the API owns are tested
next to the endpoints that implement them.
"""

import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.db import SCHEMA_VERSION, connect

# The seeded rows below are the only ones of their kind, so tests can refer to
# them with a subquery instead of threading ids around.
COMPANY = "(SELECT id FROM company)"
APP = "(SELECT id FROM application)"
CONTACT = "(SELECT id FROM contact)"


@pytest.fixture
def db(db_path: Path) -> Iterator[sqlite3.Connection]:
    """A template database holding one company, application, contact, resume and advocate."""
    conn = connect(db_path)
    conn.isolation_level = None  # autocommit: each statement stands alone
    conn.executescript(f"""
        INSERT INTO company (name, priority_tier) VALUES ('Acme', 'A');
        INSERT INTO application (company_id, target_role) VALUES ({COMPANY}, 'Software Engineer');
        INSERT INTO contact (name, company_id) VALUES ('Pat', {COMPANY});
        INSERT INTO resume_version (label, file_path, content_hash)
            VALUES ('v1', 'resumes/v1.pdf', 'abc');
        INSERT INTO application_advocate (application_id, contact_id) VALUES ({APP}, {CONTACT});
    """)
    yield conn
    conn.close()


def add_application(db: sqlite3.Connection, outcome: str | None = None) -> int:
    cursor = db.execute(
        f"INSERT INTO application (company_id, target_role, outcome) VALUES ({COMPANY}, 'SRE', ?)",
        (outcome,),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def log(
    db: sqlite3.Connection, app: int, stage: str, days_ago: int, note: str | None = None
) -> None:
    db.execute(
        "INSERT INTO stage_event (application_id, stage, occurred_on, note) "
        "VALUES (?, ?, date('now', 'localtime', ?), ?)",
        (app, stage, f"-{days_ago} days", note),
    )


def status(db: sqlite3.Connection, app: int) -> tuple[object, ...]:
    """(current_stage, furthest_stage, days_idle, is_live) from the derived-status view."""
    row = db.execute(
        "SELECT current_stage, furthest_stage, days_idle, is_live"
        " FROM application_status WHERE application_id = ?",
        (app,),
    ).fetchone()
    return tuple(row)


def count(db: sqlite3.Connection, table: str) -> int:
    return int(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def test_template_version_and_stage_vocabulary(db: sqlite3.Connection) -> None:
    assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    live = [
        r[0] for r in db.execute("SELECT name FROM stage WHERE is_terminal = 0 ORDER BY ordinal")
    ]
    assert live == [
        "researching",
        "applied",
        "assessment",
        "screen",
        "interviewing",
        "final_round",
        "offer",
    ]
    terminal = {r[0] for r in db.execute("SELECT name FROM stage WHERE is_terminal = 1")}
    assert terminal == {"rejected", "ghosted", "withdrawn"}


INVALID_ROWS = [
    pytest.param(
        "CHECK constraint failed: priority_tier",
        "INSERT INTO company (name, priority_tier) VALUES ('Beta', 'D')",
        id="tier-outside-ABC",
    ),
    pytest.param(
        "UNIQUE constraint failed: company.name",
        "INSERT INTO company (name) VALUES ('ACME')",
        id="company-name-unique-any-case",
    ),
    pytest.param(
        "CHECK constraint failed: work_model",
        f"INSERT INTO application (company_id, target_role, work_model)"
        f" VALUES ({COMPANY}, 'x', 'office')",
        id="unknown-work-model",
    ),
    pytest.param(
        "CHECK constraint failed: posting_date",
        f"INSERT INTO application (company_id, target_role, posting_date)"
        f" VALUES ({COMPANY}, 'x', '2026-02-30')",
        id="impossible-date",
    ),
    pytest.param(
        "CHECK constraint failed: posting_date",
        f"INSERT INTO application (company_id, target_role, posting_date)"
        f" VALUES ({COMPANY}, 'x', '2026-9-1')",
        id="unpadded-date",
    ),
    pytest.param(
        "cannot store TEXT value in INTEGER column",
        "INSERT INTO application (company_id, target_role) VALUES ('one', 'x')",
        id="strict-column-types",
    ),
    pytest.param(
        "CHECK constraint failed: flag_relocation",
        f"INSERT INTO application (company_id, target_role, flag_relocation)"
        f" VALUES ({COMPANY}, 'x', 2)",
        id="flag-not-boolean",
    ),
    pytest.param(
        "FOREIGN KEY constraint failed",
        "INSERT INTO application (company_id, target_role) VALUES (999, 'x')",
        id="missing-company",
    ),
    pytest.param(
        "FOREIGN KEY constraint failed",
        f"INSERT INTO stage_event (application_id, stage, occurred_on)"
        f" VALUES ({APP}, 'phone_call', '2026-09-01')",
        id="unknown-stage",
    ),
    pytest.param(
        "CHECK constraint failed: channel",
        f"INSERT INTO interaction (contact_id, occurred_on, channel)"
        f" VALUES ({CONTACT}, '2026-09-01', 'fax')",
        id="unknown-channel",
    ),
    pytest.param(
        "NOT NULL constraint failed: next_action.due_date",
        f"INSERT INTO next_action (application_id, description) VALUES ({APP}, 'Follow up')",
        id="next-action-needs-due-date",
    ),
    pytest.param(
        "CHECK constraint failed: completed_at",
        f"INSERT INTO next_action (application_id, description, due_date, completed_at)"
        f" VALUES ({APP}, 'Follow up', '2026-09-12', 'yesterday')",
        id="unparseable-timestamp",
    ),
    pytest.param(
        "UNIQUE constraint failed: resume_version.content_hash",
        "INSERT INTO resume_version (label, file_path, content_hash)"
        " VALUES ('copy', 'resumes/copy.pdf', 'abc')",
        id="same-resume-file-twice",
    ),
    pytest.param(
        "UNIQUE constraint failed: application_advocate",
        f"INSERT INTO application_advocate (application_id, contact_id) VALUES ({APP}, {CONTACT})",
        id="duplicate-advocate",
    ),
]


@pytest.mark.parametrize(("error", "sql"), INVALID_ROWS)
def test_rejects_invalid_rows(db: sqlite3.Connection, error: str, sql: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=re.escape(error)):
        db.execute(sql)


def test_current_stage_is_the_latest_event_and_idle_days_count_from_it(
    db: sqlite3.Connection,
) -> None:
    app = add_application(db)
    log(db, app, "researching", 30)
    log(db, app, "applied", 25)
    log(db, app, "screen", 20)  # assessment skipped: forward skips are fine
    log(db, app, "interviewing", 15)
    log(db, app, "interviewing", 10)  # repeat rounds are just more events
    assert status(db, app) == ("interviewing", "interviewing", 10, 1)


def test_application_without_events_has_no_stage_and_is_live(db: sqlite3.Connection) -> None:
    assert status(db, add_application(db)) == (None, None, None, 1)


def test_regression_becomes_current_while_furthest_keeps_the_high_mark(
    db: sqlite3.Connection,
) -> None:
    app = add_application(db)
    log(db, app, "final_round", 10)
    log(db, app, "interviewing", 3, note="team reorganized; one more round")
    assert status(db, app) == ("interviewing", "final_round", 3, 1)


def test_backfilled_history_does_not_move_the_current_stage(db: sqlite3.Connection) -> None:
    app = add_application(db)
    log(db, app, "interviewing", 5)
    log(db, app, "applied", 20)  # typed in afterwards, dated earlier
    assert status(db, app) == ("interviewing", "interviewing", 5, 1)


def test_same_day_events_resolve_to_the_later_stage(db: sqlite3.Connection) -> None:
    app = add_application(db)
    log(db, app, "screen", 0)
    log(db, app, "applied", 0)  # same day, typed in second
    assert status(db, app) == ("screen", "screen", 0, 1)


def test_terminal_stage_requires_an_outcome(db: sqlite3.Connection) -> None:
    app = add_application(db)
    log(db, app, "applied", 5)
    with pytest.raises(sqlite3.IntegrityError, match="requires application.outcome"):
        log(db, app, "rejected", 0)
    db.execute("UPDATE application SET outcome = 'rejected_no_response' WHERE id = ?", (app,))
    log(db, app, "rejected", 0)
    # A terminal stage closes the application but never counts as progress.
    assert status(db, app) == ("rejected", "applied", 0, 0)


def test_revived_application_shows_its_new_stage_but_stays_closed_until_reopened(
    db: sqlite3.Connection,
) -> None:
    app = add_application(db, outcome="ghosted")
    log(db, app, "applied", 40)
    log(db, app, "ghosted", 10)
    log(db, app, "screen", 2, note="recruiter came back")
    assert status(db, app) == ("screen", "screen", 2, 0)
    db.execute("UPDATE application SET outcome = NULL WHERE id = ?", (app,))
    assert status(db, app) == ("screen", "screen", 2, 1)


def test_offer_stays_live_until_resolved(db: sqlite3.Connection) -> None:
    app = add_application(db)
    log(db, app, "offer", 2)
    assert status(db, app) == ("offer", "offer", 2, 1)
    db.execute("UPDATE application SET outcome = 'offer_accepted' WHERE id = ?", (app,))
    assert status(db, app) == ("offer", "offer", 2, 0)


def test_stage_events_cannot_be_edited_but_can_be_deleted(db: sqlite3.Connection) -> None:
    app = add_application(db)
    log(db, app, "applied", 3)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("UPDATE stage_event SET occurred_on = '2026-01-01'")
    db.execute("DELETE FROM stage_event")
    assert status(db, app) == (None, None, None, 1)


def test_company_with_applications_cannot_be_deleted(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        db.execute("DELETE FROM company")


def test_resume_version_in_use_cannot_be_deleted(db: sqlite3.Connection) -> None:
    db.execute("UPDATE application SET resume_version_id = (SELECT id FROM resume_version)")
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        db.execute("DELETE FROM resume_version")


def test_deleting_an_application_cascades_to_its_own_records(db: sqlite3.Connection) -> None:
    db.executescript(f"""
        INSERT INTO stage_event (application_id, stage, occurred_on) VALUES ({APP}, 'applied', '2026-09-01');
        INSERT INTO next_action (application_id, description, due_date) VALUES ({APP}, 'Follow up', '2026-09-12');
        INSERT INTO posting_snapshot (application_id, raw_text) VALUES ({APP}, 'We are hiring');
        INSERT INTO interaction (contact_id, application_id, occurred_on, channel)
            VALUES ({CONTACT}, {APP}, '2026-09-01', 'email');
    """)
    db.execute("DELETE FROM application")
    for table in ("stage_event", "next_action", "posting_snapshot", "application_advocate"):
        assert count(db, table) == 0, table
    # The interaction belongs to the contact; it survives, unlinked.
    assert [tuple(r) for r in db.execute("SELECT application_id FROM interaction")] == [(None,)]


def test_deleting_a_company_keeps_its_contacts(db: sqlite3.Connection) -> None:
    db.execute("DELETE FROM application")
    db.execute("DELETE FROM company")
    assert db.execute("SELECT company_id FROM contact").fetchone()[0] is None


def test_timestamps_default_to_iso_8601_utc(db: sqlite3.Connection) -> None:
    created_at = db.execute("SELECT created_at FROM resume_version").fetchone()[0]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", created_at)
