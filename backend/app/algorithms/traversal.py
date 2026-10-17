from __future__ import annotations

from collections import deque
import heapq
from typing import Any, Mapping

from .adjacency import build_adjacency


def neighbors(graph: Mapping[str, Any], node_id: str, directed: bool = False) -> list[dict[str, Any]]:
    return build_adjacency(graph, directed).get(node_id, [])


def bfs_paths(graph: Mapping[str, Any], start: str, max_depth: int = 3, directed: bool = False) -> list[list[str]]:
    if max_depth < 0:
        return []
    adjacency = build_adjacency(graph, directed)
    paths: list[list[str]] = [[start]]
    queue = deque([[start]])
    while queue:
        path = queue.popleft()
        if len(path) - 1 >= max_depth:
            continue
        for edge in adjacency.get(path[-1], []):
            target = str(edge["target"])
            if target in path:
                continue
            extended = path + [target]
            paths.append(extended)
            queue.append(extended)
    return paths


def dfs_paths(graph: Mapping[str, Any], start: str, max_depth: int = 3, directed: bool = False) -> list[list[str]]:
    """Enumerate simple paths depth-first, deterministically."""
    if max_depth < 0:
        return []
    adjacency = build_adjacency(graph, directed)
    result: list[list[str]] = []
    stack = [[start]]
    while stack:
        path = stack.pop()
        result.append(path)
        if len(path) - 1 >= max_depth:
            continue
        children = [str(edge["target"]) for edge in adjacency.get(path[-1], []) if str(edge["target"]) not in path]
        for child in reversed(children):
            stack.append(path + [child])
    return result


def dijkstra_path(graph: Mapping[str, Any], source: str, target: str, directed: bool = False) -> list[str]:
    """Find the highest-evidence (lowest cost) path between two nodes."""
    adjacency = build_adjacency(graph, directed)
    queue: list[tuple[float, list[str]]] = [(0.0, [source])]
    best: dict[str, float] = {source: 0.0}
    while queue:
        cost, path = heapq.heappop(queue)
        node = path[-1]
        if node == target:
            return path
        if cost > best.get(node, float("inf")):
            continue
        for edge in adjacency.get(node, []):
            child = str(edge["target"])
            if child in path:
                continue
            try:
                evidence = float(edge.get("evidence_score", edge.get("score", 1.0)))
            except (TypeError, ValueError):
                evidence = 1.0
            next_cost = cost + (1.0 / max(evidence, 1e-9))
            if next_cost < best.get(child, float("inf")):
                best[child] = next_cost
                heapq.heappush(queue, (next_cost, path + [child]))
    return []


def traverse(graph: Mapping[str, Any], start: str, algorithm: str = "bfs", max_depth: int = 3, directed: bool = False) -> list[list[str]]:
    if algorithm == "bfs":
        return bfs_paths(graph, start, max_depth, directed)
    if algorithm == "dfs":
        return dfs_paths(graph, start, max_depth, directed)
    raise ValueError("algorithm must be bfs or dfs")


def shortest_paths(graph: Mapping[str, Any], start: str, target: str | None = None, max_depth: int = 6, directed: bool = False) -> list[list[str]]:
    paths = bfs_paths(graph, start, max_depth, directed)
    matching = [path for path in paths if target is None or path[-1] == target]
    return sorted(matching, key=lambda path: (len(path), path))
