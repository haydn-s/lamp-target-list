-- =============================================================================
-- LAMP Target List: SQLite schema template
--
-- The committed template for the local database. The live database
-- (data/lamp.sqlite) is gitignored because it holds personal data. Create it
-- from this file with:
--
--     python3 scripts/init_db.py
--
-- Requires SQLite >= 3.37 for STRICT tables.
--
-- SQLite does not store PRAGMA foreign_keys in the file. Every connection must
-- run `PRAGMA foreign_keys = ON;` or the REFERENCES clauses below are ignored.
--
-- Conventions
--   * Dates are TEXT 'YYYY-MM-DD'. `CHECK (x IS date(x))` rejects anything
--     else, including impossible dates such as 2026-02-30.
--   * Timestamps are TEXT ISO-8601 UTC, e.g. '2026-09-10T14:03:00Z'.
--   * Enumerations are CHECK constraints. SQLite cannot alter a constraint in
--     place, so changing one means rebuilding the table; trivial at this size.
--   * Nothing derived is stored. Current stage, idle days and liveness come
--     from the application_status view at the bottom of this file.
--   * No secondary indexes: at ~60 applications every query scans a few KB.
--
-- Design source: PROJECT_BRIEF.md sections 2-4. Bump user_version whenever
-- the shape of this file changes.
-- =============================================================================

BEGIN;

PRAGMA user_version = 1;

-- -----------------------------------------------------------------------------
-- Stage vocabulary. A table rather than a CHECK because queries need the
-- ordering: current stage = highest-ordinal event. Terminal stages share an
-- ordinal above every live stage, so once one is logged it is the current
-- stage.
-- -----------------------------------------------------------------------------
CREATE TABLE stage (
    name        TEXT    PRIMARY KEY,
    ordinal     INTEGER NOT NULL,
    is_terminal INTEGER NOT NULL CHECK (is_terminal IN (0, 1))
) STRICT;

INSERT INTO stage (name, ordinal, is_terminal) VALUES
    ('researching',   1, 0),
    ('applied',       2, 0),
    ('assessment',    3, 0),
    ('screen',        4, 0),
    ('interviewing',  5, 0),
    ('final_round',   6, 0),
    ('offer',         7, 0),
    ('rejected',     99, 1),
    ('ghosted',      99, 1),
    ('withdrawn',    99, 1);

-- -----------------------------------------------------------------------------
-- Companies: the target list itself. The goal is 40.
-- -----------------------------------------------------------------------------
CREATE TABLE company (
    id            INTEGER PRIMARY KEY,
    -- Unique so the sheet importer can upsert companies by name.
    name          TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    industry      TEXT,   -- free text; the UI autocompletes from prior values
    priority_tier TEXT    CHECK (priority_tier IN ('A', 'B', 'C')),  -- NULL = not yet triaged
    -- Two sentences on why this company. The API requires it before an
    -- application moves past 'researching'. Not enforced here, because
    -- imported spreadsheet history would violate it.
    motivation    TEXT,
    website       TEXT,
    notes         TEXT
) STRICT;

-- -----------------------------------------------------------------------------
-- Resume versions: a real entity so callback rates can be attributed to a
-- specific file. The files live under data/resumes/ (gitignored).
-- -----------------------------------------------------------------------------
CREATE TABLE resume_version (
    id           INTEGER PRIMARY KEY,
    label        TEXT NOT NULL,
    file_path    TEXT NOT NULL,         -- relative to data/
    content_hash TEXT NOT NULL UNIQUE,  -- sha256 hex; the same file is never stored twice
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
) STRICT;

-- -----------------------------------------------------------------------------
-- Applications: one per role applied to; a company can have several.
-- There is deliberately no status column. See stage_event.
-- -----------------------------------------------------------------------------
CREATE TABLE application (
    id                 INTEGER PRIMARY KEY,
    company_id         INTEGER NOT NULL REFERENCES company (id) ON DELETE RESTRICT,
    target_role        TEXT    NOT NULL,  -- what you want there
    applied_role_title TEXT,              -- what you actually applied to
    role_type          TEXT    CHECK (role_type IN ('full_time', 'internship', 'co_op', 'contract')),
    location           TEXT,
    work_model         TEXT    CHECK (work_model IN ('onsite', 'hybrid', 'remote')),

    -- `flags` is a multi-select in the UI, stored as one boolean per flag so
    -- each is directly sortable and filterable. Adding a flag is an
    -- ALTER TABLE ... ADD COLUMN flag_<name>, which SQLite does in place.
    flag_clearance_required INTEGER NOT NULL DEFAULT 0 CHECK (flag_clearance_required IN (0, 1)),
    flag_no_sponsorship     INTEGER NOT NULL DEFAULT 0 CHECK (flag_no_sponsorship     IN (0, 1)),
    flag_new_grad_program   INTEGER NOT NULL DEFAULT 0 CHECK (flag_new_grad_program   IN (0, 1)),
    flag_relocation         INTEGER NOT NULL DEFAULT 0 CHECK (flag_relocation         IN (0, 1)),

    req_id             TEXT,
    posting_url        TEXT,
    posting_date       TEXT    CHECK (posting_date IS date(posting_date)),  -- drives the stale-posting alert
    ats                TEXT    CHECK (ats IN ('workday', 'greenhouse', 'lever', 'ashby', 'icims',
                                              'taleo', 'smartrecruiters', 'company_site', 'other')),
    source             TEXT    CHECK (source IN ('cold_apply', 'referral', 'recruiter_inbound',
                                                 'career_fair', 'alumni', 'event')),
    resume_version_id  INTEGER REFERENCES resume_version (id) ON DELETE RESTRICT,
    comp_posted        TEXT,              -- text: postings give ranges in mixed units
    -- Close reason. NULL while the application is live.
    outcome            TEXT    CHECK (outcome IN ('rejected_no_response', 'rejected_post_screen',
                                                  'rejected_post_interview', 'ghosted', 'withdrew',
                                                  'offer_declined', 'offer_accepted', 'role_closed')),
    -- Not in the brief's field list. Needed so the sheet's per-row notes
    -- survive import; company.notes would merge several applications.
    notes              TEXT
) STRICT;

