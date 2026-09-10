#!/usr/bin/env bash
# Deploy the latest green commit of main to this machine.
#
# This app's production environment is your own machine: one FastAPI process
# serves the API and the built UI at http://127.0.0.1:8000. This script
# updates that install. It only ships a commit that passed CI, and it backs up
# the database first, because later deploys will carry schema migrations.
set -euo pipefail

cd "$(dirname "$0")/.." || exit 1

fail() {
  echo "deploy: $*" >&2
  exit 1
}

[[ "$(git branch --show-current)" == main ]] || fail "check out main first"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail "commit or stash your changes first"

git pull --ff-only --quiet
sha="$(git rev-parse HEAD)"
short="${sha:0:7}"

conclusion="$(gh run list --workflow ci.yml --commit "$sha" --json conclusion --jq '.[0].conclusion // "missing"')"
[[ "$conclusion" == success ]] || fail "CI for $short is '${conclusion:-in progress}', not 'success'"

# Same rule as the backend: a relative LAMP_DB_PATH is taken from the repo root.
db="${LAMP_DB_PATH:-data/lamp.sqlite}"
if [[ -f "$db" ]]; then
  mkdir -p data/backups
  backup="data/backups/lamp-$(date +%Y%m%d-%H%M%S)-$short.sqlite"
  sqlite3 "$db" ".backup '$backup'"
  echo "Backed up the database to $backup"
else
  python3 scripts/init_db.py
fi

(cd backend && uv sync --locked)
(cd frontend && npm ci --no-fund --no-audit && npm run build)

echo
echo "Deployed $short. Start (or restart) the app with:"
echo "  cd backend && uv run uvicorn app.main:app"
echo "and open http://127.0.0.1:8000"
