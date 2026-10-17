from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


class EnsemblService:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or Path(__file__).resolve().parents[3]).resolve()

    def fetch_gene(self, gene_symbol: str) -> dict[str, Any]:
        if os.getenv("PATHWAYGPS_OFFLINE", "").lower() in {"1", "true", "yes"}:
            path = self.base_dir / "data" / "raw" / "ensembl" / f"{gene_symbol.upper()}.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            canonical = self.base_dir / "data" / "canonical" / "quick_graph.json"
            if canonical.exists():
                payload = json.loads(canonical.read_text(encoding="utf-8"))
                record = next((g for g in payload.get("genes", []) if g.get("gene_symbol", "").upper() == gene_symbol.upper()), None)
                if record:
                    return record
            raise ValueError(f"No cached Ensembl record for {gene_symbol}")
        url = f"https://rest.ensembl.org/lookup/symbol/homo_sapiens/{gene_symbol}?expand=1"
        response = httpx.get(url, headers={"Accept": "application/json"}, timeout=30)
        if response.status_code >= 400:
            raise ValueError(f"Ensembl lookup failed for {gene_symbol}: HTTP {response.status_code}")
        payload = response.json()
        return {
            "source_database": "Ensembl",
            "source_id": payload.get("id"),
            "gene_symbol": payload.get("display_name") or gene_symbol,
            "gene_id": payload.get("id"),
            "biotype": payload.get("biotype"),
            "species": "Homo sapiens",
            "genome_build": "GRCh38",
            "ensembl_release": payload.get("assembly_name") or "latest",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "transcripts": payload.get("Transcript", [])[:3],
        }

    def cache_gene(self, gene_symbol: str) -> dict[str, Any]:
        data_dir = self.base_dir / "data" / "raw" / "ensembl"
        data_dir.mkdir(parents=True, exist_ok=True)
        payload = self.fetch_gene(gene_symbol)
        path = data_dir / f"{gene_symbol.upper()}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
