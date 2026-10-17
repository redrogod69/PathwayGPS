"""PathwayGPS API."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.http import SOURCES, SourceError
from app.pipeline.report import build_blocks, to_html, to_markdown
from app.pipeline.service import service
from app.pipeline.synthesis_ai import ai_available

VERSION = "2.0.0"

EXAMPLES = [
    {"query": "EGFR L858R", "label": "EGFR L858R", "note": "NSCLC sensitizing"},
    {"query": "BRAF V600E", "label": "BRAF V600E", "note": "Conflicting germline · Tier I"},
    {"query": "KRAS G12C", "label": "KRAS G12C", "note": "2 nucleotide records"},
    {"query": "NM_000546.6:c.524G>A", "label": "TP53 R175H", "note": "Transcript HGVS"},
    {"query": "rs121434568", "label": "rs121434568", "note": "Multi-allelic rsID"},
    {"query": "TP53", "label": "TP53", "note": "Gene-level only"},
]


class AnalyzeRequest(BaseModel):
    query: Optional[str] = Field(None, max_length=200)
    variant: Optional[str] = Field(None, max_length=200, description="Deprecated alias of 'query'")


class ExpandRequest(BaseModel):
    node_id: str = Field(..., max_length=300)
    action: str = Field(..., max_length=40)


class CompareRequest(BaseModel):
    a: str = Field(..., max_length=200)
    b: str = Field(..., max_length=200)


class ReportRequest(BaseModel):
    format: str = "md"
    workbench: Optional[Dict[str, Any]] = None


class SnapshotRequest(BaseModel):
    workbench: Optional[Dict[str, Any]] = None


class ChatMessage(BaseModel):
    role: str = Field(..., max_length=20)
    content: str = Field(..., max_length=4000)


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., min_length=1, max_length=30)


class EnrichmentRequest(BaseModel):
    identifiers: List[str] = Field(..., max_length=600)


app = FastAPI(title="PathwayGPS", version=VERSION, description="From mutation to mechanism — evidence-backed variant navigation.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173", "http://127.0.0.1:4173"],
                   allow_methods=["*"], allow_headers=["*"])


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found (analyses are kept in memory; re-run the query after a server restart).")


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "PathwayGPS", "version": VERSION, "mode": "offline_replay" if settings.offline else "live",
            "disk_cache": settings.disk_cache, "ai": ai_available(), "ncbi_api_key": bool(settings.ncbi_api_key)}


@app.get("/api/examples")
def examples() -> Dict[str, Any]:
    return {"examples": EXAMPLES}


@app.get("/api/sources")
def sources() -> Dict[str, Any]:
    return {"sources": [{"key": s.key, "name": s.name, "homepage": s.homepage, "license": s.license} for s in SOURCES.values()],
            "not_integrated": [{"name": "KEGG", "reason": "API and data require a licence for commercial use or redistribution; only outbound links are provided."}]}


@app.post("/api/analyze")
async def analyze(payload: AnalyzeRequest) -> Dict[str, Any]:
    query = (payload.query or payload.variant or "").strip()
    return await service.analyze(query)


@app.get("/api/analysis/{analysis_id}")
def get_analysis(analysis_id: str) -> Dict[str, Any]:
    data = service.get(analysis_id)
    if data is None:
        raise _not_found("Analysis")
    return data


@app.post("/api/analysis/{analysis_id}/expand")
async def expand(analysis_id: str, payload: ExpandRequest) -> Dict[str, Any]:
    try:
        return await service.expand(analysis_id, payload.node_id, payload.action)
    except KeyError:
        raise _not_found("Analysis or node")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/analysis/{analysis_id}/path")
def path(analysis_id: str, target: str = Query(..., max_length=300), source: Optional[str] = Query(None, max_length=300)) -> Dict[str, Any]:
    try:
        return service.path(analysis_id, target, source)
    except KeyError:
        raise _not_found("Analysis")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/analysis/{analysis_id}/routes")
def routes(analysis_id: str, target: str = Query(..., max_length=300), k: int = Query(3, ge=1, le=5)) -> Dict[str, Any]:
    try:
        return service.routes(analysis_id, target, k)
    except KeyError:
        raise _not_found("Analysis")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/analysis/{analysis_id}/chat")
async def chat(analysis_id: str, payload: ChatRequest) -> Dict[str, Any]:
    try:
        return await service.chat(analysis_id, [m.model_dump() for m in payload.messages])
    except KeyError:
        raise _not_found("Analysis")


@app.post("/api/analysis/{analysis_id}/synthesis")
async def synthesis(analysis_id: str) -> Dict[str, Any]:
    try:
        return await service.synthesize_ai(analysis_id)
    except KeyError:
        raise _not_found("Analysis")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text or "analysis").strip("_")[:60] or "analysis"


@app.post("/api/analysis/{analysis_id}/report")
def report(analysis_id: str, payload: ReportRequest) -> Response:
    data = service.get(analysis_id)
    if data is None:
        raise _not_found("Analysis")
    blocks = build_blocks(data, payload.workbench)
    name = f"PathwayGPS_{_safe_name(data.get('query'))}"
    if payload.format == "html":
        return Response(to_html(blocks, name), media_type="text/html; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}.html"'})
    if payload.format == "json":
        out = dict(data)
        if payload.workbench:
            out["workbench"] = payload.workbench
        return Response(json.dumps(out, indent=2, default=str), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    return Response(to_markdown(blocks), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.md"'})


@app.get("/api/analysis/{analysis_id}/export/graph")
def export_graph(analysis_id: str, format: str = "json") -> Response:
    data = service.get(analysis_id)
    if data is None:
        raise _not_found("Analysis")
    g = data["graph"]
    name = f"PathwayGPS_{_safe_name(data.get('query'))}_graph"
    if format == "cytoscape":
        elements = {"nodes": [{"data": {**{k: v for k, v in n.items() if k != "attributes"}, "id": n["id"], "label": n["label"]}} for n in g["nodes"]],
                    "edges": [{"data": {"id": e["id"], "source": e["source"], "target": e["target"], "type": e["type"], "label": e["label"],
                                        "category": e["category"], "evidence": e["evidence"]}} for e in g["edges"]]}
        body = {"format_version": "1.0", "generated_by": "PathwayGPS", "data": {"query": data.get("query"), "retrieved": data.get("created_at")},
                "elements": elements, "evidence": g["evidence"]}
    else:
        body = {"query": data.get("query"), "retrieved": data.get("created_at"), "root_id": data.get("root_id"), **g,
                "sources": data.get("sources")}
    return Response(json.dumps(body, indent=2, default=str), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}.json"'})


@app.post("/api/analysis/{analysis_id}/snapshot")
def snapshot(analysis_id: str, payload: SnapshotRequest) -> Dict[str, Any]:
    try:
        return service.save_snapshot(analysis_id, payload.workbench)
    except KeyError:
        raise _not_found("Analysis")


@app.get("/api/snapshots")
def snapshots() -> Dict[str, Any]:
    return {"snapshots": service.list_snapshots()}


@app.get("/api/snapshots/{snap_id}")
def load_snapshot(snap_id: str) -> Dict[str, Any]:
    try:
        return service.load_snapshot(snap_id)
    except KeyError:
        raise _not_found("Snapshot")


@app.post("/api/snapshots/import")
def import_snapshot(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        return service.register_snapshot(payload)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not import file: {exc}")


@app.post("/api/compare")
async def compare(payload: CompareRequest) -> Dict[str, Any]:
    return await service.compare(payload.a, payload.b)


@app.get("/api/publications/{pmid}/abstract")
async def abstract(pmid: str) -> Dict[str, Any]:
    if not pmid.isdigit() or len(pmid) > 9:
        raise HTTPException(status_code=400, detail="PMID must be numeric.")
    try:
        return await service.abstract(pmid)
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=f"PubMed unavailable: {exc.message}")


@app.get("/api/literature/search")
async def literature(q: str = Query(..., min_length=2, max_length=300), limit: int = Query(15, ge=1, le=50)) -> Dict[str, Any]:
    try:
        return await service.literature_search(q, limit)
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=f"PubMed unavailable: {exc.message}")


@app.post("/api/enrichment")
async def enrichment(payload: EnrichmentRequest) -> Dict[str, Any]:
    try:
        return await service.enrichment(payload.identifiers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=f"Reactome Analysis Service unavailable: {exc.message}")


# Serve the built frontend (npm run build) from the same process when present.
_dist = settings.repo_root / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        return FileResponse(str(_dist / "index.html"))
