"""Open Targets Platform GraphQL adapter (target–disease associations, drug mechanisms)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.http import HttpClient, SourceError, Tracker

API = "https://api.platform.opentargets.org/api/v4/graphql"

ASSOC_QUERY = """
query Assoc($id: String!, $size: Int!) {
  meta { apiVersion { x y z } dataVersion { year month } }
  target(ensemblId: $id) {
    id approvedSymbol
    associatedDiseases(page: {index: 0, size: $size}) {
      count
      rows { score datatypeScores { id score } disease { id name dbXRefs therapeuticAreas { name } } }
    }
  }
}"""

DRUG_QUERY = """
query Drugs($id: String!) {
  target(ensemblId: $id) {
    drugAndClinicalCandidates {
      count
      rows {
        maxClinicalStage
        drug { id name drugType
          mechanismsOfAction { rows { mechanismOfAction actionType targets { id approvedSymbol } references { source ids urls } } } }
        diseases { diseaseFromSource disease { id name } }
      }
    }
  }
}"""

STAGE_ORDER = {"APPROVAL": 0, "PHASE_4": 1, "PHASE_3": 2, "PHASE_2_3": 3, "PHASE_2": 4, "PHASE_1_2": 5, "PHASE_1": 6, "EARLY_PHASE_1": 7}


class OpenTargetsAdapter:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    async def _query(self, query: str, variables: Dict[str, Any], tracker: Tracker, purpose: str) -> Dict[str, Any]:
        resp = await self.http.post("opentargets", API, tracker=tracker, json_body={"query": query, "variables": variables},
                                    purpose=purpose, timeout=40)
        data = resp.data or {}
        if data.get("errors") and not data.get("data"):
            raise SourceError("opentargets", "http", "GraphQL error: " + str(data["errors"][0].get("message", ""))[:160])
        payload = data.get("data") or {}
        payload["_retrieved_at"] = resp.fetched_at
        return payload

    async def associations(self, ensembl_id: str, tracker: Tracker, size: int = 10) -> Dict[str, Any]:
        data = await self._query(ASSOC_QUERY, {"id": ensembl_id, "size": size}, tracker, "target–disease associations")
        meta = data.get("meta") or {}
        dv = meta.get("dataVersion") or {}
        if dv.get("year"):
            tracker.releases["opentargets"] = f"{dv.get('year')}.{dv.get('month')}"
        target = data.get("target") or {}
        assoc = target.get("associatedDiseases") or {}
        rows = []
        for r in assoc.get("rows", []) or []:
            d = r.get("disease") or {}
            rows.append({
                "disease_id": d.get("id"),
                "name": d.get("name"),
                "xrefs": d.get("dbXRefs") or [],
                "therapeutic_areas": [t.get("name") for t in d.get("therapeuticAreas") or []],
                "score": r.get("score"),
                "datatype_scores": {x.get("id"): x.get("score") for x in r.get("datatypeScores") or []},
                "url": f"https://platform.opentargets.org/evidence/{ensembl_id}/{d.get('id')}",
            })
        return {"count": assoc.get("count"), "rows": rows, "retrieved_at": data["_retrieved_at"],
                "url": f"https://platform.opentargets.org/target/{ensembl_id}/associations"}

    async def drugs(self, ensembl_id: str, gene_symbol: str, tracker: Tracker, limit: int = 12) -> Dict[str, Any]:
        """Drugs whose curated mechanism of action lists this gene as a target.

        Open Targets lists candidates per target, but each drug's MoA rows name their own targets
        (e.g. sorafenib appears for BRAF with a RAF1 mechanism). Only drugs whose MoA names this
        gene are returned as targeting it; the rest are counted and reported, not drawn.
        """
        data = await self._query(DRUG_QUERY, {"id": ensembl_id}, tracker, "drug mechanisms")
        target = data.get("target") or {}
        block = target.get("drugAndClinicalCandidates") or {}
        kept, excluded = [], []
        for r in block.get("rows", []) or []:
            drug = r.get("drug") or {}
            moas = (drug.get("mechanismsOfAction") or {}).get("rows", []) or []
            matching = [m for m in moas if any((t.get("id") == ensembl_id) for t in m.get("targets") or [])]
            item = {
                "chembl_id": drug.get("id"),
                "name": drug.get("name"),
                "drug_type": drug.get("drugType"),
                "max_stage": r.get("maxClinicalStage"),
                "mechanisms": [{
                    "mechanism": m.get("mechanismOfAction"), "action_type": m.get("actionType"),
                    "targets": [t.get("approvedSymbol") for t in m.get("targets") or []],
                    "pmids": [i for ref in m.get("references") or [] if ref.get("source") == "PubMed" for i in ref.get("ids") or []][:10],
                    "reference_sources": sorted({ref.get("source") for ref in m.get("references") or [] if ref.get("source")}),
                } for m in (matching or moas)],
                "indications": [(d.get("disease") or {}).get("name") or d.get("diseaseFromSource") for d in r.get("diseases") or []][:8],
                "url": f"https://platform.opentargets.org/drug/{drug.get('id')}",
            }
            (kept if matching else excluded).append(item)
        kept.sort(key=lambda d: (STAGE_ORDER.get(d["max_stage"] or "", 9), d["name"] or ""))
        return {
            "count": block.get("count"),
            "drugs": kept[:limit],
            "total_targeting": len(kept),
            "excluded_other_target": [{"name": d["name"], "mechanism_targets": sorted({t for m in d["mechanisms"] for t in m["targets"]})} for d in excluded],
            "retrieved_at": data["_retrieved_at"],
        }
