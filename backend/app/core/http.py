"""Shared asynchronous HTTP layer for all source adapters.

Responsibilities kept in one place so adapters stay small:
* per-source rate limiting (NCBI: 3 req/s without an API key, 10 with one),
* request timeouts and bounded retries for 429/5xx/network errors,
* in-memory + on-disk response cache (live mode honours a TTL; offline replay
  mode serves only cached responses and never touches the network),
* a per-analysis :class:`Tracker` that records every call so the UI can show
  honest per-source status instead of one global success flag.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import Settings, settings as default_settings

USER_AGENT = "PathwayGPS/2.0 (research prototype; +https://github.com/)"


@dataclass(frozen=True)
class SourceInfo:
    key: str
    name: str
    homepage: str
    license: str
    min_interval: float  # seconds between requests to this source
    max_concurrency: int = 4


SOURCES: Dict[str, SourceInfo] = {
    "clinvar": SourceInfo("clinvar", "ClinVar (NCBI)", "https://www.ncbi.nlm.nih.gov/clinvar/", "NCBI public data; E-utilities usage policy", 0.35, 1),
    "pubmed": SourceInfo("pubmed", "PubMed (NCBI)", "https://pubmed.ncbi.nlm.nih.gov/", "Bibliographic metadata public; abstracts may be publisher-copyrighted", 0.35, 1),
    "ensembl": SourceInfo("ensembl", "Ensembl REST / VEP", "https://rest.ensembl.org/", "Ensembl open data, no restrictions", 0.08, 4),
    "uniprot": SourceInfo("uniprot", "UniProtKB", "https://www.uniprot.org/", "CC BY 4.0", 0.05, 4),
    "reactome": SourceInfo("reactome", "Reactome", "https://reactome.org/", "Data CC0; illustrations CC BY 4.0", 0.05, 8),
    "intact": SourceInfo("intact", "IntAct (via Reactome)", "https://www.ebi.ac.uk/intact/", "CC BY 4.0", 0.05, 4),
    "opentargets": SourceInfo("opentargets", "Open Targets Platform", "https://platform.opentargets.org/", "CC0 1.0", 0.05, 4),
    "civic": SourceInfo("civic", "CIViC", "https://civicdb.org/", "CC0 1.0", 0.1, 3),
    "anthropic": SourceInfo("anthropic", "Claude API (optional synthesis)", "https://docs.anthropic.com/", "Model output; not a data source", 0.0, 2),
}

# NCBI limits are per IP across all E-utilities, so ClinVar and PubMed share one limiter.
_LIMITER_GROUP = {"pubmed": "ncbi", "clinvar": "ncbi", "intact": "reactome"}
RETRY_STATUSES = {429, 500, 502, 503, 504}


class SourceError(Exception):
    def __init__(self, source: str, kind: str, message: str, status: Optional[int] = None) -> None:
        super().__init__(f"{source}: {message}")
        self.source = source
        self.kind = kind  # timeout | http | network | offline_miss | parse | not_configured
        self.message = message
        self.status = status


@dataclass
class CallRecord:
    source: str
    url: str
    ok: bool
    status: Optional[int]
    from_cache: bool
    stale: bool
    duration_ms: int
    fetched_at: str
    error: Optional[str] = None
    purpose: str = ""


@dataclass
class Response:
    data: Any
    status: int
    url: str
    fetched_at: str
    from_cache: bool
    stale: bool = False


@dataclass
class Tracker:
    """Collects call records for one analysis (or one expansion request)."""

    calls: List[CallRecord] = field(default_factory=list)
    notes: Dict[str, List[str]] = field(default_factory=dict)
    releases: Dict[str, str] = field(default_factory=dict)

    def add(self, record: CallRecord) -> None:
        self.calls.append(record)

    def note(self, source: str, message: str) -> None:
        self.notes.setdefault(source, [])
        if message not in self.notes[source]:
            self.notes[source].append(message)

    def merge(self, other: "Tracker") -> None:
        self.calls.extend(other.calls)
        for key, values in other.notes.items():
            for value in values:
                self.note(key, value)
        self.releases.update(other.releases)

    def summary(self) -> List[Dict[str, Any]]:
        by_source: Dict[str, List[CallRecord]] = {}
        for call in self.calls:
            by_source.setdefault(call.source, []).append(call)
        rows = []
        for key, info in SOURCES.items():
            calls = by_source.get(key, [])
            notes = self.notes.get(key, [])
            if not calls and not notes:
                continue
            ok = [c for c in calls if c.ok]
            failed = [c for c in calls if not c.ok]
            if calls and not failed:
                status = "ok"
            elif ok and failed:
                status = "partial"
            elif failed:
                status = "failed"
            else:
                status = "skipped"
            rows.append({
                "source": key,
                "name": info.name,
                "status": status,
                "calls": len(calls),
                "failed_calls": len(failed),
                "from_cache": sum(1 for c in calls if c.from_cache),
                "stale_cache": sum(1 for c in calls if c.stale),
                "last_retrieved_at": max((c.fetched_at for c in ok), default=None),
                "errors": sorted({c.error for c in failed if c.error})[:5],
                "notes": notes,
                "release": self.releases.get(key),
                "license": info.license,
                "homepage": info.homepage,
            })
        return rows

    def to_dict(self) -> Dict[str, Any]:
        return {"calls": [asdict(c) for c in self.calls], "notes": self.notes, "releases": self.releases}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _RateLimiter:
    def __init__(self, interval: float) -> None:
        self.interval = interval
        self.lock = asyncio.Lock()
        self.next_slot = 0.0

    async def wait(self) -> None:
        if self.interval <= 0:
            return
        async with self.lock:
            now = time.monotonic()
            delay = self.next_slot - now
            if delay > 0:
                await asyncio.sleep(delay)
            self.next_slot = max(now, self.next_slot) + self.interval


class HttpClient:
    def __init__(self, cfg: Optional[Settings] = None, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self.cfg = cfg or default_settings
        self.transport = transport
        self._memory: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._memory_max = 3000
        self._per_loop: Dict[int, Dict[str, Any]] = {}

    # -- loop-bound resources (asyncio primitives must belong to the running loop)
    def _loop_state(self) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        state = self._per_loop.get(id(loop))
        if state is None or state.get("loop") is not loop:
            client = httpx.AsyncClient(
                transport=self.transport,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
                timeout=httpx.Timeout(self.cfg.http_timeout, connect=10.0),
            )
            state = {"loop": loop, "client": client, "limiters": {}, "semaphores": {}}
            self._per_loop[id(loop)] = state
        return state

    def _limiter(self, source: str) -> _RateLimiter:
        state = self._loop_state()
        group = _LIMITER_GROUP.get(source, source)
        limiter = state["limiters"].get(group)
        if limiter is None:
            interval = SOURCES[source].min_interval
            if group == "ncbi" and self.cfg.ncbi_api_key:
                interval = 0.11
            limiter = _RateLimiter(interval)
            state["limiters"][group] = limiter
        return limiter

    def _semaphore(self, source: str) -> asyncio.Semaphore:
        state = self._loop_state()
        group = _LIMITER_GROUP.get(source, source)
        sem = state["semaphores"].get(group)
        if sem is None:
            sem = asyncio.Semaphore(SOURCES[source].max_concurrency)
            state["semaphores"][group] = sem
        return sem

    # -- cache helpers
    @staticmethod
    def _cache_key(method: str, url: str, params: Optional[Dict[str, Any]], body: Any) -> str:
        clean = {k: v for k, v in sorted((params or {}).items()) if k not in {"api_key", "email"}}
        raw = json.dumps([method.upper(), url, clean, body], sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]

    def _disk_path(self, source: str, key: str) -> Path:
        return self.cfg.cache_dir / source / f"{key}.json"

    def _read_disk(self, source: str, key: str) -> Optional[Dict[str, Any]]:
        if not self.cfg.disk_cache and not self.cfg.offline:
            return None
        path = self._disk_path(source, key)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write_disk(self, source: str, key: str, entry: Dict[str, Any]) -> None:
        if not self.cfg.disk_cache:
            return
        path = self._disk_path(source, key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(entry), encoding="utf-8")
        except OSError:
            pass

    def _remember(self, key: str, entry: Dict[str, Any]) -> None:
        self._memory[key] = entry
        self._memory.move_to_end(key)
        while len(self._memory) > self._memory_max:
            self._memory.popitem(last=False)

    @staticmethod
    def _age_seconds(entry: Dict[str, Any]) -> float:
        try:
            fetched = datetime.fromisoformat(entry["fetched_at"])
            return (datetime.now(timezone.utc) - fetched).total_seconds()
        except (KeyError, ValueError, TypeError):
            return float("inf")

    @staticmethod
    def _decode(entry: Dict[str, Any], expect: str) -> Any:
        body = entry.get("body", "")
        if expect == "json":
            return json.loads(body) if body else None
        return body

    def _ncbi_params(self, source: str, params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if _LIMITER_GROUP.get(source) != "ncbi":
            return params
        merged = dict(params or {})
        merged.setdefault("tool", self.cfg.ncbi_tool)
        if self.cfg.ncbi_email:
            merged.setdefault("email", self.cfg.ncbi_email)
        if self.cfg.ncbi_api_key:
            merged.setdefault("api_key", self.cfg.ncbi_api_key)
        return merged

    async def request(
        self,
        source: str,
        method: str,
        url: str,
        *,
        tracker: Optional[Tracker] = None,
        params: Optional[Dict[str, Any]] = None,
        json_body: Any = None,
        content: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        expect: str = "json",
        timeout: Optional[float] = None,
        allow_status: tuple = (),
        retries: int = 2,
        use_cache: bool = True,
        purpose: str = "",
    ) -> Response:
        """Perform a request with caching, rate limiting and retries.

        Statuses in ``allow_status`` (e.g. 404 for "no record") are returned
        rather than raised, and are cached like successful responses.
        """
        params = self._ncbi_params(source, params)
        body_for_key = json_body if json_body is not None else content
        key = self._cache_key(method, url, params, body_for_key)
        started = time.monotonic()
        display_url = str(httpx.URL(url, params={k: v for k, v in (params or {}).items() if k not in {"api_key", "email"}}))

        def record(ok: bool, status: Optional[int], from_cache: bool, fetched_at: str, error: Optional[str] = None, stale: bool = False) -> None:
            if tracker is not None:
                tracker.add(CallRecord(source, display_url, ok, status, from_cache, stale, int((time.monotonic() - started) * 1000), fetched_at, error, purpose))

        # 1. memory / disk cache
        if use_cache:
            entry = self._memory.get(key) or self._read_disk(source, key)
            if entry is not None and (self.cfg.offline or self._age_seconds(entry) <= self.cfg.cache_ttl_seconds):
                self._remember(key, entry)
                record(True, entry.get("status"), True, entry["fetched_at"])
                return Response(self._decode(entry, expect), entry.get("status", 200), display_url, entry["fetched_at"], True)
            if self.cfg.offline:
                record(False, None, False, _now(), "offline replay mode: response not in cache")
                raise SourceError(source, "offline_miss", "offline replay mode: response not in cache")
            stale_entry = entry
        else:
            stale_entry = None

        # 2. network
        req_headers = {"Accept": "application/json" if expect == "json" else "*/*"}
        req_headers.update(headers or {})
        last_error: Optional[SourceError] = None
        async with self._semaphore(source):
            for attempt in range(retries + 1):
                await self._limiter(source).wait()
                try:
                    client: httpx.AsyncClient = self._loop_state()["client"]
                    resp = await client.request(
                        method, url, params=params, json=json_body, content=content, headers=req_headers,
                        timeout=timeout or self.cfg.http_timeout,
                    )
                except httpx.TimeoutException:
                    last_error = SourceError(source, "timeout", f"timed out after {timeout or self.cfg.http_timeout:.0f}s")
                except httpx.HTTPError as exc:
                    last_error = SourceError(source, "network", f"network error: {exc.__class__.__name__}")
                else:
                    if resp.status_code < 400 or resp.status_code in allow_status:
                        fetched_at = _now()
                        entry = {"url": display_url, "status": resp.status_code, "fetched_at": fetched_at, "body": resp.text}
                        try:
                            data = self._decode(entry, expect)
                        except ValueError:
                            last_error = SourceError(source, "parse", "response was not valid JSON", resp.status_code)
                            break
                        if use_cache:
                            self._remember(key, entry)
                            self._write_disk(source, key, entry)
                        record(True, resp.status_code, False, fetched_at)
                        return Response(data, resp.status_code, display_url, fetched_at, False)
                    last_error = SourceError(source, "http", f"HTTP {resp.status_code}", resp.status_code)
                    if resp.status_code not in RETRY_STATUSES:
                        break
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit() and attempt < retries:
                        await asyncio.sleep(min(float(retry_after), 5.0))
                        continue
                if attempt < retries:
                    await asyncio.sleep(0.8 * (attempt + 1))

        # 3. stale cache as a labelled fallback
        assert last_error is not None
        if stale_entry is not None:
            if tracker is not None:
                tracker.note(source, f"served stale cached response after {last_error.message}")
            record(True, stale_entry.get("status"), True, stale_entry["fetched_at"], None, stale=True)
            return Response(self._decode(stale_entry, expect), stale_entry.get("status", 200), display_url, stale_entry["fetched_at"], True, True)
        record(False, last_error.status, False, _now(), last_error.message)
        raise last_error

    async def get(self, source: str, url: str, **kwargs: Any) -> Response:
        return await self.request(source, "GET", url, **kwargs)

    async def post(self, source: str, url: str, **kwargs: Any) -> Response:
        return await self.request(source, "POST", url, **kwargs)


http_client = HttpClient()
