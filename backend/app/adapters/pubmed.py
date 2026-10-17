"""PubMed adapter (NCBI E-utilities). Abstracts are fetched on demand only."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from app.core.http import HttpClient, Tracker

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedAdapter:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    async def summaries(self, pmids: List[str], tracker: Tracker) -> Dict[str, Dict[str, Any]]:
        ids = [p for p in dict.fromkeys(str(x) for x in pmids) if p.isdigit()]
        out: Dict[str, Dict[str, Any]] = {}
        for start in range(0, len(ids), 150):
            chunk = ids[start:start + 150]
            resp = await self.http.post("pubmed", f"{EUTILS}/esummary.fcgi", tracker=tracker, purpose="publication metadata",
                                        params={"db": "pubmed", "retmode": "json"}, content=f"id={','.join(chunk)}",
                                        headers={"Content-Type": "application/x-www-form-urlencoded"})
            result = (resp.data or {}).get("result", {})
            for uid in result.get("uids", []):
                r = result.get(uid) or {}
                if r.get("error"):
                    continue
                doi = next((a.get("value") for a in r.get("articleids", []) if a.get("idtype") == "doi"), None)
                pmc = next((a.get("value") for a in r.get("articleids", []) if a.get("idtype") == "pmc"), None)
                authors = [a.get("name") for a in r.get("authors", []) if a.get("authtype") == "Author"]
                out[uid] = {
                    "pmid": uid,
                    "title": r.get("title"),
                    "journal": r.get("source") or r.get("fulljournalname"),
                    "year": (r.get("pubdate") or "")[:4] or None,
                    "authors": authors[:3] + (["et al."] if len(authors) > 3 else []),
                    "doi": doi,
                    "pmc": pmc,
                    "pubtypes": r.get("pubtype", []),
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                    "retrieved_at": resp.fetched_at,
                }
        return out

    async def abstract(self, pmid: str, tracker: Tracker) -> Dict[str, Any]:
        resp = await self.http.get("pubmed", f"{EUTILS}/efetch.fcgi", tracker=tracker, expect="text", purpose="abstract (on demand)",
                                   params={"db": "pubmed", "id": pmid, "retmode": "xml", "rettype": "abstract"})
        return {"pmid": pmid, **self.parse_abstract_xml(resp.data or ""), "retrieved_at": resp.fetched_at,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"}

    @staticmethod
    def parse_abstract_xml(xml_text: str) -> Dict[str, Any]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return {"title": None, "sections": [], "mesh": [], "pubtypes": []}
        article = root.find(".//Article")
        title = "".join(article.find("ArticleTitle").itertext()) if article is not None and article.find("ArticleTitle") is not None else None
        sections = []
        for node in root.iter("AbstractText"):
            text = "".join(node.itertext()).strip()
            if text:
                sections.append({"label": node.get("Label"), "text": text})
        mesh = [m.text for m in root.iter("DescriptorName") if m.text][:20]
        pubtypes = [p.text for p in root.iter("PublicationType") if p.text]
        copyright_node = root.find(".//Abstract/CopyrightInformation")
        return {"title": title, "sections": sections, "mesh": mesh, "pubtypes": pubtypes,
                "copyright": copyright_node.text if copyright_node is not None else None}

    async def search(self, term: str, tracker: Tracker, retmax: int = 20) -> Dict[str, Any]:
        resp = await self.http.get("pubmed", f"{EUTILS}/esearch.fcgi", tracker=tracker, purpose="literature search",
                                   params={"db": "pubmed", "term": term, "retmode": "json", "retmax": retmax, "sort": "relevance"})
        res = (resp.data or {}).get("esearchresult", {})
        return {"count": int(res.get("count", 0) or 0), "ids": res.get("idlist", []), "query_translation": res.get("querytranslation")}


def methods_from_pubtypes(pubtypes: Optional[List[str]]) -> List[str]:
    """Map PubMed publication types to a coarse study-design label shown next to evidence."""
    labels = []
    for p in pubtypes or []:
        lower = p.lower()
        if "clinical trial" in lower or "randomized" in lower:
            labels.append("clinical trial")
        elif lower == "review" or "systematic review" in lower or "meta-analysis" in lower:
            labels.append("review / meta-analysis")
        elif "case reports" in lower:
            labels.append("case report")
        elif "comparative study" in lower:
            labels.append("comparative study")
    return sorted(set(labels))