-- -----------------------------------------------------------------------------
-- Stage events: the append-only history that replaces the sheet's six
-- milestone date columns. Repeat rounds are simply more rows at one stage.
-- -----------------------------------------------------------------------------
CREATE TABLE stage_event (
    id             INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES application (id) ON DELETE CASCADE,
    stage          TEXT    NOT NULL REFERENCES stage (name),
    occurred_on    TEXT    NOT NULL CHECK (occurred_on IS date(occurred_on)),
    note           TEXT
) STRICT;

-- Entering a terminal stage requires an outcome. Set application.outcome
-- first, then insert the event, in one transaction.
CREATE TRIGGER stage_event_terminal_requires_outcome
BEFORE INSERT ON stage_event
WHEN (SELECT is_terminal FROM stage WHERE name = NEW.stage) = 1
 AND (SELECT outcome FROM application WHERE id = NEW.application_id) IS NULL
BEGIN
    SELECT RAISE(ABORT, 'entering a terminal stage requires application.outcome to be set');
END;

-- Events are never edited; a regression is a new event with a note. DELETE
-- stays allowed so a mis-keyed event can be removed, and so deleting an
-- application can cascade.
CREATE TRIGGER stage_event_no_update
BEFORE UPDATE ON stage_event
BEGIN
    SELECT RAISE(ABORT, 'stage_event is append-only: delete and re-insert to correct a mistake');
END;

-- -----------------------------------------------------------------------------
-- People and touchpoints
-- -----------------------------------------------------------------------------
CREATE TABLE contact (
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    company_id      INTEGER REFERENCES company (id) ON DELETE SET NULL,
    role            TEXT,
    how_i_know_them TEXT,
    linkedin_url    TEXT,
    email           TEXT,
    notes           TEXT
) STRICT;

-- Someone actively pushing an application internally. Distinct from
-- application.source: source is how the lead arrived, an advocate is who is
-- carrying it.
CREATE TABLE application_advocate (
    application_id INTEGER NOT NULL REFERENCES application (id) ON DELETE CASCADE,
    contact_id     INTEGER NOT NULL REFERENCES contact (id) ON DELETE CASCADE,
    PRIMARY KEY (application_id, contact_id)
) STRICT;

-- Every touchpoint with a contact; replaces the sheet's single "Last
-- Contacted" cell. The brief names the date column `date`; it is occurred_on
-- here to match stage_event and to avoid shadowing SQLite's date() function.
CREATE TABLE interaction (
    id             INTEGER PRIMARY KEY,
    contact_id     INTEGER NOT NULL REFERENCES contact (id) ON DELETE CASCADE,
    application_id INTEGER REFERENCES application (id) ON DELETE SET NULL,
    occurred_on    TEXT    NOT NULL CHECK (occurred_on IS date(occurred_on)),
    channel        TEXT    NOT NULL CHECK (channel IN ('email', 'linkedin', 'call', 'in_person', 'text')),
    summary        TEXT
) STRICT;

-- -----------------------------------------------------------------------------
-- Work owed, and postings captured before they disappear
-- -----------------------------------------------------------------------------

-- Something you owe ("Follow up with recruiter"), never something you are
-- waiting on ("Waiting to hear back"). The UI placeholder says so.
CREATE TABLE next_action (
    id             INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES application (id) ON DELETE CASCADE,
    description    TEXT    NOT NULL,
    due_date       TEXT    NOT NULL CHECK (due_date IS date(due_date)),
    completed_at   TEXT    CHECK (completed_at IS NULL OR julianday(completed_at) IS NOT NULL)
) STRICT;

CREATE TABLE posting_snapshot (
    id             INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES application (id) ON DELETE CASCADE,
    captured_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    raw_text       TEXT    NOT NULL
) STRICT;

-- -----------------------------------------------------------------------------
-- Derived status, computed on read.
--   current_stage  highest-ordinal event; ties go to the latest date, then the
--                  latest insert. NULL if the application has no events. Per
--                  the brief, a later lower-ordinal event (a logged
--                  regression) does not change it.
--   last_event_on  date of the most recent event, whatever its stage
--   days_idle      whole days from last_event_on to today, in the local time
--                  of the machine running SQLite. NULL if there are no events.
--   is_live        1 while there is no outcome and the stage is not terminal
-- -----------------------------------------------------------------------------
CREATE VIEW application_status AS
WITH ranked AS (
    SELECT e.application_id,
           e.stage,
           max(e.occurred_on) OVER (PARTITION BY e.application_id) AS last_event_on,
           row_number() OVER (
               PARTITION BY e.application_id
               ORDER BY s.ordinal DESC, e.occurred_on DESC, e.id DESC
           ) AS rn
    FROM stage_event AS e
    JOIN stage AS s ON s.name = e.stage
)
SELECT a.id                                                       AS application_id,
       r.stage                                                    AS current_stage,
       r.last_event_on,
       CAST(julianday(date('now', 'localtime'))
            - julianday(r.last_event_on) AS INTEGER)              AS days_idle,
       (a.outcome IS NULL AND coalesce(s.is_terminal, 0) = 0)     AS is_live
FROM application AS a
LEFT JOIN ranked AS r ON r.application_id = a.id AND r.rn = 1
LEFT JOIN stage  AS s ON s.name = r.stage;

COMMIT;
