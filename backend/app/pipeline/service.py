"""Analysis orchestration, in-memory store, expansions, comparison and snapshots."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.adapters.pubmed import PubMedAdapter, methods_from_pubtypes
from app.adapters.reactome import ReactomeAdapter
from app.core.config import settings
from app.core.http import HttpClient, SourceError, Tracker, http_client
from app.domain.model import Graph
from app.pipeline.builder import AnalysisBuilder, MAX_PATHWAYS
from app.pipeline.insights import VERDICT_TEXT, k_routes, deterministic_synthesis, explain_path, find_conflicts, find_gaps, impact_summary
from app.pipeline.resolver import VariantResolver
from app.pipeline.synthesis_ai import ai_available, ai_synthesis

MAX_PUBLICATIONS = 220
SNAPSHOT_ID_RE = re.compile(r"^[a-f0-9]{12}$")

STANDING_LIMITATIONS = [
    "PathwayGPS is a research and exploration tool, not a clinically validated diagnostic, prognostic or prescribing system.",
    "Pathway, reaction and interaction context describes the wild-type protein unless a Reactome entity for the exact variant is shown.",
    "Reactome event ordering (precedes) shows curated pathway order, not a measured consequence of the variant.",
    "Open Targets associations are gene-level and aggregated over all variants; they are not variant-specific.",
    "Drug edges show curated mechanisms or disease-specific clinical evidence; none is a treatment recommendation.",
    "Only ClinVar, Ensembl VEP, UniProt, Reactome (+IntAct), Open Targets, CIViC and PubMed are integrated. KEGG is not integrated for licensing reasons.",
    "Coverage is limited to what the public APIs returned at retrieval time; absence of a record is not evidence of absence.",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AnalysisService:
    def __init__(self, http: Optional[HttpClient] = None) -> None:
        self.http = http or http_client
        self.resolver = VariantResolver(self.http)
        self.builder = AnalysisBuilder(self.http)
        self.pubmed = PubMedAdapter(self.http)
        self.reactome = ReactomeAdapter(self.http)
        self.store: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self.max_store = 40

    # ------------------------------------------------------------------ analyse
    async def analyze(self, query: str) -> Dict[str, Any]:
        tracker = Tracker()
        res = await self.resolver.resolve(query, tracker)
        ctx: Optional[Dict[str, Any]] = None
        if res.status in ("resolved", "protein_level", "gene_level"):
            ctx = await self.builder.build(res, tracker)
        analysis_id = uuid.uuid4().hex[:12]
        record = {"id": analysis_id, "created_at": _now(), "query": query.strip(), "res": res, "ctx": ctx, "tracker": tracker,
                  "publications": {}, "ai": None}
        if ctx is not None:
            await self._fetch_publications(record)
        record["payload"] = self._payload(record)
        self.store[analysis_id] = record
        while len(self.store) > self.max_store:
            self.store.popitem(last=False)
        return record["payload"]

    async def _fetch_publications(self, record: Dict[str, Any]) -> None:
        g: Graph = record["ctx"]["graph"]
        counts: Dict[str, int] = {}
        for ev in g.evidence.values():
            for p in ev.publications:
                if p and str(p).isdigit():
                    counts[str(p)] = counts.get(str(p), 0) + 1
        missing = [p for p, _ in sorted(counts.items(), key=lambda kv: -kv[1]) if p not in record["publications"]][:MAX_PUBLICATIONS]
        if not missing:
            return
        try:
            meta = await self.pubmed.summaries(missing, record["tracker"])
            for pmid, m in meta.items():
                m["design"] = methods_from_pubtypes(m.get("pubtypes"))
            record["publications"].update(meta)
        except SourceError as exc:
            record["tracker"].note("pubmed", f"publication metadata unavailable: {exc.message}")
        if len(counts) > MAX_PUBLICATIONS:
            record["tracker"].note("pubmed", f"metadata fetched for the {MAX_PUBLICATIONS} most-cited of {len(counts)} PMIDs; others are listed by ID only")

    # ------------------------------------------------------------------ payload
    def _payload(self, record: Dict[str, Any]) -> Dict[str, Any]:
        res = record["res"]
        ctx = record["ctx"]
        tracker: Tracker = record["tracker"]
        sources = tracker.summary()
        base = {
            "analysis_id": record["id"],
            "created_at": record["created_at"],
            "query": record["query"],
            "mode": "offline_replay" if settings.offline else "live",
            "snapshot": None,
            "resolution": res.to_dict(),
            "sources": sources,
            "limitations": STANDING_LIMITATIONS,
            "ai": ai_available(),
            "assistant_suggestions": [],
        }
        if ctx is None:
            base.update({"root_id": None, "graph": {"nodes": [], "edges": [], "evidence": {}}, "publications": {}, "conflicts": [],
                         "gaps": [], "impact": None, "synthesis": None, "overview": None})
            return base
        g: Graph = ctx["graph"]
        root = self.builder.root_id(res)
        conflicts = find_conflicts(ctx)
        base.update({
            "root_id": root,
            "graph": g.to_dict(),
            "publications": record["publications"],
            "conflicts": conflicts,
            "gaps": find_gaps(ctx, sources),
            "impact": impact_summary(ctx, root),
            "synthesis": deterministic_synthesis(ctx, root, conflicts),
            "ai_synthesis": record.get("ai"),
            "overview": self._overview(ctx),
            "assistant_suggestions": None,
            "display_rules": {
                "max_pathways": MAX_PATHWAYS,
                "pathway_order": "gene symbol in pathway name → disease pathways when the variant has a pathogenic/oncogenic/somatic classification → Reactome order",
                "path_ranking": "fewest hops first; ties broken by stronger evidence category (curated > experimental > association > computational > inferred) and then by more supporting records. Not a probability.",
            },
        })
        if ctx is not None:
            from app.pipeline.assistant import suggestions
            base["assistant_suggestions"] = suggestions(base)
        return base

    def _overview(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        res = ctx["res"]
        data = ctx["data"]
        cv = res.clinvar
        protein = None
        if res.protein:
            protein = {k: v for k, v in res.protein.items() if k not in ("sequence", "features")}
            protein["features_at_variant"] = data.get("features_at")
            protein["feature_count"] = len(res.protein.get("features", []))
            protein["track"] = [{k: f[k] for k in ("type", "start", "end", "description", "category")}
                                for f in res.protein.get("features", [])
                                if f["type"] in ("Domain", "Region", "Topological domain", "Transmembrane", "Motif", "Active site", "Binding site")][:60]
        vep = None
        if res.vep:
            vep = dict(res.vep)
            col = dict(vep.get("colocated") or {})
            col["pubmed_count"] = len(col.get("pubmed") or [])
            col["pubmed"] = (col.get("pubmed") or [])[:30]
            vep["colocated"] = col
        civic = data.get("civic_payload")
        civic_summary = None
        if "civic" in data:
            civic_summary = {"available": civic is not None, "profile": (civic or {}).get("profile"), "total": (civic or {}).get("total", 0),
                             "related_profiles": (civic or {}).get("related_profiles", []), "items": (civic or {}).get("items", [])[:60]}
        return {
            "clinvar": cv,
            "clinvar_submissions": data.get("clinvar_submissions", []),
            "vep": vep,
            "protein": protein,
            "gene": res.gene,
            "civic": civic_summary,
            "opentargets": {"associations": data.get("ot_assoc_payload"), "drugs": data.get("ot_drugs_payload")},
            "reactome": {"pathways_total": len(data.get("all_pathways") or []), "pathways_shown": data.get("pathways_shown"),
                         "reactions_total": len(data.get("all_reactions") or []), "focus_pathway": data.get("focus_pathway"),
                         "all_pathways": [{"stId": p["stId"], "name": p["name"], "isInDisease": p.get("isInDisease"), "url": p.get("url")}
                                          for p in (data.get("all_pathways") or [])]},
        }

    # ------------------------------------------------------------------ lookups
    def get(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        record = self.store.get(analysis_id)
        return record["payload"] if record else None

    def _record(self, analysis_id: str) -> Dict[str, Any]:
        record = self.store.get(analysis_id)
        if record is None:
            raise KeyError(analysis_id)
        return record

    async def expand(self, analysis_id: str, node_id: str, action: str) -> Dict[str, Any]:
        record = self._record(analysis_id)
        ctx = record["ctx"]
        if ctx is None:
            raise ValueError("This analysis has no graph to expand.")
        if record.get("snapshot_of"):
            raise ValueError("Snapshots are read-only. Re-run the query to explore with live data.")
        g: Graph = ctx["graph"]
        if node_id not in g.nodes:
            raise KeyError(node_id)
        node = g.nodes[node_id]
        before_nodes, before_edges = set(g.nodes), set(g.edges)
        st_id = node_id.split(":", 1)[1] if node_id.startswith("reactome:") else None
        if action == "all_pathways" and node.type == "protein":
            await self.builder.expand_all_pathways(ctx)
        elif action == "reactions" and node.type == "pathway" and st_id:
            await self.builder.expand_pathway(ctx, st_id)
        elif action == "downstream" and node.type == "reaction" and st_id:
            await self.builder.expand_downstream(ctx, st_id)
        elif action == "consumers" and node.type in ("physical_entity", "reactome_entity") and st_id:
            await self.builder.expand_consumers(ctx, st_id)
        else:
            raise ValueError(f"Action '{action}' is not available for a {node.type} node.")
        await self._fetch_publications(record)
        record["payload"] = self._payload(record)
        added_nodes = [n for n in g.nodes if n not in before_nodes]
        added_edges = [e for e in g.edges if e not in before_edges]
        return {"analysis": record["payload"], "added_nodes": added_nodes, "added_edges": added_edges,
                "message": f"Added {len(added_nodes)} node(s) and {len(added_edges)} relationship(s)." if added_nodes or added_edges
                else "No further source-backed relationships were found for this action."}

    def path(self, analysis_id: str, target: str, source: Optional[str] = None) -> Dict[str, Any]:
        record = self._record(analysis_id)
        ctx = record["ctx"]
        if ctx is None:
            raise ValueError("No graph for this analysis.")
        g: Graph = ctx["graph"]
        src = source or record["payload"].get("root_id")
        p = explain_path(g, src, target)
        if p is None:
            return {"found": False, "source": src, "target": target,
                    "message": "No connecting path exists in the retrieved graph. PathwayGPS does not invent one."}
        p["found"] = True
        p["verdict_text"] = VERDICT_TEXT[p["verdict"]]
        p["evidence"] = {h["edge_id"]: [g.evidence[x].id for x in g.edges[h["edge_id"]].evidence] for h in p["hops"]}
        return p

    def routes(self, analysis_id: str, target: str, k: int = 3) -> Dict[str, Any]:
        record = self._record(analysis_id)
        if record["ctx"] is None:
            raise ValueError("No graph for this analysis.")
        g: Graph = record["ctx"]["graph"]
        src = record["payload"].get("root_id")
        routes = k_routes(g, src, target, max(1, min(k, 5)))
        for r in routes:
            r["verdict_text"] = VERDICT_TEXT[r["verdict"]]
            r["evidence"] = {h["edge_id"]: g.edges[h["edge_id"]].evidence for h in r["hops"]}
        return {"source": src, "target": target, "routes": routes,
                "message": None if routes else "No connecting route exists in the retrieved graph. PathwayGPS does not invent one.",
                "ranking": "Fewest steps first, then strongest evidence category, then most supporting records. Not a probability."}

    async def chat(self, analysis_id: str, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        from app.pipeline.assistant import chat as assistant_chat
        record = self._record(analysis_id)
        if record["ctx"] is None:
            return {"mode": "retrieval", "answer": "This query was not resolved, so there is no evidence to discuss. " + record["payload"]["resolution"]["message"], "citations": [], "follow_up": []}
        return await assistant_chat(record["payload"], messages)

    async def synthesize_ai(self, analysis_id: str) -> Dict[str, Any]:
        record = self._record(analysis_id)
        if record["ctx"] is None:
            raise ValueError("No evidence to synthesise.")
        status = ai_available()
        if not status["enabled"]:
            return {"mode": "unavailable", **status,
                    "message": "AI synthesis is disabled: install the 'anthropic' package and set ANTHROPIC_API_KEY on the server. The deterministic, citation-linked summary is shown instead."}
        try:
            result = await ai_synthesis(record["payload"])
        except Exception as exc:  # network/auth errors must not break the analysis
            record["tracker"].note("anthropic", f"synthesis failed: {exc.__class__.__name__}")
            return {"mode": "error", "message": f"AI synthesis failed ({exc.__class__.__name__}). The deterministic summary remains available."}
        record["ai"] = result
        record["payload"]["ai_synthesis"] = result
        return result or {"mode": "unavailable"}

    # ------------------------------------------------------------------ literature
    async def abstract(self, pmid: str) -> Dict[str, Any]:
        tracker = Tracker()
        return await self.pubmed.abstract(pmid, tracker)

    async def literature_search(self, query: str, limit: int = 15) -> Dict[str, Any]:
        tracker = Tracker()
        found = await self.pubmed.search(query, tracker, retmax=limit)
        meta = await self.pubmed.summaries(found["ids"], tracker) if found["ids"] else {}
        return {"query": query, "count": found["count"], "query_translation": found.get("query_translation"),
                "results": [meta[i] for i in found["ids"] if i in meta],
                "note": "Keyword search results: co-mention of terms in PubMed, not evidence for any specific relationship."}

    async def enrichment(self, identifiers: List[str]) -> Dict[str, Any]:
        clean = [i.strip().upper() for i in identifiers if i and re.match(r"^[A-Za-z0-9\-\._]{1,30}$", i.strip())]
        clean = list(dict.fromkeys(clean))[:500]
        if len(clean) < 3:
            raise ValueError("Provide at least 3 gene symbols or UniProt accessions. Over-representation analysis is not meaningful for a single gene or variant.")
        tracker = Tracker()
        result = await self.reactome.analyse_identifiers(clean, tracker)
        result["submitted"] = len(clean)
        result["note"] = ("Reactome over-representation analysis (hypergeometric test, Benjamini–Hochberg FDR) of the submitted list against all "
                          "Reactome human entities. Statistical enrichment indicates over-representation, not mechanism or causality.")
        return result

    # ------------------------------------------------------------------ compare
    async def compare(self, a: str, b: str) -> Dict[str, Any]:
        pa, pb = await asyncio.gather(self.analyze(a), self.analyze(b))

        def labels(p: Dict[str, Any], node_type: str) -> Dict[str, str]:
            return {n["id"]: n["label"] for n in p["graph"]["nodes"] if n["type"] == node_type}

        def section(node_type: str) -> Dict[str, Any]:
            la, lb = labels(pa, node_type), labels(pb, node_type)
            shared = sorted(set(la) & set(lb))
            return {"shared": [{"id": i, "label": la[i]} for i in shared],
                    "only_a": [{"id": i, "label": la[i]} for i in sorted(set(la) - set(lb))],
                    "only_b": [{"id": i, "label": lb[i]} for i in sorted(set(lb) - set(la))]}

        def all_pathways(p: Dict[str, Any]) -> Dict[str, str]:
            ov = p.get("overview") or {}
            return {x["stId"]: x["name"] for x in ((ov.get("reactome") or {}).get("all_pathways") or [])}

        apw, bpw = all_pathways(pa), all_pathways(pb)
        return {
            "a": pa, "b": pb,
            "diff": {
                "pathways_all": {"shared": [{"id": k, "label": apw[k]} for k in sorted(set(apw) & set(bpw))],
                                 "only_a": [{"id": k, "label": apw[k]} for k in sorted(set(apw) - set(bpw))],
                                 "only_b": [{"id": k, "label": bpw[k]} for k in sorted(set(bpw) - set(apw))]},
                "diseases": section("disease"),
                "drugs": section("drug"),
                "reactions_drawn": section("reaction"),
            },
            "note": "Pathway overlap compares all Reactome pathways retrieved for each protein (not only those drawn). Shared pathways mean both wild-type proteins participate; they do not imply the variants have the same effect.",
        }

    # ------------------------------------------------------------------ snapshots
    def save_snapshot(self, analysis_id: str, notes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        record = self._record(analysis_id)
        payload = json.loads(json.dumps(record["payload"], default=str))
        snap_id = uuid.uuid4().hex[:12]
        payload["snapshot"] = {"id": snap_id, "saved_at": _now(), "original_analysis_id": analysis_id,
                               "original_created_at": record["created_at"], "workbench": notes or {},
                               "statement": "Frozen copy of the analysis as retrieved; external data are not refreshed. Re-run the query to compare with current source data."}
        settings.snapshot_dir.mkdir(parents=True, exist_ok=True)
        (settings.snapshot_dir / f"{snap_id}.json").write_text(json.dumps(payload), encoding="utf-8")
        return payload["snapshot"]

    def list_snapshots(self) -> List[Dict[str, Any]]:
        rows = []
        if not settings.snapshot_dir.exists():
            return rows
        for path in sorted(settings.snapshot_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                snap = data.get("snapshot") or {}
                rows.append({"id": snap.get("id") or path.stem, "query": data.get("query"), "saved_at": snap.get("saved_at"),
                             "original_created_at": snap.get("original_created_at"), "status": (data.get("resolution") or {}).get("status")})
            except (OSError, ValueError):
                continue
        return rows

    def load_snapshot(self, snap_id: str) -> Dict[str, Any]:
        if not SNAPSHOT_ID_RE.match(snap_id):
            raise KeyError(snap_id)
        path = settings.snapshot_dir / f"{snap_id}.json"
        if not path.exists():
            raise KeyError(snap_id)
        return self.register_snapshot(json.loads(path.read_text(encoding="utf-8")))

    def register_snapshot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make a snapshot (saved or imported) addressable for path/report endpoints, read-only."""
        if not isinstance(payload, dict) or "graph" not in payload or "resolution" not in payload:
            raise ValueError("Not a PathwayGPS snapshot file.")
        graph = Graph.from_dict(payload["graph"])
        new_id = uuid.uuid4().hex[:12]
        payload = dict(payload)
        payload["analysis_id"] = new_id
        payload.setdefault("snapshot", {"id": None, "statement": "Imported analysis file; external data are not refreshed."})

        res = None  # snapshots keep the serialised resolution in the payload only
        record = {"id": new_id, "created_at": payload.get("created_at"), "query": payload.get("query"), "res": res,
                  "ctx": {"graph": graph, "res": res, "data": {}}, "tracker": Tracker(), "publications": payload.get("publications", {}),
                  "payload": payload, "snapshot_of": (payload.get("snapshot") or {}).get("id") or "imported", "ai": payload.get("ai_synthesis")}
        self.store[new_id] = record
        return payload


service = AnalysisService()
