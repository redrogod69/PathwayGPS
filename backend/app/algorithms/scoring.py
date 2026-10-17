from __future__ import annotations

from typing import Any, Mapping, Sequence


def edge_score(edge: Mapping[str, Any]) -> float:
    """Score evidence, never implying biological confidence."""
    value = edge.get("evidence_score", edge.get("score", 1.0))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 1.0


def score_path(path: Sequence[Any], graph: Mapping[str, Any] | None = None) -> float:
    if graph is None or len(path) < 2:
        return 0.0 if len(path) < 2 else 1.0
    lookup = {(e.get("source"), e.get("target")): e for e in graph.get("edges", []) or []}
    return sum(edge_score(lookup.get((path[index], path[index + 1]), {})) for index in range(len(path) - 1))


def path_confidence(path: Sequence[Any], graph: Mapping[str, Any]) -> float:
    """Return a bounded evidence confidence for a path.

    This is an evidence aggregation, not a biological probability. Missing
    evidence receives the neutral score of one.
    """
    if len(path) < 2:
        return 1.0
    scores = []
    lookup = {(e.get("source"), e.get("target")): e for e in graph.get("edges", []) or []}
    for index in range(len(path) - 1):
        scores.append(edge_score(lookup.get((path[index], path[index + 1]), {})))
    return max(0.0, min(1.0, sum(scores) / len(scores)))
