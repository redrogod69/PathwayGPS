"""Derived views over an analysis graph: conflicts, gaps, explainable paths, impact summary.

Path ranking logic (documented; not a probability of anything):
    cost(path) = Σ over hops of (1 + penalty[weakest evidence category on that edge])
    penalty: curated 0, experimental 0.1, association 0.25, computational 0.3, inferred 0.5, hypothesis 0.9
Because every penalty is < 1, a shorter path always wins; among equally short paths the one
whose edges carry stronger evidence categories wins; ties are broken by more supporting records.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from app.adapters.clinvar import germline_group
from app.domain.model import CATEGORY_ORDER, Graph

PENALTY = {"curated": 0.0, "experimental": 0.1, "association": 0.25, "computational": 0.3, "inferred": 0.5, "hypothesis": 0.9}
GROUP_LABEL = {"pathogenic": "Pathogenic / Likely pathogenic", "uncertain": "Uncertain significance", "benign": "Benign / Likely benign", "other": "Other (drug response, risk factor, …)"}


# ---------------------------------------------------------------------------- paths
def explain_path(g: Graph, source: str, target: str) -> Optional[Dict[str, Any]]:
    """Best evidence-aware path from ``source`` to ``target`` (edges may be walked in either direction)."""
    if source not in g.nodes or target not in g.nodes:
        return None
    adj: Dict[str, List[Tuple[str, str, bool]]] = defaultdict(list)
    for e in g.edges.values():
        adj[e.source].append((e.target, e.id, True))
        adj[e.target].append((e.source, e.id, False))

    def edge_cost(eid: str) -> float:
        edge = g.edges[eid]
        # An edge is as strong as its best supporting record (one curated record suffices to support it);
        # more records break ties only.
        best = min((CATEGORY_ORDER.index(c) for c in edge.categories), default=CATEGORY_ORDER.index("inferred"))
        return 1 + PENALTY[CATEGORY_ORDER[best]] - 0.001 * min(len(edge.evidence), 20)

    best_cost = {source: 0.0}
    heap: List[Tuple[float, int, str, List[Tuple[str, bool]]]] = [(0.0, 0, source, [])]
    counter = 0
    while heap:
        cost, _, node, path = heapq.heappop(heap)
        if node == target:
            return _describe(g, source, target, path, cost)
        if cost > best_cost.get(node, float("inf")) or len(path) > 8:
            continue
        for nxt, eid, forward in adj.get(node, []):
            new_cost = cost + edge_cost(eid)
            if new_cost < best_cost.get(nxt, float("inf")):
                best_cost[nxt] = new_cost
                counter += 1
                heapq.heappush(heap, (new_cost, counter, nxt, path + [(eid, forward)]))
    return None


def k_routes(g: Graph, source: str, target: str, k: int = 3) -> List[Dict[str, Any]]:
    """Up to k distinct evidence-aware routes (Yen-style: re-search with one edge of the best route removed)."""
    best = explain_path(g, source, target)
    if best is None:
        return []
    routes = [best]
    seen = {tuple(h["edge_id"] for h in best["hops"])}
    candidates: List[Dict[str, Any]] = []
    for base in list(routes):
        for hop in base["hops"]:
            removed = g.edges.pop(hop["edge_id"])
            try:
                alt = explain_path(g, source, target)
            finally:
                g.edges[hop["edge_id"]] = removed
            if alt:
                key = tuple(h["edge_id"] for h in alt["hops"])
                if key not in seen:
                    seen.add(key)
                    candidates.append(alt)
    candidates.sort(key=lambda r: r["cost"])
    routes.extend(candidates[: max(0, k - 1)])
    for i, r in enumerate(routes, 1):
        r["rank"] = i
    return routes


def _describe(g: Graph, source: str, target: str, path: List[Tuple[str, bool]], cost: float) -> Dict[str, Any]:
    hops = []
    node_ids = [source]
    for eid, forward in path:
        e = g.edges[eid]
        frm, to = (e.source, e.target) if forward else (e.target, e.source)
        node_ids.append(to)
        evs = [g.evidence[x] for x in e.evidence if x in g.evidence]
        pmids = sorted({p for ev in evs for p in ev.publications})
        hops.append({
            "edge_id": eid, "from": frm, "to": to, "from_label": g.nodes[frm].label, "to_label": g.nodes[to].label,
            "type": e.type, "label": e.label, "direction": "forward" if forward else "reverse",
            "category": e.category, "categories": e.categories, "evidence_count": len(evs), "publication_count": len(pmids),
            "sources": sorted({ev.source for ev in evs}),
        })
    cats = [h["category"] for h in hops]
    if any(c == "hypothesis" for c in cats):
        verdict = "hypothesis"
    elif any(c == "inferred" for c in cats):
        verdict = "contains_inferred_steps"
    elif any(c == "computational" for c in cats):
        verdict = "contains_computational_steps"
    elif any(c == "association" for c in cats):
        verdict = "contains_association_steps"
    else:
        verdict = "supported_by_curated_or_experimental_evidence"
    return {"source": source, "target": target, "nodes": node_ids, "hops": hops, "verdict": verdict, "cost": round(cost, 3),
            "weakest_category": max(cats, key=CATEGORY_ORDER.index) if cats else None,
            "reverse_hops": sum(1 for h in hops if h["direction"] == "reverse")}


VERDICT_TEXT = {
    "supported_by_curated_or_experimental_evidence": "Every step is supported by curated or experimental source records.",
    "contains_association_steps": "Includes gene-level statistical association steps (not mechanistic).",
    "contains_computational_steps": "Includes computational predictions.",
    "contains_inferred_steps": "Includes steps inferred by PathwayGPS (e.g. coordinate overlap) or by orthology.",
    "hypothesis": "Includes hypothesis steps that require validation.",
}


# ---------------------------------------------------------------------------- conflicts
def find_conflicts(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    res = ctx["res"]
    conflicts: List[Dict[str, Any]] = []
    cv = res.clinvar or {}
    subs = ctx["data"].get("clinvar_submissions", [])

    germ = [s for s in subs if s.get("classification_type") == "germline" and s.get("classification")]
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in germ:
        groups[germline_group(s["classification"]) or "other"].append(s)
    clinical_groups = [k for k in ("pathogenic", "uncertain", "benign") if groups.get(k)]
    aggregate = ((cv.get("germline") or {}).get("description") or "")
    if len(clinical_groups) > 1 or "conflicting" in aggregate.lower():
        conflicts.append({
            "kind": "clinvar_germline_classification",
            "title": "ClinVar submitters disagree on germline classification",
            "summary": f"ClinVar aggregate: '{aggregate or 'n/a'}'. Submissions fall into {len([k for k in groups if groups[k]])} classification groups.",
            "positions": [{
                "label": GROUP_LABEL[k], "count": len(groups[k]),
                "records": [{"id": s["scv"], "url": s.get("url"), "submitter": s.get("submitter"), "classification": s.get("classification"),
                             "review_status": s.get("review_status"), "origin": s.get("origin"), "date": s.get("date_last_evaluated"),
                             "conditions": s.get("conditions")} for s in groups[k][:12]],
            } for k in ("pathogenic", "uncertain", "benign", "other") if groups.get(k)],
            "explanation": "Disagreement can reflect different conditions, inheritance assumptions, sample origin (many 'germline' "
                           "submissions describe somatic tumour observations), evaluation dates or evidence available to each lab. "
                           "PathwayGPS does not adjudicate which submitter is correct.",
            "source": "clinvar",
        })
    origins = sorted({(s.get("origin") or "unknown").lower() for s in subs})
    if cv.get("germline") and (cv.get("somatic_clinical_impact") or cv.get("oncogenicity")):
        conflicts.append({
            "kind": "context_germline_vs_somatic",
            "title": "Germline and somatic contexts are classified separately",
            "summary": f"Germline: {(cv.get('germline') or {}).get('description')}; somatic clinical impact: "
                       f"{(cv.get('somatic_clinical_impact') or {}).get('description') or '—'}; oncogenicity: {(cv.get('oncogenicity') or {}).get('description') or '—'}. "
                       f"Submission origins: {', '.join(origins)}.",
            "positions": [],
            "explanation": "These are different questions (inherited disease risk vs. tumour biology/therapy) and are not contradictory by themselves. "
                           "Do not transfer a somatic therapeutic classification to a germline context or vice versa.",
            "source": "clinvar",
        })

    civic = ctx["data"].get("civic_payload") or {}
    by_pair: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for item in civic.get("items", []):
        if item.get("type") == "PREDICTIVE" and item.get("therapies"):
            by_pair[(" + ".join(sorted(item["therapies"])), item.get("disease") or "")].append(item)
    for (therapy, disease), items in by_pair.items():
        sigs = {i.get("significance") for i in items}
        dirs = {i.get("direction") for i in items}
        if ("SENSITIVITYRESPONSE" in sigs and any(s and "RESIST" in s for s in sigs)) or ("SUPPORTS" in dirs and "DOES_NOT_SUPPORT" in dirs):
            conflicts.append({
                "kind": "civic_opposing_evidence",
                "title": f"CIViC evidence points in different directions: {therapy} in {disease or 'unspecified disease'}",
                "summary": f"{len(items)} accepted evidence items with significance {', '.join(sorted(s for s in sigs if s))} and direction {', '.join(sorted(d for d in dirs if d))}.",
                "positions": [{"label": f"{i.get('significance')} / {i.get('direction')}", "count": 1,
                               "records": [{"id": f"EID{i['eid']}", "url": i["url"], "classification": f"level {i.get('level')}",
                                            "conditions": [i.get("disease")], "submitter": i.get("citation")}]} for i in items[:10]],
                "explanation": "Opposing results may come from different lines of therapy, co-occurring alterations, study designs or evidence levels.",
                "source": "civic",
            })

    primary = ((res.vep or {}).get("primary") or {})
    sift, poly = (primary.get("sift_prediction") or ""), (primary.get("polyphen_prediction") or "")
    if sift and poly and (("deleterious" in sift) != ("damaging" in poly)):
        conflicts.append({
            "kind": "insilico_disagreement",
            "title": "In-silico predictors disagree",
            "summary": f"SIFT: {sift} ({primary.get('sift_score')}); PolyPhen-2: {poly} ({primary.get('polyphen_score')}).",
            "positions": [], "source": "ensembl",
            "explanation": "Computational predictors use different models; under ACMG/AMP guidance their output is supporting-level evidence at most.",
        })
    rc = res.residue_check or {}
    if rc and not rc.get("ok") and res.clinvar:
        conflicts.append({
            "kind": "residue_numbering",
            "title": "Input residue does not match the UniProt canonical sequence",
            "summary": f"Position {rc.get('position')}: UniProt {rc.get('accession')} has {rc.get('observed')}, input says {rc.get('expected')}, but ClinVar has a matching record.",
            "positions": [], "source": "uniprot",
            "explanation": "ClinVar numbers residues on the RefSeq protein of its transcript, which can differ from the UniProt canonical isoform.",
        })
    return conflicts


# ---------------------------------------------------------------------------- gaps
def find_gaps(ctx: Dict[str, Any], sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    res = ctx["res"]
    g: Graph = ctx["graph"]
    gaps = list(ctx["gaps"])
    if res.has_variant and not res.clinvar:
        gaps.append({"kind": "no_clinvar", "message": "No ClinVar record exists for this exact variant, so no submitted clinical classification is available."})
    germ = ((res.clinvar or {}).get("germline") or {}).get("description") or ""
    if "uncertain significance" in germ.lower():
        gaps.append({"kind": "vus", "message": "ClinVar classifies this variant as a Variant of Uncertain Significance (germline). Pathway context here is exploratory and must not be used as a basis for clinical decisions."})
    if res.has_variant and not res.vep:
        gaps.append({"kind": "no_vep", "message": "No Ensembl VEP annotation: transcript consequence and in-silico predictions are missing."})
    no_lit = defaultdict(int)
    for e in g.edges.values():
        evs = [g.evidence[x] for x in e.evidence if x in g.evidence]
        if e.category in ("curated", "experimental") and not any(ev.publications for ev in evs):
            no_lit[e.type] += 1
    if no_lit:
        gaps.append({"kind": "edges_without_literature",
                     "message": "Some curated relationships carry no PubMed reference in the retrieved records: "
                                + ", ".join(f"{k} ×{v}" for k, v in sorted(no_lit.items())) + ". They are shown as curated database assertions without literature, not with invented citations."})
    failed = [s["name"] for s in sources if s["status"] in ("failed", "partial")]
    if failed:
        gaps.append({"kind": "source_failures", "message": f"Some sources did not respond fully: {', '.join(failed)}. Affected sections are incomplete, not empty by biology."})
    total_pw = len(ctx["data"].get("all_pathways") or [])
    shown = len(ctx["data"].get("pathways_shown") or [])
    if total_pw > shown:
        gaps.append({"kind": "pathways_truncated", "message": f"{shown} of {total_pw} Reactome pathways are drawn; use 'Show all pathways' on the protein node to add the rest."})
    if res.status == "protein_level":
        gaps.append({"kind": "no_genomic_coordinates", "message": "Genomic coordinates were not resolved; nucleotide-level annotations (VEP, population data, ClinVar) are absent."})
    return gaps


# ---------------------------------------------------------------------------- impact summary
def impact_summary(ctx: Dict[str, Any], root: str) -> Dict[str, Any]:
    res = ctx["res"]
    g: Graph = ctx["graph"]
    data = ctx["data"]
    direct, downstream, associations, hypotheses = [], [], [], []
    primary = ((res.vep or {}).get("primary") or {})
    if primary:
        direct.append({"label": "Transcript consequence", "value": f"{', '.join(primary.get('consequence_terms') or [])} ({primary.get('impact')})",
                       "detail": f"{primary.get('hgvsc')} / {primary.get('hgvsp')}", "category": "computational", "source": "ensembl"})
    for block, label in (("germline", "ClinVar germline"), ("somatic_clinical_impact", "ClinVar somatic clinical impact"), ("oncogenicity", "ClinVar oncogenicity")):
        cls = (res.clinvar or {}).get(block)
        if cls:
            direct.append({"label": label, "value": cls["description"], "detail": f"{cls.get('review_status')} · last evaluated {cls.get('last_evaluated') or 'n/a'}",
                           "category": "curated", "source": "clinvar"})
    at = data.get("features_at") or {}
    for f in at.get("covering", []):
        direct.append({"label": f"UniProt {f['type'].lower()}", "value": f"{f['description'] or f['type']} ({f['start']}–{f['end']})",
                       "detail": ", ".join(f.get("evidence_codes") or []), "category": "inferred", "source": "uniprot"})
    for f in at.get("nearby", [])[:4]:
        direct.append({"label": f"Nearby {f['type'].lower()}", "value": f"{f['description'] or f['type']} at {f['start']}" + (f"–{f['end']}" if f["end"] != f["start"] else ""),
                       "detail": f"{f['distance']} residue(s) away — proximity only", "category": "inferred", "source": "uniprot"})
    civic = data.get("civic_payload") or {}
    if civic.get("profile"):
        counts = defaultdict(int)
        for i in civic.get("items", []):
            counts[i.get("type")] += 1
        direct.append({"label": "CIViC accepted evidence", "value": f"{civic.get('total')} items", "detail": ", ".join(f"{k.lower()} {v}" for k, v in counts.items()),
                       "category": "curated", "source": "civic"})

    for n in g.nodes.values():
        if n.type in ("reaction", "physical_entity"):
            p = explain_path(g, root, n.id)
            if p:
                downstream.append({"node_id": n.id, "label": n.label, "type": n.type, "hops": len(p["hops"]), "verdict": p["verdict"],
                                   "disease_event": "disease_event" in n.flags or "disease_entity" in n.flags})
    downstream.sort(key=lambda d: (d["hops"], d["label"]))
    for n in g.nodes.values():
        if n.type in ("disease", "drug"):
            p = explain_path(g, root, n.id)
            if p:
                associations.append({"node_id": n.id, "label": n.label, "type": n.type, "hops": len(p["hops"]), "verdict": p["verdict"],
                                     "level": "variant-level" if p["hops"] and p["hops"][0]["from"] == root and len(p["hops"]) == 1 else "gene/protein-level",
                                     "sources": n.attributes.get("harmonized_sources")})
    associations.sort(key=lambda a: (a["level"] != "variant-level", a["type"], a["label"]))

    # Explicitly labelled hypotheses (questions to validate), generated from structure only.
    kinase_regions = [f for f in at.get("covering", []) if "kinase" in (f.get("description") or "").lower()]
    if kinase_regions:
        catalytic = [n for n in g.nodes.values() if n.type == "reaction" and any("kinase activity" in (c or "").lower() for c in n.attributes.get("catalysts") or [])]
        for n in catalytic[:3]:
            hypotheses.append({"node_id": n.id, "text": f"The variant lies in the {kinase_regions[0]['description']} region; does it change the catalytic step '{n.label}'?",
                               "basis": "Coordinate overlap with a kinase domain + Reactome catalyst annotation", "category": "hypothesis"})
    if res.has_variant and ((res.clinvar or {}).get("germline") or {}).get("description", "").lower().startswith("uncertain"):
        hypotheses.append({"node_id": root, "text": "Which functional assay or segregation data could move this VUS toward a definitive classification?",
                           "basis": "ClinVar VUS status", "category": "hypothesis"})
    return {
        "direct": direct,
        "downstream": downstream[:40],
        "associations": associations[:40],
        "hypotheses": hypotheses,
        "counts": {
            "pathways_total": len(data.get("all_pathways") or []),
            "pathways_shown": len(data.get("pathways_shown") or []),
            "reactions_involving_protein": len(data.get("all_reactions") or []),
            "interactors_total": data.get("interactor_total", 0),
            "nodes": len(g.nodes), "edges": len(g.edges), "evidence_records": len(g.evidence),
        },
        "focus_pathway": data.get("focus_pathway"),
    }


# ---------------------------------------------------------------------------- deterministic synthesis
def deterministic_synthesis(ctx: Dict[str, Any], root: str, conflicts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Template-based summary; every sentence cites the evidence-record IDs it is built from."""
    res = ctx["res"]
    g: Graph = ctx["graph"]
    claims: List[Dict[str, Any]] = []

    def ev_for(edge_type: str, target_prefix: str = "") -> List[str]:
        ids = []
        for e in g.edges.values():
            if e.type == edge_type and (not target_prefix or e.target.startswith(target_prefix) or e.source.startswith(target_prefix)):
                ids.extend(e.evidence)
        return ids[:6]

    name = g.nodes[root].label if root in g.nodes else res.query
    primary = ((res.vep or {}).get("primary") or {})
    if primary.get("hgvsp"):
        claims.append({"text": f"{name} is annotated by Ensembl VEP as {', '.join(primary.get('consequence_terms') or [])} ({primary.get('hgvsp')}) on {primary.get('transcript_id')}"
                               + (f" (MANE Select {primary.get('mane_select')})" if primary.get("mane_select") else "") + ".",
                       "evidence": ev_for("VARIANT_ALTERS_PROTEIN"), "kind": "computational annotation"})
    cv = res.clinvar or {}
    parts = []
    for block, label in (("germline", "germline"), ("somatic_clinical_impact", "somatic clinical impact"), ("oncogenicity", "oncogenicity")):
        if cv.get(block):
            parts.append(f"{label}: {cv[block]['description']} ({cv[block].get('review_status')})")
    if parts:
        claims.append({"text": f"ClinVar {cv.get('accession')} reports " + "; ".join(parts) + ".", "evidence": ev_for("VARIANT_ASSOCIATED_WITH_CONDITION"),
                       "kind": "curated classification"})
    regions = [e for e in g.edges.values() if e.type == "VARIANT_IN_PROTEIN_REGION"]
    if regions:
        claims.append({"text": "The altered residue falls within UniProt feature(s): " + ", ".join(g.nodes[e.target].label for e in regions) + " (coordinate overlap).",
                       "evidence": [x for e in regions for x in e.evidence][:6], "kind": "inferred location"})
    pw = [e for e in g.edges.values() if e.type == "PROTEIN_PARTICIPATES_IN_PATHWAY"]
    total = len(ctx["data"].get("all_pathways") or [])
    if pw:
        claims.append({"text": f"Reactome places the wild-type protein in {total} lowest-level pathway(s), including "
                               + ", ".join(g.nodes[e.target].label for e in pw[:4]) + ".",
                       "evidence": [x for e in pw[:4] for x in e.evidence], "kind": "curated pathway membership"})
    focus = ctx["data"].get("focus_pathway")
    prec = [e for e in g.edges.values() if e.type == "REACTION_PRECEDES"]
    if focus and prec:
        claims.append({"text": f"Within '{focus['name']}', Reactome orders {len(prec)} downstream step(s) after reactions involving the protein (event ordering, not a measured effect of the variant).",
                       "evidence": [x for e in prec[:5] for x in e.evidence], "kind": "curated event ordering"})
    civ = [e for e in g.edges.values() if e.type == "VARIANT_PREDICTIVE_FOR_THERAPY"]
    if civ:
        drugs = sorted({g.nodes[e.target].label for e in civ})
        claims.append({"text": "Curated clinical evidence (CIViC / ClinVar somatic submissions) links this variant to therapy response for: " + ", ".join(drugs[:8])
                               + ". This is disease-specific evidence, not a treatment recommendation.",
                       "evidence": [x for e in civ for x in e.evidence][:8], "kind": "curated clinical evidence"})
    if conflicts:
        claims.append({"text": f"{len(conflicts)} evidence disagreement(s) or context differences were detected; see the Conflicts panel.", "evidence": [], "kind": "meta"})
    if not res.has_variant:
        claims.insert(0, {"text": f"Gene-level view of {name}: no variant was specified, so no variant-specific statement is made.", "evidence": [], "kind": "meta"})
    return {"mode": "deterministic", "model": None, "claims": claims,
            "disclaimer": "Generated from retrieved records by fixed templates; no language model was used."}
