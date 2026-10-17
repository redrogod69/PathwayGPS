"""Explicit placeholder for a future learned model; no biological claims."""

from __future__ import annotations

from typing import Any, Mapping


def predict(graph: Mapping[str, Any], node_id: str | None = None) -> dict[str, Any]:
    raise NotImplementedError("Planned future extension — not implemented")
