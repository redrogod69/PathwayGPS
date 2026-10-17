from __future__ import annotations

from typing import Any


class KEGGService:
    """KEGG integration is deliberately deferred until licensing is settled."""

    def lookup(self, gene_symbol: str) -> dict[str, Any]:
        return {
            "status": "planned",
            "gene_symbol": (gene_symbol or "").strip().upper(),
            "message": "KEGG lookup is planned; no KEGG data was fabricated.",
        }
