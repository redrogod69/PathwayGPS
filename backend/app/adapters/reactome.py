"""Reactome Content Service + Analysis Service adapter (and IntAct static interactors)."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from app.core.http import HttpClient, SourceError, Tracker

CONTENT = "https://reactome.org/ContentService"
ANALYSIS = "https://reactome.org/AnalysisService"
BROWSER = "https://reactome.org/PathwayBrowser/#/{id}"
DETAIL = "https://reactome.org/content/detail/{id}"


def browser_url(st_id: str, pathway: Optional[str] = None) -> str:
    if pathway and pathway != st_id:
        return f"https://reactome.org/PathwayBrowser/#/{pathway}&SEL={st_id}"
    return BROWSER.format(id=st_id)


def _name(obj: Dict[str, Any]) -> str:
    return obj.get("displayName") or (obj.get("name") or [obj.get("stId", "")])[0]


def _entity(obj: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(obj, dict) or not obj.get("stId"):
        return None
    return {
        "stId": obj["stId"],
        "name": _name(obj),
        "schemaClass": obj.get("schemaClass") or obj.get("className"),
        "inDisease": bool(obj.get("inDisease") or obj.get("isInDisease")),
    }


def normalize_event(obj: Dict[str, Any], fetched_at: Optional[str] = None) -> Dict[str, Any]:
    literature = []
    for ref in obj.get("literatureReference", []) or []:
        pmid = ref.get("pubMedIdentifier")
        literature.append({
            "pmid": str(pmid) if pmid else None,
            "title": ref.get("title") or ref.get("displayName"),
            "journal": ref.get("journal"),
            "year": ref.get("year"),
            "url": ref.get("url"),
        })
    summation = " ".join((s.get("text") or "") for s in obj.get("summation", []) or [] if isinstance(s, dict)).strip()
    review = obj.get("reviewStatus")
    return {
        "stId": obj.get("stId"),
        "name": _name(obj),
        "schemaClass": obj.get("schemaClass") or obj.get("className"),
        "category": obj.get("category"),
        "isInDisease": bool(obj.get("isInDisease")),
        "isInferred": bool(obj.get("isInferred")),
        "releaseDate": obj.get("releaseDate"),
        "lastUpdatedDate": obj.get("lastUpdatedDate"),
        "doi": obj.get("doi"),
        "reviewStatus": review.get("displayName") if isinstance(review, dict) else None,
        "inputs": [e for e in (_entity(x) for x in obj.get("input", []) or []) if e],
        "outputs": [e for e in (_entity(x) for x in obj.get("output", []) or []) if e],
        "catalysts": [c.get("displayName") for c in obj.get("catalystActivity", []) or [] if isinstance(c, dict)],
        "regulators": [r.get("displayName") for r in obj.get("regulatedBy", []) or [] if isinstance(r, dict)],
        "precedingEvents": [e.get("stId") for e in obj.get("precedingEvent", []) or [] if isinstance(e, dict) and e.get("stId")],
        "compartments": [c.get("displayName") for c in obj.get("compartment", []) or [] if isinstance(c, dict)],
        "diseases": [{"name": d.get("displayName"), "doid": d.get("identifier")} for d in obj.get("disease", []) or [] if isinstance(d, dict)],
        "literature": literature,
        "summation": summation[:1200],
        "url": browser_url(obj.get("stId", "")),
        "detail_url": DETAIL.format(id=obj.get("stId", "")),
        "retrieved_at": fetched_at,
    }


class ReactomeAdapter:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    async def version(self, tracker: Tracker) -> Optional[str]:
        try:
            resp = await self.http.get("reactome", f"{CONTENT}/data/database/version", tracker=tracker, expect="text",
                                       purpose="release metadata", timeout=10)
            return str(resp.data).strip() or None
        except SourceError:
            return None

    async def pathways_for_uniprot(self, accession: str, tracker: Tracker) -> List[Dict[str, Any]]:
        resp = await self.http.get("reactome", f"{CONTENT}/data/mapping/UniProt/{quote(accession)}/pathways", tracker=tracker,
                                   params={"species": "9606"}, allow_status=(404,), purpose="lowest-level pathways for protein")
        if resp.status == 404 or not isinstance(resp.data, list):
            return []
        return [{
            "stId": p.get("stId"), "name": _name(p), "isInDisease": bool(p.get("isInDisease")),
            "isInferred": bool(p.get("isInferred")), "hasDiagram": bool(p.get("hasDiagram")),
            "releaseDate": p.get("releaseDate"), "lastUpdatedDate": p.get("lastUpdatedDate"),
            "url": browser_url(p.get("stId", "")), "retrieved_at": resp.fetched_at,
        } for p in resp.data if p.get("stId")]

    async def reactions_for_uniprot(self, accession: str, tracker: Tracker) -> List[Dict[str, Any]]:
        resp = await self.http.get("reactome", f"{CONTENT}/data/mapping/UniProt/{quote(accession)}/reactions", tracker=tracker,
                                   params={"species": "9606"}, allow_status=(404,), purpose="reactions involving protein")
        if resp.status == 404 or not isinstance(resp.data, list):
            return []
        return [{"stId": r.get("stId"), "name": _name(r), "isInDisease": bool(r.get("isInDisease")),
                 "isInferred": bool(r.get("isInferred")), "schemaClass": r.get("schemaClass"),
                 "retrieved_at": resp.fetched_at} for r in resp.data if r.get("stId")]

    async def query_ids(self, ids: List[str], tracker: Tracker) -> Dict[str, Dict[str, Any]]:
        """Full objects for up to N stable IDs (batched by 20)."""
        unique = [i for i in dict.fromkeys(ids) if i]
        out: Dict[str, Dict[str, Any]] = {}

        async def batch(chunk: List[str]) -> None:
            resp = await self.http.post("reactome", f"{CONTENT}/data/query/ids", tracker=tracker, content=",".join(chunk),
                                        headers={"Content-Type": "text/plain"}, purpose="event details", allow_status=(404,))
            for obj in resp.data if isinstance(resp.data, list) else []:
                if obj.get("stId"):
                    out[obj["stId"]] = normalize_event(obj, resp.fetched_at)

        chunks = [unique[i:i + 20] for i in range(0, len(unique), 20)]
        results = await asyncio.gather(*(batch(c) for c in chunks), return_exceptions=True)
        errors = [r for r in results if isinstance(r, Exception)]
        if errors and not out:
            raise errors[0]
        return out

    async def _attribute_list(self, st_id: str, attribute: str, tracker: Tracker) -> List[Dict[str, Any]]:
        resp = await self.http.get("reactome", f"{CONTENT}/data/query/{quote(st_id)}/{attribute}", tracker=tracker, expect="text",
                                   allow_status=(404,), purpose=f"{attribute} of {st_id}")
        if resp.status == 404:
            return []
        rows = []
        for line in str(resp.data or "").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].startswith("R-"):
                rows.append({"stId": parts[0], "name": parts[1], "schemaClass": parts[2] if len(parts) > 2 else None})
        return rows

    async def following_events(self, st_id: str, tracker: Tracker) -> List[Dict[str, Any]]:
        return await self._attribute_list(st_id, "followingEvent", tracker)

    async def consumed_by(self, entity_st_id: str, tracker: Tracker) -> List[Dict[str, Any]]:
        return await self._attribute_list(entity_st_id, "consumedByEvent", tracker)

    async def ancestors(self, st_id: str, tracker: Tracker) -> List[List[Dict[str, Any]]]:
        resp = await self.http.get("reactome", f"{CONTENT}/data/event/{quote(st_id)}/ancestors", tracker=tracker,
                                   allow_status=(404,), purpose="pathway hierarchy")
        if resp.status == 404 or not isinstance(resp.data, list):
            return []
        return [[{"stId": p.get("stId"), "name": _name(p)} for p in path if isinstance(p, dict)] for path in resp.data]

    async def contained_event_ids(self, pathway_st_id: str, tracker: Tracker) -> List[str]:
        resp = await self.http.get("reactome", f"{CONTENT}/data/pathway/{quote(pathway_st_id)}/containedEvents/stId", tracker=tracker,
                                   expect="text", allow_status=(404,), purpose="events contained in pathway")
        if resp.status == 404:
            return []
        text = str(resp.data or "").strip().strip("[]")
        return [t.strip().strip('"') for t in text.replace("\n", ",").split(",") if t.strip().strip('"').startswith("R-")]

    async def interactors(self, accession: str, tracker: Tracker) -> List[Dict[str, Any]]:
        resp = await self.http.get("intact", f"{CONTENT}/interactors/static/molecule/{quote(accession)}/details", tracker=tracker,
                                   allow_status=(404,), purpose="IntAct interactors")
        if resp.status == 404 or not isinstance(resp.data, dict):
            return []
        rows = []
        for entity in resp.data.get("entities", []) or []:
            for it in entity.get("interactors", []) or []:
                rows.append({
                    "accession": it.get("acc"), "alias": it.get("alias"), "score": it.get("score"),
                    "evidence_count": it.get("evidences"), "intact_url": it.get("evidencesURL"),
                    "retrieved_at": resp.fetched_at,
                })
        rows.sort(key=lambda r: (-(r["score"] or 0), r["alias"] or ""))
        return rows

    async def participating_entities(self, pathway_st_id: str, tracker: Tracker) -> List[Dict[str, Any]]:
        resp = await self.http.get("reactome", f"{CONTENT}/data/participants/{quote(pathway_st_id)}/participatingPhysicalEntities",
                                   tracker=tracker, allow_status=(404,), purpose="pathway participants")
        if resp.status == 404 or not isinstance(resp.data, list):
            return []
        return [{"stId": e.get("stId"), "name": e.get("displayName") or "", "schemaClass": e.get("schemaClass")} for e in resp.data if e.get("stId")]

    async def set_members(self, set_ids: List[str], tracker: Tracker) -> Dict[str, List[Dict[str, Any]]]:
        unique = [i for i in dict.fromkeys(set_ids) if i]
        out: Dict[str, List[Dict[str, Any]]] = {}
        for start in range(0, len(unique), 20):
            resp = await self.http.post("reactome", f"{CONTENT}/data/query/ids", tracker=tracker, content=",".join(unique[start:start + 20]),
                                        headers={"Content-Type": "text/plain"}, purpose="set members", allow_status=(404,))
            for obj in resp.data if isinstance(resp.data, list) else []:
                members = obj.get("hasMember", []) or []
                out[obj.get("stId")] = [{"stId": m.get("stId"), "name": m.get("displayName") or ""} for m in members if isinstance(m, dict)]
        return out

    async def find_variant_entities(self, gene: str, change_short: str, pathways: List[Dict[str, Any]], tracker: Tracker,
                                    max_pathways: int = 8) -> List[Dict[str, Any]]:
        """Find Reactome-curated physical entities named exactly '<GENE> <CHANGE> [compartment]'.

        Searches the participants of disease pathways (and members of their entity sets). The
        match is strict: the entity name before the compartment must equal 'GENE CHANGE', so
        compound alleles such as 'BRAF V600E;V169_D380del' are not counted as the variant.
        """
        target = f"{gene} {change_short}".upper()

        def exact(name: str) -> bool:
            return name.split(" [")[0].strip().upper() == target

        candidates = [p for p in pathways if p.get("isInDisease")][:max_pathways]
        participant_lists = await asyncio.gather(*(self.participating_entities(p["stId"], tracker) for p in candidates), return_exceptions=True)
        hits: List[Dict[str, Any]] = []
        set_lookup: Dict[str, List[str]] = {}
        for p, ents in zip(candidates, participant_lists):
            if isinstance(ents, Exception):
                continue
            for e in ents:
                if exact(e["name"]):
                    hits.append({"stId": e["stId"], "name": e["name"], "pathway": p["stId"], "pathway_name": p["name"], "via_set": None})
                elif e["schemaClass"] in ("DefinedSet", "CandidateSet") and (gene.upper() in e["name"].upper() or "mutant" in e["name"].lower()):
                    set_lookup.setdefault(e["stId"], []).append(p["stId"])
                    set_lookup[e["stId"]].append(e["name"])
        if set_lookup:
            names = {p["stId"]: p["name"] for p in candidates}
            # frontier: set id -> (pathway ids, top-level set name); descend through nested mutant sets (≤3 levels)
            frontier = {sid: ([x for x in info if x.startswith("R-")], next((x for x in info if not x.startswith("R-")), sid))
                        for sid, info in set_lookup.items()}
            visited: set = set()
            for _depth in range(3):
                ids = [sid for sid in frontier if sid not in visited][:40]
                if not ids:
                    break
                visited.update(ids)
                members = await self.set_members(ids, tracker)
                next_frontier: Dict[str, Any] = {}
                for set_id, mlist in members.items():
                    pathway_ids, set_name = frontier.get(set_id, ([], set_id))
                    for m in mlist:
                        if exact(m["name"]):
                            for pw in dict.fromkeys(pathway_ids):
                                hits.append({"stId": m["stId"], "name": m["name"], "pathway": pw, "pathway_name": names.get(pw, pw),
                                             "via_set": {"stId": set_id, "name": set_name}})
                        elif m.get("stId") and "mutant" in m["name"].lower() and m["stId"] not in visited:
                            next_frontier.setdefault(m["stId"], (pathway_ids, set_name))
                frontier = next_frontier
        seen, unique_hits = set(), []
        for h in hits:
            key = (h["stId"], h["pathway"])
            if key not in seen:
                seen.add(key)
                h["url"] = browser_url(h["stId"], h["pathway"])
                unique_hits.append(h)
        return unique_hits

    async def analyse_identifiers(self, identifiers: List[str], tracker: Tracker, page_size: int = 25) -> Dict[str, Any]:
        resp = await self.http.post("reactome", f"{ANALYSIS}/identifiers/projection", tracker=tracker, content="\n".join(identifiers),
                                    headers={"Content-Type": "text/plain"}, purpose="gene-list over-representation analysis",
                                    params={"pageSize": page_size, "page": 1, "sortBy": "ENTITIES_FDR", "order": "ASC", "resource": "TOTAL"},
                                    use_cache=True, timeout=60)
        data = resp.data or {}
        token = (data.get("summary") or {}).get("token")
        pathways = []
        for p in data.get("pathways", []) or []:
            ent = p.get("entities") or {}
            pathways.append({
                "stId": p.get("stId"), "name": p.get("name"), "found": ent.get("found"), "total": ent.get("total"),
                "ratio": ent.get("ratio"), "pValue": ent.get("pValue"), "fdr": ent.get("fdr"),
                "inDisease": p.get("inDisease"), "url": browser_url(p.get("stId", "")) + (f"&DTAB=AN&ANALYSIS={token}" if token else ""),
            })
        return {
            "token": token,
            "identifiers_not_found": data.get("identifiersNotFound"),
            "pathways_found": data.get("pathwaysFound"),
            "pathways": pathways,
            "retrieved_at": resp.fetched_at,
            "warnings": data.get("warnings") or [],
        }
