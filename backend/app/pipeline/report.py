"""Research report export (Markdown / HTML) built from one block structure.

Abstract text is deliberately excluded (publisher copyright); publications are cited by
title, journal, year and PMID link only.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

Block = Tuple[str, Any]


def _fmt(value: Any) -> str:
    if value is None or value == "" or value == []:
        return "—"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v is not None)
    return str(value)


def build_blocks(p: Dict[str, Any], workbench: Optional[Dict[str, Any]] = None) -> List[Block]:
    res = p.get("resolution") or {}
    g = p.get("graph") or {"nodes": [], "edges": [], "evidence": {}}
    nodes = {n["id"]: n for n in g["nodes"]}
    ov = p.get("overview") or {}
    blocks: List[Block] = []
    blocks.append(("h1", f"PathwayGPS research report — {p.get('query')}"))
    snap = p.get("snapshot")
    blocks.append(("p", f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} · analysis {p.get('analysis_id')} · data retrieved {p.get('created_at')} · mode: {p.get('mode')}"
                   + (f" · snapshot {snap.get('id')} saved {snap.get('saved_at')} (data not refreshed)" if snap else "")))
    blocks.append(("note", "Research use only. Not a clinical diagnostic or treatment recommendation. Computational predictions, curated annotations, "
                           "associations and hypotheses are labelled separately below."))

    blocks.append(("h2", "1. Input and resolution"))
    blocks.append(("kv", [("Input", p.get("query")), ("Detected type", res.get("input_type")), ("Status", res.get("status")),
                          ("Interpretation", res.get("message")), ("Resolved via", res.get("resolved_via"))]))
    if res.get("steps"):
        blocks.append(("table", (["Step", "Source", "Outcome", "Detail"], [[s["step"], s["source"], s["outcome"], s["detail"]] for s in res["steps"]])))
    if res.get("warnings"):
        blocks.append(("h3", "Warnings"))
        blocks.append(("ul", res["warnings"]))
    if res.get("clinvar_alternatives"):
        blocks.append(("h3", "Alternative nucleotide-level records (not analysed)"))
        blocks.append(("ul", [f"{a['accession']} — {a['title']}" for a in res["clinvar_alternatives"]]))

    root = nodes.get(p.get("root_id") or "")
    if root and root["type"] == "variant":
        a = root["attributes"]
        blocks.append(("h2", "2. Variant annotations"))
        blocks.append(("kv", [
            ("HGVS (coding)", a.get("hgvs_c")), ("HGVS (protein)", a.get("hgvs_p")), ("GRCh38", (a.get("grch38") or {}) and f"chr{a['grch38'].get('chr')}:{a['grch38'].get('start')}"),
            ("SPDI", a.get("spdi")), ("Transcript (MANE)", f"{_fmt(a.get('transcript'))} ({_fmt(a.get('mane_select'))})"),
            ("Consequence [computational, VEP]", a.get("consequence")), ("SIFT [computational]", (a.get("sift") or {}).get("prediction")),
            ("PolyPhen-2 [computational]", (a.get("polyphen") or {}).get("prediction")),
            ("ClinVar germline [curated]", (a.get("germline") or {}).get("description") and f"{a['germline']['description']} ({a['germline'].get('review_status')})"),
            ("ClinVar somatic clinical impact [curated]", (a.get("somatic_clinical_impact") or {}).get("description") and f"{a['somatic_clinical_impact']['description']} ({a['somatic_clinical_impact'].get('review_status')})"),
            ("ClinVar oncogenicity [curated]", (a.get("oncogenicity") or {}).get("description") and f"{a['oncogenicity']['description']} ({a['oncogenicity'].get('review_status')})"),
            ("Identifiers", [f"{x['db']} {x['id']}" for x in root.get("xrefs", [])]),
        ]))
        if res.get("residue_check"):
            rc = res["residue_check"]
            blocks.append(("p", f"Reference residue check: position {rc['position']} of {rc['accession']} is {rc.get('observed')} (input {rc['expected']}) — {'match' if rc['ok'] else 'MISMATCH'}."))
    subs = ov.get("clinvar_submissions") or []
    if subs:
        blocks.append(("h3", f"ClinVar submissions ({len(subs)})"))
        blocks.append(("table", (["SCV", "Submitter", "Type", "Classification", "Review status", "Origin", "Conditions", "PMIDs"],
                                 [[s["scv"], s.get("submitter"), s.get("classification_type"), s.get("classification"), s.get("review_status"),
                                   s.get("origin"), _fmt(s.get("conditions")), _fmt(s.get("pmids", [])[:4])] for s in subs[:40]])))

    blocks.append(("h2", "3. Key relationships (evidence ledger)"))
    rows = []
    for e in g["edges"]:
        evs = [g["evidence"][x] for x in e["evidence"] if x in g["evidence"]]
        pmids = sorted({pm for ev in evs for pm in ev.get("publications", [])})
        rows.append([f"{nodes[e['source']]['label']} → {nodes[e['target']]['label']}", e["type"], e["category"],
                     _fmt(sorted({ev['source'] for ev in evs})), str(len(evs)), _fmt(pmids[:6]) + (" …" if len(pmids) > 6 else "")])
    order = {"curated": 0, "experimental": 1, "association": 2, "computational": 3, "inferred": 4, "hypothesis": 5}
    rows.sort(key=lambda r: (order.get(r[2], 9), r[1]))
    blocks.append(("table", (["Relationship", "Type", "Best evidence category", "Sources", "Records", "PMIDs"], rows[:120])))

    imp = p.get("impact") or {}
    if imp:
        blocks.append(("h2", "4. Pathway impact summary"))
        c = imp.get("counts") or {}
        blocks.append(("p", f"Reactome: {c.get('pathways_total', 0)} pathways ({c.get('pathways_shown', 0)} drawn), {c.get('reactions_involving_protein', 0)} reactions involving the protein; "
                            f"IntAct partners: {c.get('interactors_total', 0)}. Graph: {c.get('nodes')} nodes, {c.get('edges')} relationships, {c.get('evidence_records')} evidence records."))
        if imp.get("direct"):
            blocks.append(("h3", "Direct annotations"))
            blocks.append(("table", (["Annotation", "Value", "Detail", "Category"], [[d["label"], d["value"], d.get("detail"), d["category"]] for d in imp["direct"]])))
        if imp.get("downstream"):
            blocks.append(("h3", "Downstream entities reached (Reactome)"))
            blocks.append(("table", (["Entity", "Type", "Hops", "Path evidence"], [[d["label"], d["type"], str(d["hops"]), d["verdict"]] for d in imp["downstream"]])))
        if imp.get("associations"):
            blocks.append(("h3", "Disease and drug context"))
            blocks.append(("table", (["Entity", "Type", "Level", "Path evidence", "Sources"],
                                     [[d["label"], d["type"], d["level"], d["verdict"], _fmt(d.get("sources"))] for d in imp["associations"]])))
    if p.get("conflicts"):
        blocks.append(("h2", "5. Conflicting evidence"))
        for cf in p["conflicts"]:
            blocks.append(("h3", cf["title"]))
            blocks.append(("p", cf["summary"]))
            for pos in cf.get("positions", []):
                blocks.append(("ul", [f"{pos['label']}: " + ", ".join(f"{r['id']} ({_fmt(r.get('submitter'))})" for r in pos["records"][:8])]))
            blocks.append(("note", cf["explanation"]))
    blocks.append(("h2", "6. Evidence gaps and missing information"))
    blocks.append(("ul", [gp["message"] for gp in p.get("gaps", [])] or ["None detected."]))

    hyps = list((imp or {}).get("hypotheses") or [])
    wb = workbench or ((snap or {}).get("workbench") if snap else None) or {}
    blocks.append(("h2", "7. Exploratory hypotheses (require validation)"))
    items = [f"[generated] {h['text']} (basis: {h['basis']})" for h in hyps]
    for note in wb.get("notes", []) if isinstance(wb, dict) else []:
        kind = note.get("kind", "question")
        items.append(f"[researcher · {kind}] {note.get('target_label') or ''}: {note.get('text')}")
    blocks.append(("ul", items or ["No hypotheses recorded."]))

    syn = p.get("ai_synthesis") or p.get("synthesis")
    if syn and syn.get("claims"):
        blocks.append(("h2", f"8. Summary ({'AI-generated, ' + str(syn.get('model')) if syn.get('mode') == 'ai' else 'template-generated'})"))
        blocks.append(("ul", [f"{c['text']} [{c.get('kind')}; evidence: {', '.join(c.get('evidence', [])[:4]) or 'n/a'}]" for c in syn["claims"]]))
        blocks.append(("note", syn.get("disclaimer", "")))

    pubs = p.get("publications") or {}
    blocks.append(("h2", "9. References"))
    if pubs:
        blocks.append(("ul", [f"{_fmt(m.get('authors'))} ({_fmt(m.get('year'))}). {m.get('title')} {m.get('journal') or ''}. PMID {pm} — https://pubmed.ncbi.nlm.nih.gov/{pm}/"
                              + (f" doi:{m['doi']}" if m.get("doi") else "") for pm, m in sorted(pubs.items(), key=lambda kv: kv[1].get("year") or "", reverse=True)]))
    else:
        blocks.append(("p", "No publication metadata was retrieved."))
    blocks.append(("h2", "10. Data sources"))
    blocks.append(("table", (["Source", "Status", "Release", "Last retrieved", "Calls (cached)", "Licence"],
                             [[s["name"], s["status"], _fmt(s.get("release")), _fmt(s.get("last_retrieved_at")), f"{s['calls']} ({s['from_cache']})", s["license"]]
                              for s in p.get("sources", [])])))
    blocks.append(("h2", "11. Limitations"))
    blocks.append(("ul", p.get("limitations", [])))
    return blocks


def to_markdown(blocks: List[Block]) -> str:
    out: List[str] = []
    for kind, val in blocks:
        if kind == "h1":
            out.append(f"# {val}\n")
        elif kind == "h2":
            out.append(f"\n## {val}\n")
        elif kind == "h3":
            out.append(f"\n### {val}\n")
        elif kind == "p":
            out.append(f"{val}\n")
        elif kind == "note":
            out.append(f"> {val}\n")
        elif kind == "ul":
            out.extend(f"- {x}" for x in val)
            out.append("")
        elif kind == "kv":
            out.extend(f"- **{k}:** {_fmt(v)}" for k, v in val)
            out.append("")
        elif kind == "table":
            header, rows = val
            esc = lambda s: _fmt(s).replace("|", "\\|").replace("\n", " ")
            out.append("| " + " | ".join(header) + " |")
            out.append("|" + "---|" * len(header))
            out.extend("| " + " | ".join(esc(c) for c in r) + " |" for r in rows)
            out.append("")
    return "\n".join(out)


def to_html(blocks: List[Block], title: str) -> str:
    e = html.escape
    body: List[str] = []
    for kind, val in blocks:
        if kind in ("h1", "h2", "h3"):
            body.append(f"<{kind}>{e(str(val))}</{kind}>")
        elif kind == "p":
            body.append(f"<p>{e(str(val))}</p>")
        elif kind == "note":
            body.append(f"<p class='note'>{e(str(val))}</p>")
        elif kind == "ul":
            body.append("<ul>" + "".join(f"<li>{e(str(x))}</li>" for x in val) + "</ul>")
        elif kind == "kv":
            body.append("<dl>" + "".join(f"<dt>{e(k)}</dt><dd>{e(_fmt(v))}</dd>" for k, v in val) + "</dl>")
        elif kind == "table":
            header, rows = val
            body.append("<table><thead><tr>" + "".join(f"<th>{e(h)}</th>" for h in header) + "</tr></thead><tbody>"
                        + "".join("<tr>" + "".join(f"<td>{e(_fmt(c))}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table>")
    css = """body{font:14px/1.5 -apple-system,Segoe UI,Inter,sans-serif;max-width:1100px;margin:32px auto;padding:0 16px;color:#0f172a}
h1{font-size:24px;border-bottom:3px solid #0891b2;padding-bottom:8px}h2{font-size:18px;margin-top:32px;color:#0e7490}h3{font-size:15px}
table{border-collapse:collapse;width:100%;font-size:12px;margin:8px 0}th,td{border:1px solid #cbd5e1;padding:4px 6px;text-align:left;vertical-align:top}
th{background:#ecfeff}.note{background:#fef9c3;border-left:4px solid #ca8a04;padding:8px 12px}dl{display:grid;grid-template-columns:260px 1fr;gap:2px 12px}
dt{font-weight:600;color:#334155}dd{margin:0}@media print{body{margin:0}}"""
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{e(title)}</title><style>{css}</style></head><body>{''.join(body)}</body></html>"
