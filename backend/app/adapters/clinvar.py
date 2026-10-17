"""ClinVar adapter (NCBI E-utilities: esearch, esummary, efetch VCV XML)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from app.core.http import HttpClient, Tracker
from app.domain.notation import ProteinChange, protein_change_from_title

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
VCV_URL = "https://www.ncbi.nlm.nih.gov/clinvar/variation/{id}/"
SCV_URL = "https://www.ncbi.nlm.nih.gov/clinvar/?term={acc}"

# ClinVar review status → star rating (ClinVar documentation)
REVIEW_STARS = {
    "practice guideline": 4,
    "reviewed by expert panel": 3,
    "criteria provided, multiple submitters, no conflicts": 2,
    "criteria provided, conflicting classifications": 1,
    "criteria provided, conflicting interpretations": 1,
    "criteria provided, single submitter": 1,
    "criteria provided, multiple submitters": 2,
    "no assertion criteria provided": 0,
    "no classification provided": 0,
    "no classification for the individual variant": 0,
}

GERMLINE_GROUPS = {
    "pathogenic": "pathogenic",
    "likely pathogenic": "pathogenic",
    "pathogenic/likely pathogenic": "pathogenic",
    "uncertain significance": "uncertain",
    "likely benign": "benign",
    "benign": "benign",
    "benign/likely benign": "benign",
}


class ClinVarAdapter:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    async def search(self, term: str, tracker: Tracker, retmax: int = 20) -> List[str]:
        resp = await self.http.get("clinvar", f"{EUTILS}/esearch.fcgi", tracker=tracker, purpose="search variant records",
                                   params={"db": "clinvar", "term": term, "retmode": "json", "retmax": retmax})
        return list((resp.data or {}).get("esearchresult", {}).get("idlist", []))

    async def search_protein_change(self, gene: str, change: ProteinChange, tracker: Tracker) -> List[str]:
        term = f'{gene}[gene] AND ("{change.short}"[varname] OR "p.{change.long}"[varname])'
        return await self.search(term, tracker)

    async def summaries(self, ids: List[str], tracker: Tracker) -> List[Dict[str, Any]]:
        if not ids:
            return []
        resp = await self.http.get("clinvar", f"{EUTILS}/esummary.fcgi", tracker=tracker, purpose="variant summaries",
                                   params={"db": "clinvar", "id": ",".join(ids[:50]), "retmode": "json"})
        result = (resp.data or {}).get("result", {})
        records = []
        for uid in result.get("uids", []):
            raw = result.get(uid)
            if isinstance(raw, dict) and not raw.get("error"):
                records.append(self.normalize_summary(raw, resp.fetched_at))
        return records

    @staticmethod
    def _classification(block: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(block, dict) or not block.get("description"):
            return None
        traits = []
        for trait in block.get("trait_set", []) or []:
            xrefs = [{"db": x.get("db_source"), "id": x.get("db_id")} for x in trait.get("trait_xrefs", []) if x.get("db_id")]
            traits.append({"name": trait.get("trait_name"), "xrefs": xrefs})
        review = block.get("review_status") or ""
        return {
            "description": block.get("description"),
            "review_status": review,
            "stars": REVIEW_STARS.get(review.lower(), None),
            "last_evaluated": (block.get("last_evaluated") or "").split(" ")[0] or None,
            "traits": traits,
        }

    def normalize_summary(self, raw: Dict[str, Any], fetched_at: str) -> Dict[str, Any]:
        vset = (raw.get("variation_set") or [{}])[0]
        xrefs = vset.get("variation_xrefs", []) or []
        rsid = next((f"rs{x['db_id']}" for x in xrefs if x.get("db_source") == "dbSNP"), None)
        uniprot_var = next((x["db_id"] for x in xrefs if x.get("db_source") == "UniProtKB"), None)
        clingen = next((x["db_id"] for x in xrefs if x.get("db_source") == "ClinGen"), None)
        loc38 = next((loc for loc in vset.get("variation_loc", []) or [] if loc.get("assembly_name") == "GRCh38"), None)
        genes = [g.get("symbol") for g in raw.get("genes", []) or [] if g.get("symbol")]
        title = raw.get("title") or ""
        change = protein_change_from_title(title)
        protein_changes = [p.strip() for p in (raw.get("protein_change") or "").split(",") if p.strip()]
        uid = str(raw.get("uid"))
        return {
            "variation_id": uid,
            "accession": raw.get("accession"),
            "accession_version": raw.get("accession_version"),
            "title": title,
            "url": VCV_URL.format(id=uid),
            "obj_type": raw.get("obj_type"),
            "genes": genes,
            "protein_change": change.to_dict() if change else None,
            "protein_change_aliases": protein_changes,
            "cdna_change": vset.get("cdna_change"),
            "canonical_spdi": vset.get("canonical_spdi"),
            "grch38": {"chr": loc38.get("chr"), "start": loc38.get("start"), "stop": loc38.get("stop"), "band": loc38.get("band")} if loc38 else None,
            "rsid": rsid,
            "uniprot_variant": uniprot_var,
            "clingen_allele": clingen,
            "molecular_consequences": raw.get("molecular_consequence_list", []) or [],
            "germline": self._classification(raw.get("germline_classification")),
            "somatic_clinical_impact": self._classification(raw.get("clinical_impact_classification")),
            "oncogenicity": self._classification(raw.get("oncogenicity_classification")),
            "scv_accessions": (raw.get("supporting_submissions") or {}).get("scv", []),
            "rcv_accessions": (raw.get("supporting_submissions") or {}).get("rcv", []),
            "retrieved_at": fetched_at,
        }

    async def submissions(self, variation_id: str, tracker: Tracker) -> Dict[str, Any]:
        """Fetch per-submission (SCV) records from the VCV XML."""
        resp = await self.http.get("clinvar", f"{EUTILS}/efetch.fcgi", tracker=tracker, expect="text", purpose="submissions (SCV)",
                                   params={"db": "clinvar", "id": variation_id, "rettype": "vcv", "is_variationid": "true"})
        return {"submissions": self.parse_vcv_xml(resp.data or ""), "retrieved_at": resp.fetched_at}

    @staticmethod
    def parse_vcv_xml(xml_text: str) -> List[Dict[str, Any]]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []
        out: List[Dict[str, Any]] = []
        for ca in root.iter("ClinicalAssertion"):
            acc = ca.find("ClinVarAccession")
            cls = ca.find("Classification")
            if acc is None:
                continue
            kind, value, extra = None, None, {}
            if cls is not None:
                for tag, label in (("GermlineClassification", "germline"), ("SomaticClinicalImpact", "somatic_clinical_impact"), ("OncogenicityClassification", "oncogenicity")):
                    node = cls.find(tag)
                    if node is not None and (node.text or "").strip():
                        kind, value = label, node.text.strip()
                        extra = {k: v for k, v in node.attrib.items()}
                        break
            traits = []
            for trait in ca.findall("./TraitSet/Trait"):
                name = trait.find("./Name/ElementValue")
                if name is not None and name.text:
                    traits.append(name.text)
            origin = ca.find(".//Origin")
            method = ca.find(".//ObservedIn/Method/MethodType")
            pmids = []
            for cid in ca.iter("ID"):
                if cid.get("Source") == "PubMed" and cid.text and cid.text.strip().isdigit() and cid.text.strip() not in pmids:
                    pmids.append(cid.text.strip())
            comment = cls.find("Comment") if cls is not None else None
            review = cls.find("ReviewStatus") if cls is not None else None
            accession = acc.get("Accession")
            out.append({
                "scv": accession,
                "url": SCV_URL.format(acc=accession),
                "submitter": acc.get("SubmitterName"),
                "submitter_id": acc.get("OrgID"),
                "classification_type": kind,
                "classification": value,
                "therapeutic_context": extra or None,
                "review_status": review.text.strip() if review is not None and review.text else None,
                "date_last_evaluated": cls.get("DateLastEvaluated") if cls is not None else None,
                "origin": origin.text.strip() if origin is not None and origin.text else None,
                "method": method.text.strip() if method is not None and method.text else None,
                "conditions": traits,
                "pmids": pmids[:25],
                "comment": (comment.text or "").strip()[:600] if comment is not None else None,
                "contributes_to_aggregate": ca.get("ContributesToAggregateClassification") == "true",
            })
        return out


def germline_group(classification: Optional[str]) -> Optional[str]:
    if not classification:
        return None
    return GERMLINE_GROUPS.get(classification.strip().lower(), "other")
