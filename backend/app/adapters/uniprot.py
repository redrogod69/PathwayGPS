"""UniProtKB adapter: reviewed protein entry, function, features at a residue."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from app.core.http import HttpClient, Tracker

BASE = "https://rest.uniprot.org/uniprotkb"
FIELDS = ",".join([
    "accession", "id", "protein_name", "gene_names", "length", "sequence", "annotation_score",
    "cc_function", "cc_subcellular_location", "cc_disease",
    "ft_domain", "ft_region", "ft_act_site", "ft_binding", "ft_mod_res", "ft_motif", "ft_topo_dom",
    "ft_transmem", "ft_variant", "ft_mutagen", "ft_site", "xref_reactome", "xref_pdb", "xref_ensembl",
])

# ECO evidence code → PathwayGPS evidence category
ECO_CATEGORY = {
    "ECO:0000269": "curated",       # experimental evidence used in manual assertion
    "ECO:0000303": "curated",       # author statement (non-traceable), manual
    "ECO:0000305": "curated",       # curator inference, manual
    "ECO:0000250": "inferred",      # sequence similarity evidence used in manual assertion
    "ECO:0000255": "computational", # match to sequence model evidence used in manual assertion
    "ECO:0000256": "computational", # match to sequence model, automatic
    "ECO:0000259": "computational", # match to InterPro member signature, automatic
    "ECO:0007744": "curated",       # combinatorial computational and experimental (e.g. PDB structures)
    "ECO:0007829": "computational",
}
ECO_LABEL = {
    "ECO:0000269": "experimental evidence (manual)",
    "ECO:0000303": "author statement (manual)",
    "ECO:0000305": "curator inference (manual)",
    "ECO:0000250": "by sequence similarity (manual)",
    "ECO:0000255": "sequence-model match (manual)",
    "ECO:0000256": "sequence-model match (automatic)",
    "ECO:0000259": "InterPro signature (automatic)",
    "ECO:0007744": "combinatorial experimental + computational",
    "ECO:0007829": "combinatorial computational (automatic)",
}
REGION_TYPES = {"Domain", "Region", "Topological domain", "Transmembrane", "Motif"}
SITE_TYPES = {"Active site", "Binding site", "Site", "Modified residue"}


def _category_for(evidences: List[Dict[str, Any]]) -> str:
    cats = [ECO_CATEGORY.get(e.get("evidenceCode", ""), "computational") for e in evidences] or ["computational"]
    for preferred in ("curated", "experimental", "inferred", "computational"):
        if preferred in cats:
            return preferred
    return "computational"


class UniProtAdapter:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    async def reviewed_entries_for_gene(self, symbol: str, tracker: Tracker) -> List[Dict[str, Any]]:
        resp = await self.http.get("uniprot", f"{BASE}/search", tracker=tracker, purpose="reviewed protein for gene", params={
            "query": f"gene_exact:{symbol} AND organism_id:9606 AND reviewed:true", "format": "json", "fields": FIELDS, "size": 5,
        })
        release = None
        return [self.normalize(e, resp.fetched_at, release) for e in (resp.data or {}).get("results", [])]

    async def entry(self, accession: str, tracker: Tracker) -> Optional[Dict[str, Any]]:
        resp = await self.http.get("uniprot", f"{BASE}/{quote(accession)}", tracker=tracker, purpose="protein entry",
                                   params={"format": "json", "fields": FIELDS}, allow_status=(400, 404))
        if resp.status >= 400 or not resp.data:
            return None
        return self.normalize(resp.data, resp.fetched_at, None)

    @staticmethod
    def normalize(entry: Dict[str, Any], fetched_at: str, release: Optional[str]) -> Dict[str, Any]:
        acc = entry.get("primaryAccession")
        desc = entry.get("proteinDescription", {}) or {}
        name = ((desc.get("recommendedName") or {}).get("fullName") or {}).get("value")
        if not name:
            sub = desc.get("submissionNames") or [{}]
            name = (sub[0].get("fullName") or {}).get("value")
        genes = entry.get("genes", []) or []
        gene_names = [g.get("geneName", {}).get("value") for g in genes if g.get("geneName")]
        synonyms = [s.get("value") for g in genes for s in g.get("synonyms", []) or []]
        function_texts, function_pmids = [], []
        subcellular, diseases = [], []
        for c in entry.get("comments", []) or []:
            ctype = c.get("commentType")
            if ctype == "FUNCTION":
                for t in c.get("texts", []) or []:
                    function_texts.append(t.get("value"))
                    for ev in t.get("evidences", []) or []:
                        if ev.get("source") == "PubMed" and ev.get("id") not in function_pmids:
                            function_pmids.append(ev.get("id"))
            elif ctype == "SUBCELLULAR LOCATION":
                for loc in c.get("subcellularLocations", []) or []:
                    value = (loc.get("location") or {}).get("value")
                    if value and value not in subcellular:
                        subcellular.append(value)
            elif ctype == "DISEASE":
                d = c.get("disease") or {}
                if d.get("diseaseId"):
                    diseases.append({"name": d.get("diseaseId"), "acronym": d.get("acronym"), "mim": (d.get("diseaseCrossReference") or {}).get("id")})
        features = []
        for f in entry.get("features", []) or []:
            loc = f.get("location", {}) or {}
            start = (loc.get("start") or {}).get("value")
            end = (loc.get("end") or {}).get("value")
            if start is None or end is None:
                continue
            evidences = f.get("evidences", []) or []
            alt = f.get("alternativeSequence") or {}
            features.append({
                "type": f.get("type"),
                "start": int(start),
                "end": int(end),
                "description": f.get("description") or "",
                "feature_id": f.get("featureId"),
                "original": alt.get("originalSequence"),
                "alternatives": alt.get("alternativeSequences", []) or [],
                "evidence_codes": sorted({e.get("evidenceCode") for e in evidences if e.get("evidenceCode")}),
                "pmids": sorted({e.get("id") for e in evidences if e.get("source") == "PubMed" and e.get("id")}),
                "evidence_sources": sorted({f"{e.get('source')}:{e.get('id')}" for e in evidences if e.get("source") and e.get("source") != "PubMed"})[:6],
                "category": _category_for(evidences),
            })
        xrefs = entry.get("uniProtKBCrossReferences", []) or []
        seq = (entry.get("sequence") or {}).get("value") or ""
        return {
            "accession": acc,
            "entry_name": entry.get("uniProtkbId"),
            "reviewed": "reviewed" in str(entry.get("entryType", "")).lower() and "unreviewed" not in str(entry.get("entryType", "")).lower(),
            "protein_name": name,
            "gene_names": gene_names,
            "gene_synonyms": synonyms,
            "length": (entry.get("sequence") or {}).get("length") or len(seq),
            "sequence": seq,
            "annotation_score": entry.get("annotationScore"),
            "function": function_texts,
            "function_pmids": function_pmids[:30],
            "subcellular_location": subcellular[:8],
            "diseases": diseases[:10],
            "features": features,
            "reactome_ids": [x.get("id") for x in xrefs if x.get("database") == "Reactome"],
            "pdb_count": sum(1 for x in xrefs if x.get("database") == "PDB"),
            "url": f"https://www.uniprot.org/uniprotkb/{acc}/entry",
            "retrieved_at": fetched_at,
        }


def features_at(protein: Dict[str, Any], position: int, window: int = 0) -> Dict[str, List[Dict[str, Any]]]:
    """Split UniProt features into those covering ``position`` and those near it."""
    covering, nearby, at_residue = [], [], []
    for f in protein.get("features", []):
        if f["type"] in ("Natural variant", "Mutagenesis"):
            if f["start"] <= position <= f["end"]:
                at_residue.append(f)
            continue
        if f["start"] <= position <= f["end"]:
            covering.append(f)
        elif window and (abs(f["start"] - position) <= window or abs(f["end"] - position) <= window) and f["type"] in SITE_TYPES:
            nearby.append({**f, "distance": min(abs(f["start"] - position), abs(f["end"] - position))})
    return {"covering": covering, "nearby": sorted(nearby, key=lambda x: x["distance"]), "at_residue": at_residue}


def reference_residue(protein: Dict[str, Any], position: int) -> Optional[str]:
    seq = protein.get("sequence") or ""
    if 1 <= position <= len(seq):
        return seq[position - 1]
    return None


def eco_label(code: str) -> str:
    return ECO_LABEL.get(code, code)
