from __future__ import annotations

from typing import Any, Mapping

from neo4j import GraphDatabase


class Neo4jClient:
    def __init__(self, uri: str = 'bolt://localhost:7687', username: str = 'neo4j', password: str = 'pathwaygps', fallback: Mapping[str, Any] | None = None) -> None:
        self.uri = uri
        self.username = username
        self.password = password
        self.driver = GraphDatabase.driver(uri, auth=(username, password))
        self.fallback = fallback

    def close(self) -> None:
        self.driver.close()

    def run(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self.driver.session(database='neo4j') as session:
            result = session.run(query, parameters or {})
            return [dict(record) for record in result]

    def list_nodes(self, label: str | None = None) -> list[dict[str, Any]]:
        if self.fallback is not None:
            nodes = self.fallback.get("nodes", [])
            return [dict(n) for n in nodes if not label or n.get("type") == label]
        return self.run("MATCH (n) RETURN n", {})

    def neighbors(self, node_id: str) -> list[dict[str, Any]]:
        if self.fallback is not None:
            return [dict(e) for e in self.fallback.get("edges", []) if e.get("source") == node_id or e.get("target") == node_id]
        return self.run("MATCH (n {id: $id})-[r]-(m) RETURN r, m", {"id": node_id})
