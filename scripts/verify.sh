#!/usr/bin/env bash
# Offline verification: backend tests (recorded replay fixtures) + frontend type-check and build.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-$ROOT/backend/.venv/bin/python}"
echo "== backend tests"
(cd "$ROOT/backend" && "$PY" -m pytest -q tests -p no:cacheprovider)
echo "== frontend type-check + build"
(cd "$ROOT/frontend" && npm run build)
if [[ "${PATHWAYGPS_LIVE:-0}" == "1" ]]; then
  echo "== live integration tests"
  (cd "$ROOT/backend" && PATHWAYGPS_LIVE=1 "$PY" -m pytest -q tests/test_live.py -p no:cacheprovider)
fi
echo "All checks passed."
