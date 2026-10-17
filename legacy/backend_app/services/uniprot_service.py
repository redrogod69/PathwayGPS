from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


class UniProtService:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or Path(__file__).resolve().parents[3]).resolve()

    def fetch_gene(self, gene_symbol: str) -> dict[str, Any]:
        if os.getenv("PATHWAYGPS_OFFLINE", "").lower() in {"1", "true", "yes"}:
            path = self.base_dir / "data" / "raw" / "uniprot" / f"{gene_symbol.upper()}.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            canonical = self.base_dir / "data" / "canonical" / "quick_graph.json"
            if canonical.exists():
                payload = json.loads(canonical.read_text(encoding="utf-8"))
                record = next((g for g in payload.get("genes", []) if g.get("gene_symbol", "").upper() == gene_symbol.upper()), None)
                if record:
                    return {"source_id": record.get("protein_accession"), "gene_symbol": gene_symbol, "protein_name": record.get("protein_name")}
            raise ValueError(f"No cached UniProt record for {gene_symbol}")
        query = f"gene:{gene_symbol} AND organism_id:9606"
        url = "https://rest.uniprot.org/uniprotkb/search"
        params = {
            "query": query,
            "format": "json",
            "fields": "accession,gene_names,protein_name,sequence,length,reviewed,organism_name,organism_id",
        }
        response = httpx.get(url, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        hits = payload.get("results", [])
        if not hits:
            raise ValueError(f"No UniProt record found for {gene_symbol}")
        entry = hits[0]
        gene_names = entry.get("genes", [])
        gene_name = gene_names[0].get("geneName", {}).get("value") if gene_names else gene_symbol
        return {
            "source_database": "UniProt",
            "source_id": entry.get("primaryAccession"),
            "gene_symbol": gene_name,
            "protein_name": entry.get("proteinDescription", {}).get("recommendedName", {}).get("fullName", {}).get("value"),
            "reviewed": entry.get("entryType", "").lower().startswith("uniprotkb reviewed"),
            "protein_length": entry.get("sequence", {}).get("length"),
            "sequence": entry.get("sequence", {}).get("value"),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "species": "Homo sapiens",
        }

    def cache_gene(self, gene_symbol: str) -> dict[str, Any]:
        data_dir = self.base_dir / "data" / "raw" / "uniprot"
        data_dir.mkdir(parents=True, exist_ok=True)
        payload = self.fetch_gene(gene_symbol)
        path = data_dir / f"{gene_symbol.upper()}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
