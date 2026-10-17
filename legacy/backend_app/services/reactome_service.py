from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from app.services.uniprot_service import UniProtService


class ReactomeService:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or Path(__file__).resolve().parents[3]).resolve()

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "PathwayGPS/1.0",
        }

    def fetch_pathways(self) -> list[dict[str, Any]]:
        if os.getenv("PATHWAYGPS_OFFLINE", "").lower() in {"1", "true", "yes"}:
            path = self.base_dir / "data" / "raw" / "reactome" / "top_human_pathways.json"
            if not path.exists():
                return []
            return json.loads(path.read_text(encoding="utf-8"))
        url = "https://reactome.org/ContentService/data/pathways/top/9606"
        response = httpx.get(url, headers=self._headers(), timeout=30)
        response.raise_for_status()
        results = response.json()
        return [
            {
                "dbId": item.get("dbId"),
                "displayName": item.get("displayName"),
                "stId": item.get("stId"),
                "name": item.get("name", [item.get("displayName")]),
                "speciesName": item.get("speciesName"),
                "releaseDate": item.get("releaseDate"),
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
            }
            for item in results
        ]

    def fetch_pathways_for_protein(self, accession: str | None) -> list[dict[str, Any]]:
        if not accession:
            return []
        accession = str(accession).strip()
        if not accession:
            return []
        url = f"https://reactome.org/ContentService/data/mapping/UniProt/{accession}/pathways"
        response = httpx.get(url, params={"species": "9606"}, headers=self._headers(), timeout=30)
        response.raise_for_status()
        return [
            {
                "stId": item.get("stId"),
                "displayName": item.get("displayName"),
                "url": f"https://reactome.org/PathwayBrowser/#/{item.get('stId')}",
                "releaseDate": item.get("releaseDate"),
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
            }
            for item in response.json()
            if item.get("stId")
        ]

    def filter_for_gene(self, gene_symbol: str) -> list[dict[str, Any]]:
        """Return pathways supported by a cached gene/protein record.

        Reactome does not expose a reliable gene-symbol endpoint.  Prefer the
        local UniProt mapping (and the canonical ETL graph) rather than
        inventing memberships; network lookup is intentionally not attempted
        here.
        """
        symbol = (gene_symbol or "").strip().upper()
        if not symbol:
            return []
        try:
            record = UniProtService(self.base_dir).fetch_gene(symbol)
            accession = (record or {}).get("source_id") or (record or {}).get("primaryAccession")
            if accession:
                return self.fetch_pathways_for_protein(str(accession))
        except Exception:
            pass
        candidates = [
            self.base_dir / "data" / "raw" / "reactome" / f"{symbol}.json",
            self.base_dir / "data" / "raw" / "reactome" / f"{symbol.lower()}.json",
        ]
        canonical = self.base_dir / "data" / "canonical" / "quick_graph.json"
        if canonical.exists():
            try:
                payload = json.loads(canonical.read_text(encoding="utf-8"))
                gene = next((g for g in payload.get("genes", []) if str(g.get("gene_symbol", "")).upper() == symbol), None)
                accession = gene.get("protein_accession") if gene else None
                if accession:
                    memberships = [
                        rel for rel in payload.get("relationships", [])
                        if rel.get("source") == accession and rel.get("relationship") == "PARTICIPATES_IN"
                    ]
                    return [self._normalize_pathway_entry({
                        "stId": rel.get("source_id") or rel.get("target"),
                        "displayName": rel.get("displayName") or rel.get("source_id") or rel.get("target"),
                    }) for rel in memberships if rel.get("source_id") or rel.get("target")]
            except (OSError, ValueError, TypeError):
                pass
        for path in candidates:
            if path.exists():
                try:
                    return self._extract_pathway_collection(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, ValueError, TypeError):
                    return []
        return []

    def fetch_reactions_for_pathway(self, st_id: str | None) -> list[dict[str, Any]]:
        if not st_id:
            return []
        st_id = str(st_id).strip()
        if not st_id:
            return []

        url = f"https://reactome.org/ContentService/data/pathway/{st_id}/containedEvents"
        try:
            response = httpx.get(url, headers=self._headers(), timeout=20)
            if response.status_code == 404:
                return []
            response.raise_for_status()
            results = response.json()
        except httpx.HTTPError:
            return []
        events = results if isinstance(results, list) else results.get("containedEvents", [])
        valid_events = []
        for event in events:
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("className") or event.get("type") or "").strip()
            if event_type not in {"Reaction", "BlackBoxEvent", "FailedReaction"}:
                continue
            event_id = event.get("stId") or event.get("identifier")
            if event_id:
                valid_events.append({
                    "stId": event_id,
                    "displayName": event.get("displayName") or "Reaction",
                    "className": event_type,
                    "url": f"https://reactome.org/PathwayBrowser/#/{st_id}&SEL={event_id}",
                    "downloaded_at": datetime.now(timezone.utc).isoformat(),
                })
        return valid_events[:4]

    @staticmethod
    def _extract_pathway_collection(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [ReactomeService._normalize_pathway_entry(item) for item in payload if item]
        if not isinstance(payload, dict):
            return []
        candidates = []
        for key in ("pathways", "results", "entries", "entities"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates.extend(value)
        if not candidates:
            if payload.get("stId") or payload.get("displayName"):
                return [ReactomeService._normalize_pathway_entry(payload)]
            return []
        normalized: list[dict[str, Any]] = []
        for item in candidates:
            normalized_item = ReactomeService._normalize_pathway_entry(item)
            if normalized_item:
                normalized.append(normalized_item)
        return normalized

    @staticmethod
    def _normalize_pathway_entry(item: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        st_id = item.get("stId") or item.get("identifier")
        if not st_id:
            return None
        display_name = item.get("displayName") or item.get("name") or "Pathway"
        if isinstance(display_name, list) and display_name:
            display_name = display_name[0]
        return {
            "dbId": item.get("dbId"),
            "displayName": str(display_name),
            "stId": str(st_id),
            "name": item.get("name") or [str(display_name)],
            "speciesName": item.get("speciesName"),
            "source_database": "Reactome",
            "source_id": str(st_id),
            "source_url": "https://reactome.org/ContentService/data",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }

    def cache_pathways(self) -> list[dict[str, Any]]:
        data_dir = self.base_dir / "data" / "raw" / "reactome"
        data_dir.mkdir(parents=True, exist_ok=True)
        payload = self.fetch_pathways()
        path = data_dir / "top_human_pathways.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
