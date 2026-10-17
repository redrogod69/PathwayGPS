"""Export recorded analyses for the GitHub Pages static demo (frontend/public/demo/).

Runs the real pipeline in offline replay mode over backend/tests/fixtures/replay, so the demo shows
genuine source data captured on the fixture recording date (no live queries from the static site).
Usage:  backend/.venv/bin/python scripts/export_static_demo.py
"""
import asyncio, json, os, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["PATHWAYGPS_OFFLINE"] = "1"
os.environ["PATHWAYGPS_CACHE_DIR"] = str(ROOT / "backend" / "tests" / "fixtures" / "replay")
os.environ["PATHWAYGPS_SNAPSHOT_DIR"] = "/tmp/pathwaygps-static-snapshots"
sys.path.insert(0, str(ROOT / "backend"))
from app.main import EXAMPLES  # noqa: E402
from app.pipeline.service import AnalysisService  # noqa: E402

QUERIES = [e["query"] for e in EXAMPLES] + ["HER2", "L858R", "EGFR L859R", "ZZZFAKEGENE L858R"]
OUT = ROOT / "frontend" / "public" / "demo"


def key(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().upper())


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    svc = AnalysisService()
    index = {"generated_from": "recorded replay fixtures", "queries": {}, "examples": EXAMPLES}
    for q in QUERIES:
        p = await svc.analyze(q)
        p["mode"] = "static_demo"
        name = re.sub(r"[^A-Za-z0-9]+", "_", q).strip("_") + ".json"
        (OUT / name).write_text(json.dumps(p, separators=(",", ":")), encoding="utf-8")
        index["queries"][key(q)] = name
        for alias in filter(None, [p["resolution"].get("clinvar_variation_id") and f"VCV{int(p['resolution']['clinvar_variation_id']):09d}",
                                   (p.get("overview") or {}).get("clinvar") and (p["overview"]["clinvar"] or {}).get("rsid")]):
            index["queries"].setdefault(key(alias), name)
        print(f"{q:24s} {p['resolution']['status']:12s} {name}")
    (OUT / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")


asyncio.run(main())
