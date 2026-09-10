# LAMP Target List

A single-user tracker for running a job search from a LAMP list: the ~40
target companies, the applications to them, the people inside who can help,
and the stage-by-stage history of every hiring process. It replaces a Google
Sheets "Target Company List".

> **LAMP** is the target-employer method from Steve Dalton's *The 2-Hour Job
> Search* (**L**ist, **A**lumni, **M**otivation, **P**osting). It has nothing
> to do with the Linux/Apache/MySQL/PHP stack.

**Status:** prototype, runs locally. The app skeleton works end to end: a
React shell calls a FastAPI health check, which reads from SQLite. CI runs on
every pull request. Features start with Phase 1.

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
| Backend | Python, FastAPI, stdlib `sqlite3`, managed with uv | Pydantic models validate the many enum fields at the API boundary for free. SQL-first with no ORM, because the queries that matter (current stage, funnel, alerts) are aggregates that read better as SQL. |
| Database | SQLite, one file | A few hundred rows, one user. There's no server to run, and a backup is one command. |
| Hosting | Local machine only | The API binds to `127.0.0.1`, so there's no auth and no Docker for now. |

The brief suggested reusing LibreShelf's Fastify/Next.js/PostgreSQL stack for
homelab deployment. The prototype gives that up in exchange for
zero-infrastructure local setup. The table design would carry over to
Postgres unchanged. The DDL wouldn't: the type declarations, date checks,
triggers, and the view would all need translating.

## Getting started

Requirements:

- **[uv](https://docs.astral.sh/uv/)**, which installs the backend's pinned
  Python (3.14) by itself.
- **Python 3 built against SQLite 3.37 or newer** for `scripts/init_db.py`;
  the schema's `STRICT` tables need it. Check with
  `python3 -c "import sqlite3; print(sqlite3.sqlite_version)"`.
- **Node.js 24**, pinned in `frontend/.node-version`. With
  [fnm](https://github.com/Schniz/fnm) it's selected automatically when you
  `cd` into `frontend/`.
- **[GitHub CLI](https://cli.github.com/)** (`gh`), only for
  `scripts/deploy.sh`.

```bash
git clone https://github.com/haydn-s/lamp-target-list.git
cd lamp-target-list
python3 scripts/init_db.py
(cd backend && uv sync)
(cd frontend && npm ci)
```

`init_db.py` creates `data/lamp.sqlite` from the template. To keep the
database somewhere else, set `LAMP_DB_PATH` (absolute, or relative to the repo
root). The script, the backend, and the deploy script all read it.

## Development

Run the API and the UI in two terminals:

```bash
cd backend && uv run uvicorn app.main:app --reload
```

```bash
cd frontend && npm run dev
```

Open http://localhost:5173. Vite forwards `/api` requests to FastAPI on
`127.0.0.1:8000`, so there's no CORS to configure. FastAPI's interactive API
docs are at http://127.0.0.1:8000/docs.

The backend refuses to start if the database is missing or was built from a
different schema version, and the error says how to fix it. It never creates a
database on its own, because an empty database appearing where yours should
be would look exactly like data loss.

### Checks

These are the same commands CI runs:

```bash
cd backend && uv run ruff check . ../scripts && uv run ruff format --check . ../scripts && uv run mypy . ../scripts && uv run pytest
```

```bash
cd frontend && npm run lint && npm test && npm run build
```

The backend suite includes `tests/test_schema.py`, which exercises every rule
the database enforces on its own: constraints, triggers, delete behavior, and
the derived-status view.

## CI/CD

### Continuous integration

`.github/workflows/ci.yml` runs on every pull request and every push to
`main`, as two parallel jobs:

| Job | Steps |
|---|---|
| Backend | `uv sync --locked`, Ruff lint and format check, mypy (strict), pytest, ShellCheck on `scripts/*.sh` |
| Frontend | `npm ci`, Oxlint (warnings fail), Vitest, `tsc` type-check and production build |

The workflow's token is read-only, every action is pinned to a full commit
SHA, and a newer push to a pull request cancels its older run. Dependabot
(`.github/dependabot.yml`) opens one grouped update PR a month for each
ecosystem (actions, uv, npm), and CI vets each one like any other change.

### Deployment

This app's production environment is your own machine, so deploying is a
local step rather than a pipeline stage:

```bash
scripts/deploy.sh
```

It refuses to run unless you're on a clean `main`. It then pulls, checks that
CI passed for that exact commit, backs up the database to `data/backups/`,
syncs backend dependencies, and builds the UI. Then start the app:

```bash
cd backend && uv run uvicorn app.main:app
```

and open http://127.0.0.1:8000. In this mode FastAPI serves the built UI and
the API from one process on one port.

Nothing deploys automatically, on purpose. There's no server to push to. A
self-hosted runner on this machine would let workflows from a public repo run
code on it. And a deploy that touches the only copy of your data should be a
step you choose to take. If the app moves to the homelab, CD becomes: build
an image, push it, roll it out.

## Repository layout

```
backend/              FastAPI app (app/) and its tests (tests/); a uv project
frontend/             React + TypeScript app; Vite, Vitest, Oxlint
db/schema.sql         SQLite template: tables, constraints, triggers, view
scripts/init_db.py    builds data/lamp.sqlite from the template; stdlib only
scripts/deploy.sh     deploys the latest green commit of main to this machine
.github/              CI workflow and Dependabot config
ruff.toml             Ruff settings for all Python in the repo
data/                 gitignored: live database, backups, resume files
PROJECT_BRIEF.md      design brief
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
  references go unchecked. The backend turns them on for every connection.
- **You can't update `stage_event` rows.** To fix a mis-keyed event, delete it
  and insert the correct one.
- **Status isn't stored anywhere.** Read it from the view:
  `SELECT * FROM application_status;`

### Backups

A plain `cp` while the app is running can copy the file in the middle of a
write. Use SQLite's online backup instead (`scripts/deploy.sh` does this
before every deploy):

```bash
mkdir -p data/backups
sqlite3 data/lamp.sqlite ".backup data/backups/lamp-$(date +%F).sqlite"
```

### Changing the schema

Edit `db/schema.sql`, bump `PRAGMA user_version`, and bump `SCHEMA_VERSION` in
`backend/app/db.py` to match. The backend refuses to start when the two
disagree. While the database holds no real data, delete it and recreate it.
Once it does, changes ship as numbered migration scripts applied in order
against `user_version`. That runner gets built along with the first change
that needs it.

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

**Status is derived, never stored.** The `application_status` view computes
two stages for each application:

- **Current stage:** where it is now, meaning its latest event by date. A
  logged regression or a revived application shows up here. Same-day events
  resolve to the later stage, so backfilling history never moves it backward.
- **Furthest stage:** the highest live stage it ever reached. This is what
  the funnel counts, so an application rejected after a screen still counts
  as having reached `screen`.

Idle time counts from the latest event. A stored status column drifts out of
sync with the dates within weeks, and that drift is the main reason to leave
the spreadsheet.

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

- **Phase 0, Foundation:** schema template, bootstrap script, app skeleton,
  and CI/CD (done). The CSV importer for the existing sheet is deferred until
  later.
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
