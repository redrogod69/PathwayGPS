from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class GraphBackend:
    """Small backend abstraction with a read-only JSON fallback."""

    def __init__(self, repo_root: Path, graph: Mapping[str, Any] | None = None) -> None:
        self.path = repo_root / "data" / "canonical" / "quick_graph.json"
        self._graph = dict(graph) if graph is not None else self._load()

    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except (OSError, ValueError, TypeError):
            pass
        return {}

    def graph(self) -> dict[str, Any]:
        nodes = list(self._graph.get("nodes", []))
        edges = list(self._graph.get("relationships", self._graph.get("edges", [])))
        if not nodes:
            by_id: dict[str, dict[str, Any]] = {}
            for gene in self._graph.get("genes", []):
                symbol = gene.get("gene_symbol")
                if symbol:
                    by_id.setdefault(symbol, {"id": symbol, "name": symbol, "type": "gene"})
                accession = gene.get("protein_accession")
                if accession:
                    by_id.setdefault(accession, {"id": accession, "name": gene.get("protein_name") or accession, "type": "protein"})
            for variant in self._graph.get("variants", []):
                name = f"{variant.get('gene_symbol')} {variant.get('protein_change')}".strip()
                if name:
                    by_id.setdefault(name, {"id": name, "name": name, "type": "variant"})
            for edge in edges:
                for key, node_type in (("source", "gene"), ("target", "pathway")):
                    identifier = edge.get(key)
                    if identifier:
                        by_id.setdefault(identifier, {"id": identifier, "name": identifier, "type": node_type})
            nodes = list(by_id.values())
        return {
            "nodes": nodes,
            "edges": edges,
        }

    @property
    def name(self) -> str:
        return "memory-json"

    def variants(self) -> list[str]:
        variants = {
            f"{v.get('gene_symbol')} {v.get('protein_change')}".strip()
            for v in self._graph.get("variants", [])
            if v.get("gene_symbol") and v.get("protein_change")
        }
        variants.update(
            str(node.get("name"))
            for node in self._graph.get("nodes", [])
            if node.get("type") == "variant" and node.get("name")
        )
        return sorted(variants)

    def node(self, node_id: str) -> dict[str, Any] | None:
        return next((dict(n) for n in self.graph()["nodes"] if n.get("id") == node_id), None)
