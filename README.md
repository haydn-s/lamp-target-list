# LAMP Target List

A single-user tracker for running a job search from a LAMP list: the ~40
target companies, the applications to them, the people inside who can help,
and the stage-by-stage history of every hiring process. It replaces a Google
Sheets "Target Company List".

> **LAMP** is the target-employer method from Steve Dalton's *The 2-Hour Job
> Search* (**L**ist, **A**lumni, **M**otivation, **P**osting). It has nothing
> to do with the Linux/Apache/MySQL/PHP stack.

**Status:** prototype, runs locally, Phase 0. The database template and its
bootstrap script exist. The API and UI don't yet.

## Why it exists

A job search usually fails in one of two ways, and each needs the opposite fix:

1. **Targeting failure:** applications go out and nothing comes back. The fix
   is the resume, the target list, and referrals.
2. **Conversion failure:** interviews happen but don't turn into offers. The
   fix is interview prep and storytelling.

You can only tell which one you're in from stage-by-stage conversion data, and
a spreadsheet with one status column can't produce that. The tracker's second
job is nagging: flagging live opportunities before they quietly go cold.

The full design (domain model, rules, alerting, phasing) is in
[PROJECT_BRIEF.md](PROJECT_BRIEF.md).

## Stack

| Layer | Choice | Reasoning |
|---|---|---|
| Frontend | React + TypeScript, Vite | Client-rendered SPA over a local JSON API. Nothing needs server rendering, so Vite rather than Next.js. **Desktop only**: laid out for ~1280px and wider, with no mobile breakpoints. |
| Backend | Python, FastAPI, stdlib `sqlite3` | Pydantic models validate the many enum fields at the API boundary for free. SQL-first with no ORM, because the queries that matter (current stage, funnel, alerts) are aggregates that read better as SQL. |
| Database | SQLite, one file | A few hundred rows, one user. There's no server to run, and a backup is one command. |
| Hosting | Local machine only | The API binds to `127.0.0.1`, so there's no auth and no Docker for now. |

The brief suggested reusing LibreShelf's Fastify/Next.js/PostgreSQL stack for
homelab deployment. The prototype gives that up in exchange for
zero-infrastructure local setup. The table design would carry over to
Postgres unchanged. The DDL wouldn't: the type declarations, date checks,
triggers, and the view would all need translating.

## Getting started

Requirements:

- **Python 3.12+** built against **SQLite 3.37 or newer**, which the schema's
  `STRICT` tables need. Check with
  `python3 -c "import sqlite3; print(sqlite3.sqlite_version)"`.
- **Node.js 22+**, once the frontend exists.

```bash
git clone <repo-url> lamp-target-list
cd lamp-target-list
python3 scripts/init_db.py
```

This creates `data/lamp.sqlite` from the template. To put it somewhere else,
pass a path or set `LAMP_DB_PATH`.

Instructions for running the API and UI will land here with Phase 1. The plan:
FastAPI on `127.0.0.1:8000` and the Vite dev server on `localhost:5173`, with
Vite proxying `/api` to FastAPI so there's no CORS to configure.

## Repository layout

```
db/schema.sql        SQLite template: tables, constraints, triggers, view (committed)
scripts/init_db.py   builds data/lamp.sqlite from the template; stdlib only
data/                gitignored: live database, resume files, backups, sheet exports
backend/             FastAPI app (Phase 1, not created yet)
frontend/            React app (Phase 1, not created yet)
PROJECT_BRIEF.md     design brief
```

## The database

### Template vs. live database

| File | Committed? | Contents |
|---|---|---|
| `db/schema.sql` | Yes | The template: every table, constraint, trigger, and view, plus the stage vocabulary. |
| `data/lamp.sqlite` | **Never** | Your data. It holds real people's names, emails, and notes. |

The template is plain SQL on purpose, not a pre-built `.sqlite` file. Schema
changes show up as reviewable diffs rather than binary blobs, and `.gitignore`
can exclude every `*.sqlite`/`*.db` file and its `-journal`/`-wal`/`-shm`
sidecars without any exceptions.

`init_db.py` won't overwrite an existing database. To start over:

```bash
rm data/lamp.sqlite && python3 scripts/init_db.py
```

### Working with it directly

