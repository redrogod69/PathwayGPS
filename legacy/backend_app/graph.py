from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.clinvar_service import ClinVarService
from app.services.ensembl_service import EnsemblService
from app.services.reactome_service import ReactomeService
from app.services.uniprot_service import UniProtService
from app.services.variant_resolver import VariantResolver
from app.graph_backend import GraphBackend


class GraphService:
    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
        self.clinvar = ClinVarService(self.repo_root)
        self.ensembl = EnsemblService(self.repo_root)
        self.uniprot = UniProtService(self.repo_root)
        self.reactome = ReactomeService(self.repo_root)
        self.variant_resolver = VariantResolver()

        self.graph_backend = GraphBackend(self.repo_root)
        self._graph_cache: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _source_metadata(self) -> dict[str, Any]:
        retrieved_at = self._now()
        return {
            "clinvar": {
                "source_url": "https://www.ncbi.nlm.nih.gov/clinvar/",
                "version": "unknown",
                "retrieved_at": retrieved_at,
                "downloaded_at": retrieved_at,
                "license": "NCBI terms",
            },
            "ensembl": {
                "source_url": "https://rest.ensembl.org/",
                "version": "unknown",
                "retrieved_at": retrieved_at,
                "downloaded_at": retrieved_at,
                "license": "Ensembl terms",
            },
            "uniprot": {
                "source_url": "https://rest.uniprot.org/",
                "version": "unknown",
                "retrieved_at": retrieved_at,
                "downloaded_at": retrieved_at,
                "license": "UniProt terms",
            },
            "reactome": {
                "source_url": "https://reactome.org/ContentService/data",
                "version": "unknown",
                "retrieved_at": retrieved_at,
                "downloaded_at": retrieved_at,
                "license": "Reactome terms of use",
            },
        }

    @staticmethod
    def _provenance(
        source_database: str,
        source_id: str | None,
        source_url: str | None,
        relationship: str,
        evidence_summary: str,
        classification: str = "database_fact",
        retrieved_at: str | None = None,
    ) -> dict[str, Any]:
        provenance = {
            "source_database": source_database,
            "source_id": str(source_id) if source_id is not None else "",
            "source_url": source_url or "",
            "relationship": relationship,
            "classification": classification,
            "evidence_summary": evidence_summary,
            "retrieved_at": retrieved_at or GraphService._now(),
        }
        provenance["downloaded_at"] = provenance["retrieved_at"]
        return provenance

    @staticmethod
    def _build_node(node_id: str, name: str, node_type: str, provenance: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": node_id,
            "name": name,
            "type": node_type,
            "source_database": provenance["source_database"],
            "source_id": provenance["source_id"],
            "source_url": provenance["source_url"],
            "classification": provenance["classification"],
            "evidence_summary": provenance["evidence_summary"],
            "retrieved_at": provenance["retrieved_at"],
            "provenance": provenance,
        }

    @staticmethod
    def _build_edge(source: str, target: str, relationship: str, provenance: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": f"{source}->{relationship}->{target}",
            "source": source,
            "target": target,
            "relationship": relationship,
            "source_database": provenance["source_database"],
            "source_id": provenance["source_id"],
            "source_url": provenance["source_url"],
            "classification": provenance["classification"],
            "evidence_summary": provenance["evidence_summary"],
            "retrieved_at": provenance["retrieved_at"],
            "provenance": provenance,
        }

    def _default_not_resolved(self, query: str, message: str = "not resolved / insufficient source data") -> dict[str, Any]:
        return {
            "query": query,
            "status": "not_resolved",
            "message": message,
            "variant": None,
            "graph": {"nodes": [], "edges": []},
            "paths": [],
            "sources": self._source_metadata(),
            "candidate_drugs": [],
        }

    @staticmethod
    def _pick_record(records: list[dict[str, Any]], query: str, gene_symbol: str, target_change: str | None) -> dict[str, Any] | None:
        query_lower = (query or "").lower()
        for record in records:
            if not isinstance(record, dict):
                continue
            title = str(record.get("title") or "")
            canonical_title = VariantResolver().canonical_protein_change(title)
            if target_change and canonical_title == target_change:
                return record
            if target_change and target_change.lower() in title.lower():
                return record
            if not target_change and gene_symbol and gene_symbol.lower() in title.lower():
                return record
            if not target_change and query_lower and query_lower in title.lower():
                return record
        return None

    def list_variants(self) -> list[str]:
        return self.graph_backend.variants()

    def get_variant(self, variant_name: str) -> dict[str, Any] | None:
        lookup = (variant_name or '').strip()
        if not lookup:
            return None
        normalized = self.variant_resolver.normalize(lookup)
        gene_symbol = (normalized.get('gene_symbol') or '').upper()
        if not gene_symbol:
            return None
        return {'gene_symbol': gene_symbol, 'source_database': 'ClinVar'}

    def get_node_detail(self, node_id: str) -> dict[str, Any] | None:
        for graph in reversed(list(self._graph_cache.values())):
            node = next((n for n in graph.get("nodes", []) if n.get("id") == node_id), None)
            if node:
                return node
        return self.graph_backend.node(node_id)

    def analyze(self, variant_name: str) -> dict[str, Any] | None:
        query = (variant_name or "").strip()
        if not query:
            return self._default_not_resolved(query)

        normalized = self.variant_resolver.normalize(query)
        gene_symbol = (normalized.get("gene_symbol") or "").strip()
        if not gene_symbol:
            return self._default_not_resolved(query)

        try:
            clinvar_response = self.clinvar.fetch_variant(gene_symbol, query)
        except Exception:
            return self._default_not_resolved(query)

        records = clinvar_response.get("variant_records") or []
        if not records:
            return self._default_not_resolved(query)

        target_change = normalized.get("protein_change")
        selected_record = self._pick_record(records, query, gene_symbol, target_change)
        if selected_record is None:
            return self._default_not_resolved(query)

        title = str(selected_record.get("title") or query)
        variant_id = selected_record.get("accession") or selected_record.get("uid") or title
        protein_change = self.variant_resolver.canonical_protein_change(title) or target_change or "unknown"
        variant_data = {
            "gene_symbol": gene_symbol,
            "variant_id": str(variant_id),
            "protein_change": protein_change,
            "source_database": "ClinVar",
            "source_id": str(selected_record.get("uid") or selected_record.get("accession") or variant_id),
            "clinical_significance": selected_record.get("clinical_significance") or "not_reported",
            "retrieved_at": selected_record.get("downloaded_at") or self._now(),
            "title": title,
        }

        try:
            ensembl_record = self.ensembl.fetch_gene(gene_symbol)
            uniprot_record = self.uniprot.fetch_gene(gene_symbol)
        except Exception:
            return self._default_not_resolved(query)

        protein_accession = (uniprot_record or {}).get("source_id") or (uniprot_record or {}).get("primaryAccession") or (uniprot_record or {}).get("accession")
        if not protein_accession:
            return self._default_not_resolved(query)

        try:
            pathways = self.reactome.fetch_pathways_for_protein(protein_accession)
        except Exception:
            pathways = []

        source_metadata = self._source_metadata()
        retrieved_at = self._now()
        variant_provenance = self._provenance(
            "ClinVar",
            variant_data["source_id"],
            source_metadata["clinvar"]["source_url"],
            "VARIANT_OF",
            f"ClinVar record for {gene_symbol} variant {variant_data['protein_change']}",
            retrieved_at=retrieved_at,
        )
        gene_provenance = self._provenance(
            "Ensembl",
            ensembl_record.get("source_id") or gene_symbol,
            source_metadata["ensembl"]["source_url"],
            "GENE_RECORD",
            f"Ensembl gene record for {gene_symbol}",
            retrieved_at=retrieved_at,
        )
        protein_provenance = self._provenance(
            "UniProt",
            protein_accession,
            source_metadata["uniprot"]["source_url"],
            "PROTEIN_RECORD",
            f"UniProt canonical protein record for {gene_symbol}",
            retrieved_at=retrieved_at,
        )

        variant_node = self._build_node(f"variant:{variant_data['variant_id']}", query, "variant", variant_provenance)
        gene_node = self._build_node(f"gene:{gene_symbol}", gene_symbol, "gene", gene_provenance)
        protein_node = self._build_node(f"protein:{protein_accession}", uniprot_record.get("protein_name") or gene_symbol, "protein", protein_provenance)

        nodes = [variant_node, gene_node, protein_node]
        edges = [
            self._build_edge(variant_node["id"], gene_node["id"], "VARIANT_OF", variant_provenance),
            self._build_edge(gene_node["id"], protein_node["id"], "ENCODES", protein_provenance),
        ]

        evidence = [
            {"source_database": "UniProt", "source_id": protein_accession, "relationship": "ENCODES"},
            {"source_database": "ClinVar", "source_id": variant_data["source_id"], "relationship": "VARIANT_OF"},
        ]

        pathway_records = []
        for pathway in pathways:
            st_id = pathway.get("stId") or pathway.get("source_id")
            if not st_id:
                continue
            pathway_provenance = self._provenance(
                "Reactome",
                st_id,
                pathway.get("url") or f"https://reactome.org/PathwayBrowser/#/{st_id}",
                "PARTICIPATES_IN",
                f"Reactome pathway membership for {gene_symbol}",
                retrieved_at=self._now(),
            )
            pathway_node = self._build_node(f"pathway:{st_id}", str(pathway.get("displayName") or pathway.get("name") or st_id), "pathway", pathway_provenance)
            nodes.append(pathway_node)
            edges.append(self._build_edge(protein_node["id"], pathway_node["id"], "PARTICIPATES_IN", pathway_provenance))
            evidence.append({"source_database": "Reactome", "source_id": st_id, "relationship": "PARTICIPATES_IN"})
            pathway_records.append((pathway_node, pathway))

        reaction_entries: list[dict[str, Any]] = []
        for pathway_node, pathway in pathway_records:
            pathway_st_id = pathway.get("stId") or pathway.get("source_id")
            if not pathway_st_id:
                continue
            try:
                reactions = self.reactome.fetch_reactions_for_pathway(pathway_st_id)
            except Exception:
                reactions = []
            for reaction in reactions:
                reaction_id = reaction.get("source_id") or reaction.get("stId")
                if not reaction_id:
                    continue
                reaction_provenance = self._provenance(
                    "Reactome",
                    reaction_id,
                    reaction.get("url") or f"https://reactome.org/PathwayBrowser/#/{reaction_id}",
                    "CONTAINS",
                    f"Contained Reactome event for {pathway_node['name']}",
                    retrieved_at=self._now(),
                )
                reaction_node = self._build_node(f"reaction:{reaction_id}", str(reaction.get("displayName") or reaction.get("name") or reaction_id), "reaction", reaction_provenance)
                nodes.append(reaction_node)
                edges.append(self._build_edge(pathway_node["id"], reaction_node["id"], "CONTAINS", reaction_provenance))
                evidence.append({"source_database": "Reactome", "source_id": reaction_id, "relationship": "CONTAINS"})
                reaction_entries.append(reaction_node)

        deduped_nodes: list[dict[str, Any]] = []
        seen_node_ids: set[str] = set()
        for node in nodes:
            node_id = node["id"]
            if node_id in seen_node_ids:
                continue
            seen_node_ids.add(node_id)
            deduped_nodes.append(node)
        deduped_edges: list[dict[str, Any]] = []
        seen_edges: set[tuple[str, str, str]] = set()
        for edge in edges:
            key = (edge["source"], edge["target"], edge["relationship"])
            if key in seen_edges:
                continue
            seen_edges.add(key)
            deduped_edges.append(edge)

        path_payloads: list[dict[str, Any]] = []
        if pathway_records:
            for pathway_node, pathway in pathway_records:
                path_nodes = [variant_node, gene_node, protein_node, pathway_node]
                path_edges = [
                    self._build_edge(variant_node["id"], gene_node["id"], "VARIANT_OF", variant_provenance),
                    self._build_edge(gene_node["id"], protein_node["id"], "ENCODES", protein_provenance),
                    self._build_edge(protein_node["id"], pathway_node["id"], "PARTICIPATES_IN", self._provenance(
                        "Reactome",
                        pathway.get("stId") or pathway.get("source_id"),
                        pathway.get("url") or f"https://reactome.org/PathwayBrowser/#/{pathway.get('stId') or pathway.get('source_id')}",
                        "PARTICIPATES_IN",
                        f"Reactome pathway membership for {gene_symbol}",
                        retrieved_at=self._now(),
                    )),
                ]
                for reaction in self.reactome.fetch_reactions_for_pathway(pathway.get("stId") or pathway.get("source_id"))[:4]:
                    reaction_id = reaction.get("source_id") or reaction.get("stId")
                    if not reaction_id:
                        continue
                    reaction_node = next((node for node in deduped_nodes if node["id"] == f"reaction:{reaction_id}"), None)
                    if reaction_node is None:
                        continue
                    path_nodes.append(reaction_node)
                    path_edges.append(self._build_edge(pathway_node["id"], reaction_node["id"], "CONTAINS", self._provenance(
                        "Reactome",
                        reaction_id,
                        reaction.get("url") or f"https://reactome.org/PathwayBrowser/#/{reaction_id}",
                        "CONTAINS",
                        f"Contained Reactome event for {pathway_node['name']}",
                        retrieved_at=self._now(),
                    )))
                path_payloads.append({
                    "nodes": path_nodes,
                    "edges": path_edges,
                    "evidence": evidence,
                })
        if not path_payloads:
            path_payloads.append({
                "nodes": [variant_node, gene_node, protein_node],
                "edges": [
                    self._build_edge(variant_node["id"], gene_node["id"], "VARIANT_OF", variant_provenance),
                    self._build_edge(gene_node["id"], protein_node["id"], "ENCODES", protein_provenance),
                ],
                "evidence": evidence,
            })

        self._graph_cache[query] = {"nodes": deduped_nodes, "edges": deduped_edges}
        return {
            "query": query,
            "status": "resolved",
            "message": "resolved from live source data",
            "variant": variant_data,
            "graph": {"nodes": deduped_nodes, "edges": deduped_edges},
            "paths": path_payloads,
            "sources": source_metadata,
            "candidate_drugs": [],
        }
