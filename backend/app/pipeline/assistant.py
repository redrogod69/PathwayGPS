"""PathwayGPS Research Assistant: conversational Q&A grounded in one analysis's evidence ledger.

Two modes, both citation-bound:
* ``claude``    — when the anthropic SDK and ANTHROPIC_API_KEY are available. The model sees only the
                  ledger; cited IDs are validated server side and unknown IDs are dropped.
* ``retrieval`` — always available. Intent routing + lexical retrieval over the ledger; every sentence is
                  assembled from retrieved records, so nothing is generated beyond the sources.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Dict, List

from app.core.config import settings
from app.pipeline.synthesis_ai import _ledger, ai_available

STOP = set("a an the of to in on for and or is are was be by with what which how why does do this that these those it its from as at into about can i me my vs".split())

CHAT_SYSTEM = """You are the PathwayGPS Research Assistant, answering questions about one analysed genetic variant.
You are given an evidence ledger retrieved from ClinVar, Ensembl VEP, UniProt, Reactome, IntAct, Open Targets, CIViC and PubMed, plus detected conflicts and gaps.

Rules:
- Answer only from the ledger. Cite the evidence IDs ("ev-…") that support each substantive statement in the "citations" list and inline as [ev-…].
- If the ledger cannot answer, say so plainly and suggest what data would be needed. Never invent PMIDs, interactions, numbers or classifications.
- Distinguish curated, experimental, computational, association and inferred evidence. Keep germline and somatic contexts separate. A VUS stays uncertain.
- Label speculation explicitly as a hypothesis requiring validation. Do not give treatment recommendations for individuals.
- Be concise (≤ 220 words) and scientific."""

CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
        "follow_up": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "citations", "follow_up"],
    "additionalProperties": False,
}


def suggestions(payload: Dict[str, Any]) -> List[str]:
    name = next((n["label"] for n in payload["graph"]["nodes"] if n["id"] == payload.get("root_id")), payload.get("query"))
    out = [f"Explain the molecular mechanism connecting {name} to downstream signalling.",
           "Which links in this cascade have direct experimental or curated evidence vs computational inference?",
           "Where do the sources disagree, and why might that be?",
           "What therapies have curated evidence, and in which disease contexts?",
           "What evidence is missing or uncertain for this variant?"]
    return out if payload["graph"]["nodes"] else []


def _tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9\-]+", text.lower()) if t not in STOP and len(t) > 1]


def _retrieval_answer(payload: Dict[str, Any], question: str) -> Dict[str, Any]:
    g = payload["graph"]
    nodes = {n["id"]: n for n in g["nodes"]}
    q = question.lower()
    rows = []
    for e in g["edges"]:
        rel = f"{nodes[e['source']]['label']} {e['label']} {nodes[e['target']]['label']}"
        for eid in e["evidence"]:
            ev = g["evidence"].get(eid)
            if ev:
                rows.append((e, ev, rel))

    def pick(pred, limit=6):
        seen, out = set(), []
        for e, ev, rel in rows:
            if pred(e, ev) and ev["id"] not in seen:
                seen.add(ev["id"])
                out.append((e, ev, rel))
        return out[:limit]

    lines: List[str] = []
    cites: List[str] = []

    def add(e, ev, rel):
        lines.append(f"• {ev['statement']} ({ev['category']}, {ev['source']}) [{ev['id']}]")
        cites.append(ev["id"])

    if re.search(r"conflict|disagree|discord|contradict|inconsist", q):
        if payload.get("conflicts"):
            for c in payload["conflicts"]:
                lines.append(f"• {c['title']}: {c['summary']} — {c['explanation']}")
        else:
            lines.append("• No disagreements were detected among the retrieved records.")
    elif re.search(r"drug|therap|treat|inhibit|sensitiv|resist", q):
        for t in pick(lambda e, ev: e["type"] in ("VARIANT_PREDICTIVE_FOR_THERAPY", "DRUG_TARGETS_PROTEIN"), 8):
            add(*t)
        lines.append("Note: these are disease-specific curated evidence items or gene-level mechanisms — not treatment recommendations.")
    elif re.search(r"missing|gap|uncertain|unknown|limitation|vus", q):
        for gp in payload.get("gaps", []):
            lines.append(f"• {gp['message']}")
    elif re.search(r"experimental|curated|computational|inferr|predict|evidence strength|direct", q):
        cats = Counter(e["category"] for e in g["edges"])
        lines.append("Relationship counts by strongest evidence category: " + ", ".join(f"{k} {v}" for k, v in cats.most_common()) + ".")
        for t in pick(lambda e, ev: ev["category"] in ("computational", "inferred"), 4):
            add(*t)
        for t in pick(lambda e, ev: ev["category"] in ("experimental",) or (ev["category"] == "curated" and ev["publications"]), 4):
            add(*t)
    elif re.search(r"mechanism|pathway|downstream|cascade|signal|route|proliferat", q):
        imp = payload.get("impact") or {}
        fp = imp.get("focus_pathway")
        if fp:
            lines.append(f"Downstream cascade is drawn for '{fp['name']}' ({fp.get('reason')}).")
        order = ["VARIANT_ALTERS_PROTEIN", "VARIANT_IN_PROTEIN_REGION", "VARIANT_REPRESENTED_AS", "MUTANT_ENTITY_IN_PATHWAY",
                 "PROTEIN_PARTICIPATES_IN_REACTION", "REACTION_PRECEDES", "REACTION_PRODUCES"]
        for t in order:
            for item in pick(lambda e, ev, t=t: e["type"] == t, 2):
                add(*item)
        lines.append("Reactome event order describes curated pathway sequence, not a measured effect of the variant.")
    else:
        qt = set(_tokens(question))
        scored = []
        for e, ev, rel in rows:
            hay = Counter(_tokens(ev["statement"] + " " + rel))
            score = sum(hay[t] for t in qt)
            if score:
                scored.append((score, e, ev, rel))
        scored.sort(key=lambda x: -x[0])
        seen = set()
        for _, e, ev, rel in scored:
            if ev["id"] not in seen:
                seen.add(ev["id"])
                add(e, ev, rel)
            if len(seen) >= 6:
                break
    if not lines:
        lines.append("The retrieved evidence ledger does not contain records that answer this question. "
                     "Try the Evidence Library or a PubMed search, or rephrase around genes, pathways, drugs, conflicts or evidence types.")
    return {"mode": "retrieval", "answer": "\n".join(lines), "citations": cites, "follow_up": suggestions(payload)[:2]}


async def chat(payload: Dict[str, Any], messages: List[Dict[str, str]]) -> Dict[str, Any]:
    question = (messages[-1].get("content") if messages else "") or ""
    if not ai_available()["enabled"]:
        return _retrieval_answer(payload, question)
    import anthropic

    ledger = _ledger(payload, limit=160)
    valid = {r["id"] for r in ledger}
    context = {"query": payload["query"], "resolution": payload["resolution"].get("message"),
               "conflicts": [{"title": c["title"], "summary": c["summary"]} for c in payload.get("conflicts", [])],
               "gaps": [g["message"] for g in payload.get("gaps", [])], "evidence_ledger": ledger}
    convo = [{"role": "user", "content": "Evidence ledger (JSON):\n" + json.dumps(context, ensure_ascii=False)},
             {"role": "assistant", "content": "I have the ledger and will answer only from it, citing evidence IDs."}]
    for m in messages[-10:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            convo.append({"role": m["role"], "content": m["content"][:4000]})
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=120.0, max_retries=2)
    try:
        resp = await client.messages.create(
            model=settings.ai_model, max_tokens=16000, system=CHAT_SYSTEM, messages=convo,
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={"output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": CHAT_SCHEMA}}, "fallbacks": "default"},
        )
    except Exception as exc:  # fall back to retrieval rather than failing the conversation
        out = _retrieval_answer(payload, question)
        out["notice"] = f"Claude unavailable ({exc.__class__.__name__}); answered from the ledger by retrieval."
        return out
    if resp.stop_reason == "refusal":
        out = _retrieval_answer(payload, question)
        out["notice"] = "The model declined; answered by retrieval instead."
        return out
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "{}")
    try:
        data = json.loads(text)
    except ValueError:
        return _retrieval_answer(payload, question)
    cites = [c for c in data.get("citations", []) if c in valid]
    answer = re.sub(r"\[(ev-[^\]]+)\]", lambda m: m.group(0) if m.group(1) in valid else "", data.get("answer", ""))
    return {"mode": "claude", "model": getattr(resp, "model", settings.ai_model), "answer": answer, "citations": cites,
            "dropped_citations": len(data.get("citations", [])) - len(cites), "follow_up": data.get("follow_up", [])[:3]}
