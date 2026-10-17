# Graph algorithms

Per-analysis graphs are sparse and small, stored as dictionaries of nodes/edges (adjacency built on demand, O(V + E)).

* **Explainable path** (`backend/app/pipeline/insights.py::explain_path`): Dijkstra over an undirected view of the typed
  multigraph (edge direction is reported per hop), binary-heap priority queue, O((V + E) log V). Cost function and its
  interpretation are documented in `docs/architecture.md` — it ranks navigation routes and is not a probability.
* **Route layout** (`frontend/src/components/GraphCanvas.tsx::routePositions`): columns by entity type; reactions are
  placed by breadth-first depth along curated `REACTION_PRECEDES` / `REACTION_PRODUCES` / `ENTITY_INPUT_OF_REACTION` edges.
* `backend/app/algorithms/` (BFS, DFS, Dijkstra on generic edge lists) is retained from the original build and unit-tested;
  the API no longer exposes the static-graph traversal endpoints that used it (they operated on a demo graph, not on the analysis).
