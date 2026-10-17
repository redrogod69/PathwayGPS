"""Optional grounded synthesis with Claude.

Enabled only when the ``anthropic`` package is installed and ANTHROPIC_API_KEY is set
(server side; the key never reaches the browser). The model receives *only* the retrieved
evidence ledger and must return claims that cite evidence-record IDs. The server then:
* drops any claim that cites no ID or an ID not present in the ledger,
* forces every claim not marked as an observation to be labelled a hypothesis,
* never lets the model add nodes, edges or scores to the graph.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.core.config import settings

SYSTEM_PROMPT = """You are assisting a researcher who is exploring a genetic variant in PathwayGPS.
You receive a JSON evidence ledger retrieved from public databases (ClinVar, Ensembl VEP, UniProt, Reactome, IntAct, Open Targets, CIViC).
Write a short, careful synthesis for a scientific audience.

Rules:
- Every claim must cite one or more evidence IDs exactly as they appear in the ledger ("ev-…"). Never cite anything else, never invent PMIDs, papers, numbers or interactions.
- Use kind "observation" only for statements directly asserted by the cited records. Anything that goes beyond them (mechanistic speculation, possible downstream effects) must use kind "hypothesis" and must say what would be needed to test it.
- Keep germline and somatic contexts separate. A variant of uncertain significance stays uncertain. Association is not mechanism. Do not recommend treatments.
- Point out conflicting records and missing evidence when present.
- Suggest at most 4 follow-up PubMed search queries (plain query strings)."""

SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "kind": {"type": "string", "enum": ["observation", "hypothesis", "gap", "conflict"]},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "kind", "evidence"],
                "additionalProperties": False,
            },
        },
        "follow_up_searches": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["claims", "follow_up_searches"],
    "additionalProperties": False,
}


def ai_available() -> Dict[str, Any]:
    try:
        import anthropic  # noqa: F401
        sdk = True
    except Exception:
        sdk = False
    return {"enabled": bool(sdk and settings.anthropic_api_key), "sdk_installed": sdk,
            "key_configured": bool(settings.anthropic_api_key), "model": settings.ai_model}


def _ledger(payload: Dict[str, Any], limit: int = 140) -> List[Dict[str, Any]]:
    nodes = {n["id"]: n for n in payload["graph"]["nodes"]}
    rows = []
    for e in payload["graph"]["edges"]:
        for ev_id in e["evidence"]:
            ev = payload["graph"]["evidence"].get(ev_id)
            if not ev:
                continue
            rows.append({
                "id": ev_id, "relationship": f"{nodes.get(e['source'], {}).get('label')} —{e['label']}→ {nodes.get(e['target'], {}).get('label')}",
                "source": ev["source"], "category": ev["category"], "statement": ev["statement"],
                "classification": ev.get("classification"), "review_status": ev.get("review_status"), "origin": ev.get("origin"),
                "pmids": ev.get("publications", [])[:5], "limitations": ev.get("limitations"),
            })
    order = {"curated": 0, "experimental": 1, "computational": 2, "association": 3, "inferred": 4, "hypothesis": 5}
    rows.sort(key=lambda r: order.get(r["category"], 9))
    return rows[:limit]


async def ai_synthesis(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    status = ai_available()
    if not status["enabled"]:
        return None
    import anthropic

    ledger = _ledger(payload)
    valid_ids = {r["id"] for r in ledger}
    context = {
        "query": payload["query"],
        "resolution": {k: payload["resolution"].get(k) for k in ("status", "message", "warnings")},
        "conflicts": [{"title": c["title"], "summary": c["summary"]} for c in payload.get("conflicts", [])],
        "gaps": [g["message"] for g in payload.get("gaps", [])],
        "evidence_ledger": ledger,
    }
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=120.0, max_retries=2)
    # output_config / fallbacks are sent via extra_body so that older SDK releases (the newest
    # anthropic 1.x needs Python ≥3.10; this project's venv is 3.9) still pass them through.
    response = await client.messages.create(
        model=settings.ai_model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "Evidence ledger and context (JSON):\n" + json.dumps(context, ensure_ascii=False)}],
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        extra_body={
            "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            "fallbacks": "default",
        },
    )
    if response.stop_reason == "refusal":
        return {"mode": "ai", "model": settings.ai_model, "claims": [], "follow_up_searches": [], "rejected_claims": 0,
                "disclaimer": "The model declined this request; the deterministic summary remains available."}
    text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "{}")
    try:
        data = json.loads(text)
    except ValueError:
        return {"mode": "ai", "model": settings.ai_model, "claims": [], "follow_up_searches": [], "rejected_claims": 0,
                "disclaimer": "The model returned malformed output; nothing was shown."}
    kept, rejected = [], 0
    for claim in data.get("claims", []):
        cites = [c for c in claim.get("evidence", []) if c in valid_ids]
        if not cites or len(cites) != len(claim.get("evidence", [])):
            rejected += 1
            continue
        kind = claim.get("kind") if claim.get("kind") in ("observation", "hypothesis", "gap", "conflict") else "hypothesis"
        kept.append({"text": claim["text"], "kind": kind, "evidence": cites})
    return {
        "mode": "ai",
        "model": getattr(response, "model", settings.ai_model),
        "claims": kept,
        "follow_up_searches": [s for s in data.get("follow_up_searches", []) if isinstance(s, str)][:4],
        "rejected_claims": rejected,
        "disclaimer": "AI-generated from the evidence ledger only. Claims citing unknown evidence IDs were discarded "
                      f"({rejected}). Hypotheses require experimental validation. Not clinical advice.",
    }
