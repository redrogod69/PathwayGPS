"""Ensembl REST adapter: gene lookup, alias resolution and VEP annotation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from app.core.http import HttpClient, SourceError, Tracker

BASE = "https://rest.ensembl.org"
VEP_PARAMS = {
    "content-type": "application/json",
    "canonical": "1",
    "mane": "1",
    "hgvs": "1",
    "uniprot": "1",
    "numbers": "1",
    "variant_class": "1",
    "protein": "1",
    "domains": "1",
}
DOMAIN_DBS = {"Pfam", "PROSITE_profiles", "PROSITE_patterns", "SMART", "PANTHER", "CDD", "Gene3D", "Superfamily"}


class EnsemblAdapter:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    async def release(self, tracker: Tracker) -> Optional[str]:
        try:
            resp = await self.http.get("ensembl", f"{BASE}/info/data", tracker=tracker, params={"content-type": "application/json"},
                                       purpose="release metadata", timeout=10)
            releases = (resp.data or {}).get("releases") or []
            return str(releases[0]) if releases else None
        except SourceError:
            return None

    async def lookup_symbol(self, symbol: str, tracker: Tracker) -> Optional[Dict[str, Any]]:
        resp = await self.http.get("ensembl", f"{BASE}/lookup/symbol/homo_sapiens/{quote(symbol)}", tracker=tracker,
                                   params={"content-type": "application/json"}, allow_status=(400, 404), purpose="gene lookup")
        data = resp.data or {}
        if resp.status >= 400 or not data.get("id"):
            return None
        return self._gene(data, resp.fetched_at)

    async def lookup_id(self, ensembl_id: str, tracker: Tracker) -> Optional[Dict[str, Any]]:
        resp = await self.http.get("ensembl", f"{BASE}/lookup/id/{quote(ensembl_id)}", tracker=tracker,
                                   params={"content-type": "application/json"}, allow_status=(400, 404), purpose="gene lookup by id")
        data = resp.data or {}
        if resp.status >= 400 or not data.get("id"):
            return None
        return self._gene(data, resp.fetched_at)

    @staticmethod
    def _gene(data: Dict[str, Any], fetched_at: str) -> Dict[str, Any]:
        description = data.get("description") or ""
        hgnc = None
        if "HGNC:" in description:
            hgnc = "HGNC:" + description.split("HGNC:")[-1].rstrip("]").strip()
        return {
            "ensembl_id": data.get("id"),
            "symbol": data.get("display_name"),
            "description": description.split(" [Source")[0] if description else None,
            "hgnc_id": hgnc,
            "biotype": data.get("biotype"),
            "chromosome": data.get("seq_region_name"),
            "start": data.get("start"),
            "end": data.get("end"),
            "strand": data.get("strand"),
            "assembly": data.get("assembly_name"),
            "canonical_transcript": data.get("canonical_transcript"),
            "retrieved_at": fetched_at,
            "url": f"https://www.ensembl.org/Homo_sapiens/Gene/Summary?g={data.get('id')}",
        }

    async def resolve_alias(self, symbol: str, tracker: Tracker) -> List[str]:
        """Return Ensembl gene IDs whose symbol or synonym matches ``symbol``."""
        resp = await self.http.get("ensembl", f"{BASE}/xrefs/symbol/homo_sapiens/{quote(symbol)}", tracker=tracker,
                                   params={"content-type": "application/json", "object_type": "gene"}, allow_status=(400, 404),
                                   purpose="alias resolution")
        if resp.status >= 400 or not isinstance(resp.data, list):
            return []
        return sorted({row["id"] for row in resp.data if str(row.get("id", "")).startswith("ENSG")})

    async def vep_region(self, chrom: str, pos: int, end: int, alt: str, tracker: Tracker) -> List[Dict[str, Any]]:
        region = f"{chrom}:{pos}-{end}:1/{alt}"
        resp = await self.http.get("ensembl", f"{BASE}/vep/human/region/{quote(region, safe=':/-')}", tracker=tracker,
                                   params=VEP_PARAMS, timeout=40, purpose="VEP consequence (region)")
        return resp.data if isinstance(resp.data, list) else []

    async def vep_hgvs(self, hgvs: str, tracker: Tracker) -> List[Dict[str, Any]]:
        params = dict(VEP_PARAMS)
        if hgvs.startswith(("NM_", "NR_", "XM_", "NP_")):
            params["refseq"] = "1"
        resp = await self.http.get("ensembl", f"{BASE}/vep/human/hgvs/{quote(hgvs, safe=':.>_()')}", tracker=tracker,
                                   params=params, timeout=40, allow_status=(400,), purpose="VEP consequence (HGVS)")
        if resp.status == 400:
            message = (resp.data or {}).get("error", "VEP could not parse the HGVS expression") if isinstance(resp.data, dict) else "VEP rejected the input"
            raise SourceError("ensembl", "http", message, 400)
        return resp.data if isinstance(resp.data, list) else []

    async def vep_id(self, rsid: str, tracker: Tracker) -> List[Dict[str, Any]]:
        resp = await self.http.get("ensembl", f"{BASE}/vep/human/id/{quote(rsid)}", tracker=tracker, params=VEP_PARAMS,
                                   timeout=40, allow_status=(400,), purpose="VEP consequence (rsID)")
        if resp.status == 400:
            raise SourceError("ensembl", "http", (resp.data or {}).get("error", "rsID not recognised") if isinstance(resp.data, dict) else "rsID not recognised", 400)
        return resp.data if isinstance(resp.data, list) else []

    async def variant_recoder(self, expression: str, tracker: Tracker) -> List[str]:
        """Best-effort conversion of gene-level protein HGVS to genomic HGVS (often slow)."""
        resp = await self.http.get("ensembl", f"{BASE}/variant_recoder/human/{quote(expression, safe=':.')}", tracker=tracker,
                                   params={"content-type": "application/json", "fields": "hgvsg"}, timeout=25, retries=0,
                                   allow_status=(400,), purpose="variant recoder (protein → genomic)")
        if resp.status == 400 or not isinstance(resp.data, list):
            return []
        found: List[str] = []
        for item in resp.data:
            for allele in (item.values() if isinstance(item, dict) else []):
                if isinstance(allele, dict):
                    for g in allele.get("hgvsg", []) or []:
                        if g.startswith("NC_") and g not in found:
                            found.append(g)
        return found


def summarize_vep(entry: Dict[str, Any], prefer_allele: Optional[str] = None, prefer_gene: Optional[str] = None) -> Dict[str, Any]:
    """Reduce one VEP result to the fields PathwayGPS displays, choosing a primary transcript.

    Primary transcript preference: MANE Select → Ensembl canonical → first protein-coding
    consequence. Filtered to ``prefer_gene`` when provided. All alleles are kept separately so
    multi-allelic rsIDs are never collapsed.
    """
    consequences = []
    for tc in entry.get("transcript_consequences", []) or []:
        consequences.append({
            "transcript_id": tc.get("transcript_id"),
            "gene_symbol": tc.get("gene_symbol"),
            "gene_id": tc.get("gene_id"),
            "allele": tc.get("variant_allele"),
            "consequence_terms": tc.get("consequence_terms", []),
            "impact": tc.get("impact"),
            "biotype": tc.get("biotype"),
            "hgvsc": tc.get("hgvsc"),
            "hgvsp": tc.get("hgvsp"),
            "protein_start": tc.get("protein_start"),
            "protein_end": tc.get("protein_end"),
            "amino_acids": tc.get("amino_acids"),
            "codons": tc.get("codons"),
            "exon": tc.get("exon"),
            "mane_select": tc.get("mane_select"),
            "canonical": bool(tc.get("canonical")),
            "swissprot": [s.split(".")[0] for s in tc.get("swissprot", []) or []],
            "sift_prediction": tc.get("sift_prediction"),
            "sift_score": tc.get("sift_score"),
            "polyphen_prediction": tc.get("polyphen_prediction"),
            "polyphen_score": tc.get("polyphen_score"),
            "domains": sorted({f"{d.get('db')}:{d.get('name')}" for d in tc.get("domains", []) or [] if d.get("db") in DOMAIN_DBS})[:12],
        })

    def rank(tc: Dict[str, Any]) -> tuple:
        return (
            0 if prefer_gene and tc["gene_symbol"] and tc["gene_symbol"].upper() == prefer_gene.upper() else 1,
            0 if prefer_allele and tc["allele"] == prefer_allele else 1,
            0 if tc["mane_select"] else 1,
            0 if tc["canonical"] else 1,
            0 if tc["biotype"] == "protein_coding" else 1,
        )

    ordered = sorted(consequences, key=rank)
    alleles: Dict[str, Dict[str, Any]] = {}
    for tc in ordered:
        if tc["allele"] and tc["allele"] not in alleles and (not prefer_gene or (tc["gene_symbol"] or "").upper() == prefer_gene.upper()):
            alleles[tc["allele"]] = tc

    colocated = entry.get("colocated_variants", []) or []
    rsids = sorted({c.get("id") for c in colocated if str(c.get("id", "")).startswith("rs")})
    clin_sig = sorted({s for c in colocated for s in (c.get("clin_sig") or [])})
    pubmed = []
    for c in colocated:
        for p in c.get("pubmed", []) or []:
            if str(p) not in pubmed:
                pubmed.append(str(p))
    cosmic = sorted({c.get("id") for c in colocated if str(c.get("id", "")).startswith("COSV")})
    return {
        "input": entry.get("input") or entry.get("id"),
        "assembly": entry.get("assembly_name"),
        "chromosome": entry.get("seq_region_name"),
        "start": entry.get("start"),
        "end": entry.get("end"),
        "allele_string": entry.get("allele_string"),
        "variant_class": entry.get("variant_class"),
        "most_severe_consequence": entry.get("most_severe_consequence"),
        "primary": ordered[0] if ordered else None,
        "per_allele_primary": alleles,
        "transcript_count": len(consequences),
        "colocated": {"rsids": rsids, "clin_sig": clin_sig, "pubmed": pubmed[:200], "cosmic": cosmic[:10]},
    }
