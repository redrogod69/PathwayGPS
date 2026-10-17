"""Live integration tests against the public APIs (opt-in: PATHWAYGPS_LIVE=1).

They check structure and identifiers only, because source contents legitimately change.
Run:  PATHWAYGPS_LIVE=1 python -m pytest -q tests/test_live.py
"""

import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("PATHWAYGPS_LIVE") != "1", reason="set PATHWAYGPS_LIVE=1 to hit the live APIs")


@pytest.fixture(scope="module")
def live_service(tmp_path_factory):
    from app.core.config import Settings
    from app.core.http import HttpClient
    from app.pipeline.service import AnalysisService

    cfg = Settings(cache_dir=tmp_path_factory.mktemp("live-cache"), offline=False)
    return AnalysisService(HttpClient(cfg))


@pytest.mark.parametrize("query,gene,acc", [("EGFR L858R", "EGFR", "P00533"), ("BRAF V600E", "BRAF", "P15056")])
def test_live_resolution_and_graph(live_service, query, gene, acc):
    p = asyncio.run(live_service.analyze(query))
    assert p["resolution"]["status"] == "resolved"
    assert p["resolution"]["gene"]["symbol"] == gene and p["resolution"]["protein"]["accession"] == acc
    assert p["graph"]["edges"] and all(e["evidence"] for e in p["graph"]["edges"])
    statuses = {s["source"]: s["status"] for s in p["sources"]}
    assert statuses.get("clinvar") in ("ok", "partial") and statuses.get("reactome") in ("ok", "partial")
