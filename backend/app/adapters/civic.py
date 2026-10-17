"""CIViC GraphQL adapter: curated clinical evidence for cancer variants."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.http import HttpClient, SourceError, Tracker

API = "https://civicdb.org/api/graphql"
SITE = "https://civicdb.org"

PROFILE_QUERY = """
query Profiles($name: String!) {
  molecularProfiles(name: $name, first: 10) { nodes { id name link molecularProfileScore } }
}"""

EVIDENCE_QUERY = """
query Evidence($id: Int!, $first: Int!) {
  evidenceItems(molecularProfileId: $id, status: ACCEPTED, first: $first) {
    totalCount
    nodes {
      id name link evidenceType evidenceLevel evidenceDirection significance evidenceRating variantOrigin description
      disease { name doid }
      therapies { name ncitId }
      therapyInteractionType
      source { citationId sourceType citation }
    }
  }
}"""

LEVEL_LABEL = {
    "A": "A — validated association",
    "B": "B — clinical evidence",
    "C": "C — case study",
    "D": "D — preclinical evidence",
    "E": "E — inferential association",
}


class CivicAdapter:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    async def _query(self, query: str, variables: Dict[str, Any], tracker: Tracker, purpose: str) -> Dict[str, Any]:
        resp = await self.http.post("civic", API, tracker=tracker, json_body={"query": query, "variables": variables}, purpose=purpose, timeout=40)
        data = resp.data or {}
        if data.get("errors") and not data.get("data"):
            raise SourceError("civic", "http", "GraphQL error: " + str(data["errors"][0].get("message", ""))[:160])
        out = data.get("data") or {}
        out["_retrieved_at"] = resp.fetched_at
        return out

    async def evidence_for_variant(self, gene: str, change_short: str, tracker: Tracker, first: int = 60) -> Dict[str, Any]:
        """Accepted evidence items for the molecular profile named exactly '<GENE> <CHANGE>'.

        Composite profiles (e.g. 'BRAF V600E OR BRAF K601E') are listed but not merged, because
        their evidence does not apply to the single variant alone.
        """
        name = f"{gene} {change_short}"
        profiles = await self._query(PROFILE_QUERY, {"name": name}, tracker, "molecular profile lookup")
        nodes = (profiles.get("molecularProfiles") or {}).get("nodes", []) or []
        exact = next((n for n in nodes if (n.get("name") or "").upper() == name.upper()), None)
        related = [{"id": n.get("id"), "name": n.get("name"), "url": SITE + (n.get("link") or "")} for n in nodes if n is not exact]
        if exact is None:
            return {"profile": None, "related_profiles": related, "items": [], "total": 0, "retrieved_at": profiles["_retrieved_at"]}
        ev = await self._query(EVIDENCE_QUERY, {"id": int(exact["id"]), "first": first}, tracker, "accepted evidence items")
        block = ev.get("evidenceItems") or {}
        items = []
        for n in block.get("nodes", []) or []:
            src = n.get("source") or {}
            items.append({
                "eid": n.get("id"),
                "name": n.get("name"),
                "url": SITE + (n.get("link") or f"/evidence/{n.get('id')}"),
                "type": n.get("evidenceType"),
                "level": n.get("evidenceLevel"),
                "level_label": LEVEL_LABEL.get(n.get("evidenceLevel") or "", n.get("evidenceLevel")),
                "direction": n.get("evidenceDirection"),
                "significance": n.get("significance"),
                "rating": n.get("evidenceRating"),
                "origin": n.get("variantOrigin"),
                "description": (n.get("description") or "")[:900],
                "disease": (n.get("disease") or {}).get("name"),
                "doid": (n.get("disease") or {}).get("doid"),
                "therapies": [t.get("name") for t in n.get("therapies") or []],
                "therapy_ncit": [t.get("ncitId") for t in n.get("therapies") or []],
                "therapy_interaction": n.get("therapyInteractionType"),
                "pmid": src.get("citationId") if (src.get("sourceType") or "").upper() == "PUBMED" else None,
                "citation": src.get("citation"),
                "source_type": src.get("sourceType"),
            })
        level_rank = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
        items.sort(key=lambda i: (level_rank.get(i["level"] or "", 9), -(i["rating"] or 0)))
        return {
            "profile": {"id": exact.get("id"), "name": exact.get("name"), "url": SITE + (exact.get("link") or ""),
                        "score": exact.get("molecularProfileScore")},
            "related_profiles": related,
            "items": items,
            "total": block.get("totalCount", len(items)),
            "retrieved_at": ev["_retrieved_at"],
        }
