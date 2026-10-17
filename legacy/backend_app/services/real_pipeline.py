from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.clinvar_service import ClinVarService
from app.services.ensembl_service import EnsemblService
from app.services.reactome_service import ReactomeService
from app.services.uniprot_service import UniProtService
from app.services.variant_resolver import VariantResolver
from etl.normalize import normalize_graph

GENE_LIST = [
    "EGFR",
    "KRAS",
    "BRAF",
    "MAP2K1",
    "MAPK1",
    "AKT1",
    "PTEN",
]

VARIANT_CATALOG = {
    "EGFR": ["L858R", "T790M"],
    "BRAF": ["V600E"],
    "KRAS": ["G12D", "G12C"],
    "PTEN": ["R130Q"],
}


class RealDataPipeline:
    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = (repo_root or Path(__file__).resolve().parents[3]).resolve()
        self.data_root = self.repo_root / "data"
        self.uniprot = UniProtService(self.repo_root)
        self.ensembl = EnsemblService(self.repo_root)
        self.reactome = ReactomeService(self.repo_root)
        self.clinvar = ClinVarService(self.repo_root)
        self.variant_resolver = VariantResolver()

    def resolve_gene_record(self, gene_symbol: str) -> dict[str, Any] | None:
        try:
            uniprot_record = self.uniprot.fetch_gene(gene_symbol)
            ensembl_record = self.ensembl.fetch_gene(gene_symbol)
        except Exception:
            return None
        return {
            "gene_symbol": gene_symbol,
            "canonical_id": f"gene:{ensembl_record.get('gene_id') or gene_symbol}",
            "protein_accession": uniprot_record.get("source_id"),
            "protein_name": uniprot_record.get("protein_name"),
            "genome_build": "GRCh38",
            "source": "official",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }

    def resolve_pathways_for_gene(self, gene_symbol: str) -> list[dict[str, Any]]:
        return self.reactome.filter_for_gene(gene_symbol)

    def build_source_metadata(self) -> dict[str, Any]:
        downloaded_at = datetime.now(timezone.utc).isoformat()
        return {
            "reactome": {
                "source_url": "https://reactome.org/ContentService/data/pathways/top/9606",
                "version": "unknown",
                "downloaded_at": downloaded_at,
                "license": "Reactome terms of use",
            },
            "uniprot": {
                "source_url": "https://rest.uniprot.org/",
                "version": "unknown",
                "downloaded_at": downloaded_at,
                "license": "UniProt terms",
            },
            "ensembl": {
                "source_url": "https://rest.ensembl.org/",
                "version": "unknown",
                "downloaded_at": downloaded_at,
                "license": "Ensembl terms",
            },
            "clinvar": {
                "source_url": "https://www.ncbi.nlm.nih.gov/clinvar/",
                "version": "unknown",
                "downloaded_at": downloaded_at,
                "license": "NCBI terms",
            },
        }

    def resolve_variant_record(self, variant_name: str) -> dict[str, Any] | None:
        parsed = self.variant_resolver.normalize(variant_name)
        gene_symbol = parsed.get("gene_symbol")
        if not gene_symbol:
            return None
        protein_change = parsed.get("protein_change")
        query_variants = []
        if protein_change:
            query_variants.append(protein_change)
            query_variants.append(protein_change.replace("p.", "", 1))
            if not protein_change.lower().startswith("p."):
                query_variants.append(f"p.{protein_change}")
        query_variants.append(variant_name)

        last_error = None
        for query_value in query_variants:
            if not query_value:
                continue
            try:
                variant_payload = self.clinvar.fetch_variant(gene_symbol, query_value)
            except Exception as exc:  # pragma: no cover - network guard
                last_error = exc
                continue
            records = variant_payload.get("variant_records") or []
            if not records:
                continue

            target_change = self.variant_resolver.canonical_protein_change(protein_change)
            selected = None
            for record in records:
                title = record.get("title") or ""
                inferred_change = self.variant_resolver.canonical_protein_change(title)
                if target_change and inferred_change == target_change:
                    selected = record
                    break
                if protein_change and protein_change.lower() in title.lower():
                    selected = record
                    break
                if query_value.lower() in title.lower():
                    selected = record
                    break
            if selected is None:
                selected = records[0]

            title = selected.get("title") or ""
            inferred_change = self.variant_resolver.canonical_protein_change(title) or protein_change
            return {
                "gene_symbol": gene_symbol,
                "variant_id": selected.get("accession") or f"{gene_symbol}_{inferred_change or 'unknown'}",
                "protein_change": inferred_change or protein_change or "unknown",
                "source_database": "ClinVar",
                "source_id": selected.get("uid") or selected.get("accession"),
                "clinical_significance": selected.get("clinical_significance") or self.clinvar.extract_clinical_significance(selected),
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "title": title,
            }

        if last_error is not None:
            raise last_error
        return None

    def run_quick(self) -> dict[str, Any]:
        genes = []
        relationships = []
        variants = []
        seen_variants: set[str] = set()

        for symbol in GENE_LIST:
            gene_record = self.resolve_gene_record(symbol)
            if gene_record is None:
                continue
            genes.append(gene_record)
            protein_accession = gene_record.get("protein_accession")
            if protein_accession:
                relationships.append({
                    "source": symbol,
                    "target": protein_accession,
                    "relationship": "ENCODES",
                    "source_database": "UniProt",
                    "source_id": protein_accession,
                })

            for pathway in self.resolve_pathways_for_gene(symbol)[:3]:
                pathway_id = pathway.get("stId")
                if not pathway_id or not protein_accession:
                    continue
                relationships.append({
                    "source": protein_accession,
                    "target": pathway_id,
                    "relationship": "PARTICIPATES_IN",
                    "source_database": "Reactome",
                    "source_id": pathway_id,
                    "evidence": "Curated pathway relationship",
                })

            for variant_code in VARIANT_CATALOG.get(symbol, []):
                try:
                    variant_record = self.resolve_variant_record(f"{symbol} {variant_code}")
                except Exception:
                    continue
                if not variant_record:
                    continue
                key = f"{variant_record.get('gene_symbol')}:{variant_record.get('protein_change')}"
                if key in seen_variants:
                    continue
                seen_variants.add(key)
                variants.append(variant_record)

        data = {
            "genes": genes,
            "variants": variants,
            "relationships": relationships,
            "sources": self.build_source_metadata(),
        }
        data, report = normalize_graph(data)

        self.data_root.mkdir(parents=True, exist_ok=True)
        (self.data_root / "canonical").mkdir(exist_ok=True)
        (self.data_root / "metadata").mkdir(exist_ok=True)
        (self.data_root / "metadata" / "reports").mkdir(exist_ok=True)
        (self.data_root / "canonical" / "quick_graph.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        (self.data_root / "metadata" / "reports" / "quick_mode.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return data
