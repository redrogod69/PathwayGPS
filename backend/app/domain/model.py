"""Canonical PathwayGPS graph model: entities, typed relationships and evidence.

Every relationship (edge) holds one or more evidence records. An evidence
record says *which source asserted what*, under which category:

* ``curated``       expert-curated database assertion (Reactome, ClinVar submission, CIViC, ChEMBL mechanism, UniProt feature with experimental ECO code)
* ``experimental``  experimental observation without pathway curation (IntAct interaction, UniProt mutagenesis)
* ``association``   aggregated statistical/literature association (Open Targets score)
* ``computational`` algorithmic prediction or rule-based annotation (VEP consequence, SIFT, PolyPhen, sequence-model features)
* ``inferred``      a step derived by PathwayGPS itself (e.g. coordinate overlap) or by orthology in Reactome
* ``hypothesis``    user or AI suggestion; never displayed as evidence of fact

Evidence strength, prediction scores, graph relevance and clinical
classification are kept in separate fields and are never combined.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

CATEGORY_ORDER = ["curated", "experimental", "association", "computational", "inferred", "hypothesis"]

NODE_TIERS = {
    "variant": 0,
    "gene": 1,
    "protein": 2,
    "protein_region": 3,
    "reactome_entity": 3,
    "reaction": 4,
    "pathway": 5,
    "physical_entity": 6,
    "interactor": 3,
    "disease": 6,
    "drug": 7,
}


def stable_id(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


@dataclass
class Xref:
    db: str
    id: str
    url: Optional[str] = None


@dataclass
class Evidence:
    source: str  # source key, see app.core.http.SOURCES
    record_id: str
    record_url: Optional[str]
    evidence_type: str  # human-readable kind of record, e.g. "ClinVar submission (SCV)"
    category: str
    statement: str  # what the record asserts, in plain words
    retrieved_at: Optional[str] = None
    release: Optional[str] = None
    publications: List[str] = field(default_factory=list)  # PMIDs
    classification: Optional[str] = None  # the source's own classification, verbatim
    review_status: Optional[str] = None
    origin: Optional[str] = None  # germline / somatic / ...
    direction: Optional[str] = None  # e.g. CIViC SUPPORTS / DOES_NOT_SUPPORT
    method: Optional[str] = None
    score: Optional[Dict[str, Any]] = None  # {"name", "value", "meaning"}
    inference: Optional[str] = None  # what PathwayGPS derived, if anything
    limitations: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    id: str = ""

    def __post_init__(self) -> None:
        if self.category not in CATEGORY_ORDER:
            raise ValueError(f"unknown evidence category {self.category!r}")
        if not self.id:
            self.id = f"ev-{self.source}-{stable_id(self.source, self.record_id, self.evidence_type, self.statement)}"


@dataclass
class Node:
    id: str
    type: str
    label: str
    source: str
    subtitle: Optional[str] = None
    xrefs: List[Xref] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    role: str = "core"  # query | core | downstream | context | secondary
    secondary: bool = False
    flags: List[str] = field(default_factory=list)
    tier: int = 0

    def __post_init__(self) -> None:
        if not self.tier:
            self.tier = NODE_TIERS.get(self.type, 5)


@dataclass
class Edge:
    id: str
    source: str
    target: str
    type: str
    label: str
    evidence: List[str] = field(default_factory=list)
    category: str = "inferred"
    categories: List[str] = field(default_factory=list)
    secondary: bool = False
    attributes: Dict[str, Any] = field(default_factory=dict)


class Graph:
    """Small in-memory multigraph with evidence-aware edge merging."""

    def __init__(self) -> None:
        self.nodes: Dict[str, Node] = {}
        self.edges: Dict[str, Edge] = {}
        self.evidence: Dict[str, Evidence] = {}

    # -- nodes
    def add_node(self, node: Node) -> Node:
        existing = self.nodes.get(node.id)
        if existing is None:
            self.nodes[node.id] = node
            return node
        known = {(x.db, x.id) for x in existing.xrefs}
        existing.xrefs.extend(x for x in node.xrefs if (x.db, x.id) not in known)
        for key, value in node.attributes.items():
            existing.attributes.setdefault(key, value)
        for flag in node.flags:
            if flag not in existing.flags:
                existing.flags.append(flag)
        if existing.secondary and not node.secondary:
            existing.secondary = False
            existing.role = node.role
        return existing

    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    # -- edges
    def add_edge(
        self,
        source: str,
        target: str,
        rel_type: str,
        label: str,
        evidence: List[Evidence],
        secondary: bool = False,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Optional[Edge]:
        if source not in self.nodes or target not in self.nodes or not evidence:
            return None  # never create an edge without both endpoints and evidence
        edge_id = f"e-{stable_id(source, target, rel_type)}"
        edge = self.edges.get(edge_id)
        if edge is None:
            edge = Edge(edge_id, source, target, rel_type, label, secondary=secondary, attributes=dict(attributes or {}))
            self.edges[edge_id] = edge
        elif not secondary:
            edge.secondary = False
        for item in evidence:
            self.evidence.setdefault(item.id, item)
            if item.id not in edge.evidence:
                edge.evidence.append(item.id)
        cats = {self.evidence[e].category for e in edge.evidence}
        edge.categories = [c for c in CATEGORY_ORDER if c in cats]
        edge.category = edge.categories[0] if edge.categories else "inferred"
        return edge

    def neighbours(self, node_id: str) -> List[Edge]:
        return [e for e in self.edges.values() if e.source == node_id or e.target == node_id]

    def merge(self, other: "Graph") -> Dict[str, List[str]]:
        """Merge another graph into this one; returns ids that were new."""
        new_nodes = [nid for nid in other.nodes if nid not in self.nodes]
        new_edges = [eid for eid in other.edges if eid not in self.edges]
        for node in other.nodes.values():
            self.add_node(node)
        for edge in other.edges.values():
            ev = [other.evidence[e] for e in edge.evidence if e in other.evidence]
            self.add_edge(edge.source, edge.target, edge.type, edge.label, ev, edge.secondary, edge.attributes)
        return {"nodes": new_nodes, "edges": new_edges}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [asdict(n) for n in self.nodes.values()],
            "edges": [asdict(e) for e in self.edges.values()],
            "evidence": {k: asdict(v) for k, v in self.evidence.items()},
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Graph":
        graph = cls()
        for item in payload.get("evidence", {}).values():
            graph.evidence[item["id"]] = Evidence(**item)
        for raw in payload.get("nodes", []):
            raw = dict(raw)
            raw["xrefs"] = [Xref(**x) for x in raw.get("xrefs", [])]
            graph.nodes[raw["id"]] = Node(**raw)
        for raw in payload.get("edges", []):
            graph.edges[raw["id"]] = Edge(**raw)
        return graph