Any SQLite client works, including the `sqlite3` CLI, DB Browser for SQLite,
and TablePlus, as long as its bundled SQLite is 3.37 or newer. Older clients
can't read `STRICT` tables. Keep these in mind:

- **Foreign keys are off unless you turn them on**, per connection:
  `PRAGMA foreign_keys = ON;`. With them off, deletes don't cascade and bad
  references go unchecked. The backend will turn them on for every connection.
- **You can't update `stage_event` rows.** To fix a mis-keyed event, delete it
  and insert the correct one.
- **Status isn't stored anywhere.** Read it from the view:
  `SELECT * FROM application_status;`

### Backups

A plain `cp` while the app is running can copy the file in the middle of a
write. Use SQLite's online backup instead:

```bash
mkdir -p data/backups
sqlite3 data/lamp.sqlite ".backup data/backups/lamp-$(date +%F).sqlite"
```

### Changing the schema

Edit `db/schema.sql` and bump `PRAGMA user_version`. While the database holds
no real data, delete it and recreate it. Once it does, changes ship as
numbered migration scripts applied in order against `user_version`. That
runner gets built along with the first change that needs it.

## Domain model

| Table | Holds |
|---|---|
| `company` | Target employers, with industry, priority tier (A/B/C), and motivation |
| `application` | One per role applied to. A company can have several. |
| `stage_event` | Append-only stage history, one row per milestone |
| `stage` | The stage vocabulary and its order |
| `contact` | People, optionally tied to a company |
| `application_advocate` | Contacts actively pushing a specific application |
| `interaction` | Every touchpoint with a contact |
| `next_action` | Something you owe, with a due date |
| `resume_version` | Resume files, so callbacks can be attributed to a version |
| `posting_snapshot` | Posting text captured before the posting disappears |

Stages run `researching → applied → assessment → screen → interviewing →
final_round → offer`. Any live stage can end in `rejected`, `ghosted`, or
`withdrawn`. Stages can be skipped going forward, and `interviewing` repeats,
so three rounds are three events.

**Status is derived, never stored.** The current stage is the highest-ordinal
event, and idle time counts from the latest event. A stored status column
drifts out of sync with the dates within weeks, and that drift is the main
reason to leave the spreadsheet.

### How LAMP maps onto the tables

| LAMP | Where it lives |
|---|---|
| **L**ist | `company` rows. The target is 40. |
| **A**lumni | `contact` rows at the company, counted rather than stored as a Y/N |
| **M**otivation | `company.priority_tier` for ranking, `company.motivation` for the two-sentence *why* |
| **P**osting | `application.posting_url` and `posting_date` |

### Where rules are enforced

| Rule | Enforced by | Why there |
|---|---|---|
| Valid enums, dates, and references | Database (CHECK, FK) | These must hold no matter what writes the file: the API, the importer, or a GUI client. |
| Entering a terminal stage requires an `outcome` | Database trigger | Imported history must satisfy it too. |
| Stage events are never edited | Database trigger | The log is the history, so editing a row rewrites it. |
| Moving backward requires a note | API | The logic has to consider dates, since backfilling an earlier stage isn't a regression, and the error needs to be readable. |
| `motivation` required before leaving `researching` | API | Imported sheet rows will break this rule, and enforcing it in the database would block the import. |
| A next action is something you owe | UI placeholder text | A machine can't check it. |

## Roadmap

- **Phase 0, Foundation:** schema template and bootstrap script (done). Still
  to come: a CSV importer that turns the sheet's milestone date columns into
  `stage_event` rows.
- **Phase 1, Replace the spreadsheet:** CRUD for companies, applications, and
  contacts. The board view, application detail with a stage timeline, and
  keyboard quick-add.
- **Phase 2, Earn its keep:** a dashboard with the funnel, conversion rates,
  and advocate lift. The seven alert rules, and next actions.
- **Phase 3, Compound value:** search over posting snapshots, callback
  attribution by resume version, and a periodic digest. SQLite's built-in FTS5
  may make MeiliSearch unnecessary for the search.
- **Phase 4, Speculative:** one-click posting capture and keyword differential.

## Open questions

- **Sheet cutover:** retire the Google Sheet when Phase 1 lands, or keep a
  one-way export as a readable backup? Bidirectional sync is ruled out either
  way.

## License

Apache License 2.0. See [LICENSE](LICENSE).
