from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping


def build_adjacency(graph: Mapping[str, Any], directed: bool = False) -> dict[str, list[dict[str, Any]]]:
    """Build a deterministic adjacency index without mutating the graph."""
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.get("edges", []) or []:
        if not isinstance(edge, Mapping) or not edge.get("source") or not edge.get("target"):
            continue
        result[str(edge["source"])].append(dict(edge))
        if not directed:
            reverse = dict(edge)
            reverse["source"], reverse["target"] = edge["target"], edge["source"]
            result[str(edge["target"])].append(reverse)
    return {key: sorted(value, key=lambda e: (str(e.get("target")), str(e.get("relationship", "")))) for key, value in sorted(result.items())}
