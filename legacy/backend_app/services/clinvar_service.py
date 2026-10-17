from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


class ClinVarService:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or Path(__file__).resolve().parents[3]).resolve()

    @staticmethod
    def extract_clinical_significance(record: dict[str, Any]) -> str:
        for key in ("germline_classification", "clinical_impact_classification", "oncogenicity_classification"):
            classification = record.get(key) or {}
            if isinstance(classification, dict):
                description = classification.get("description")
                if description:
                    return str(description)
        return "not_reported"

    def fetch_variant(self, gene_symbol: str, variant_code: str | None = None) -> dict[str, Any]:
        if os.getenv("PATHWAYGPS_OFFLINE", "").lower() in {"1", "true", "yes"}:
            path = self.base_dir / "data" / "raw" / "clinvar" / f"{gene_symbol.upper()}_{(variant_code or 'all').replace(':', '_')}.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            return {"gene_symbol": gene_symbol, "source_database": "ClinVar", "variant_records": [], "variant_ids": []}
        term = f"{gene_symbol}[Gene]"
        if variant_code:
            normalized = variant_code.strip()
            protein_change = re.search(r"(?:p\.)?([A-Za-z]{1,3}\d+[A-Za-z]{1,3})", normalized)
            if protein_change:
                term = f"{gene_symbol}[Gene] AND {protein_change.group(1)}[All Fields]"
            else:
                term = f"{gene_symbol}[Gene] AND {normalized}[All Fields]"
        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        params = {"db": "clinvar", "term": term, "retmode": "json", "retmax": 10}
        response = httpx.get(url, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        ids = payload.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return {"gene_symbol": gene_symbol, "source_database": "ClinVar", "variants": [], "variant_records": [], "variant_ids": [], "downloaded_at": datetime.now(timezone.utc).isoformat()}

        summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        summary_response = httpx.get(summary_url, params={"db": "clinvar", "id": ",".join(ids), "retmode": "json"}, timeout=30)
        summary_response.raise_for_status()
        summary_payload = summary_response.json().get("result", {})

        variant_records: list[dict[str, Any]] = []
        for uid in ids:
            record = summary_payload.get(uid, {})
            if not record:
                continue
            title = record.get("title") or ""
            variant_records.append(
                {
                    "uid": uid,
                    "accession": record.get("accession"),
                    "title": title,
                    "obj_type": record.get("obj_type"),
                    "clinical_significance": self.extract_clinical_significance(record),
                    "variation_set": record.get("variation_set", []),
                    "downloaded_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        return {
            "gene_symbol": gene_symbol,
            "source_database": "ClinVar",
            "variant_ids": ids,
            "variant_records": variant_records,
            "raw_xml_snippet": "",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "confidence": "source_record",
        }

    def cache_variant(self, gene_symbol: str, variant_code: str | None = None) -> dict[str, Any]:
        data_dir = self.base_dir / "data" / "raw" / "clinvar"
        data_dir.mkdir(parents=True, exist_ok=True)
        payload = self.fetch_variant(gene_symbol, variant_code)
        path = data_dir / f"{gene_symbol.upper()}_{(variant_code or 'all').replace(':', '_')}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
