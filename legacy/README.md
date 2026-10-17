# Legacy (Copilot-generated) code — superseded

These files are the original Copilot implementation, preserved for reference. They are **not** imported by the
current application. See `docs/PROJECT_AUDIT.md` for why each part was replaced.

| Path | Replaced by |
|---|---|
| `backend_app/graph.py`, `graph_backend.py`, `models.py` | `backend/app/pipeline/*`, `backend/app/domain/model.py` |
| `backend_app/services/*` | `backend/app/adapters/*` (async, cached, rate-limited, per-source status) |
| `backend_app/neo4j_client.py`, `docker-compose.yml` | not needed — per-analysis graphs are held in memory |
| `etl/`, `graph/`, `data/` (static `quick_graph.json`) | live source adapters; deterministic replay fixtures in `backend/tests/fixtures/replay` |
| `backend_tests/test_api.py` | `backend/tests/test_*.py` |
| `verification/` | historical verification logs from the Copilot session |
