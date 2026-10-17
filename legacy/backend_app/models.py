from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

NodeType = Literal["variant", "gene", "protein", "pathway", "reaction", "event", "effect", "drug"]
Classification = Literal[
    "database_fact",
    "predicted_relationship",
    "model_output",
    "user_input",
    "manual_seed_data",
]


class Provenance(BaseModel):
    source_database: str
    source_id: str
    relationship: str
    evidence: str = ""
    evidence_summary: str = ""
    source_url: str = ""
    version: str = "unknown"
    download_date: str = ""
    downloaded_at: str = ""
    classification: Classification = "database_fact"


class GraphNode(BaseModel):
    id: str
    name: str
    type: NodeType
    description: Optional[str] = None
    classification: Classification = "database_fact"
    provenance: Optional[Provenance] = None


class GraphEdge(BaseModel):
    id: str = ""
    source: str
    target: str
    relationship: str
    description: Optional[str] = None
    classification: Classification = "manual_seed_data"
    provenance: Optional[Provenance] = None


class GraphPayload(BaseModel):
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []


class AnalyzeResponse(BaseModel):
    query: str
    status: str
    message: str
    variant: Optional[dict] = None
    graph: GraphPayload
    paths: list[dict] = []
    sources: dict = {}
    candidate_drugs: list[dict] = []
