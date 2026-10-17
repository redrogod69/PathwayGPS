from app.algorithms import bfs_paths, dfs_paths, dijkstra_path


GRAPH = {
    "edges": [
        {"source": "a", "target": "b", "evidence_score": 1},
        {"source": "b", "target": "c", "evidence_score": 1},
        {"source": "a", "target": "c", "evidence_score": 0.25},
    ]
}


def test_bfs_and_dfs_respect_depth_and_cycles():
    assert ["a", "b", "c"] in bfs_paths(GRAPH, "a", max_depth=2, directed=True)
    assert all(len(path) <= 3 for path in dfs_paths(GRAPH, "a", max_depth=2, directed=True))


def test_dijkstra_prefers_high_evidence_path():
    assert dijkstra_path(GRAPH, "a", "c", directed=True) == ["a", "b", "c"]
