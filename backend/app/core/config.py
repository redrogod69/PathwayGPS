"""Runtime configuration read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional: load backend/.env or repo .env when python-dotenv is installed
    from dotenv import load_dotenv

    _here = Path(__file__).resolve()
    for candidate in (_here.parents[3] / ".env", _here.parents[2] / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)
except Exception:  # pragma: no cover - dotenv is optional
    pass


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


REPO_ROOT = Path(__file__).resolve().parents[3]


def _path(name: str, default: Path) -> Path:
    """Env path; empty means default. Relative paths resolve against the working directory when
    that location exists, otherwise against the repository root."""
    value = (os.getenv(name) or "").strip()
    if not value:
        return default
    p = Path(value).expanduser()
    if p.is_absolute():
        return p
    return (Path.cwd() / p).resolve() if (Path.cwd() / p).exists() else (REPO_ROOT / p)


@dataclass(frozen=True)
class Settings:
    repo_root: Path = REPO_ROOT
    cache_dir: Path = field(default_factory=lambda: _path("PATHWAYGPS_CACHE_DIR", REPO_ROOT / "data" / "cache"))
    snapshot_dir: Path = field(default_factory=lambda: _path("PATHWAYGPS_SNAPSHOT_DIR", REPO_ROOT / "data" / "snapshots"))
    # Replay mode: only previously cached responses are used; nothing is fetched.
    offline: bool = field(default_factory=lambda: _flag("PATHWAYGPS_OFFLINE"))
    # Disk cache freshness for live mode. Older entries are re-fetched.
    cache_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("PATHWAYGPS_CACHE_TTL") or 7 * 24 * 3600))
    disk_cache: bool = field(default_factory=lambda: _flag("PATHWAYGPS_DISK_CACHE", True))
    http_timeout: float = field(default_factory=lambda: float(os.getenv("PATHWAYGPS_HTTP_TIMEOUT") or 25))
    ncbi_api_key: str = field(default_factory=lambda: os.getenv("NCBI_API_KEY", ""))
    ncbi_email: str = field(default_factory=lambda: os.getenv("NCBI_EMAIL", ""))
    ncbi_tool: str = field(default_factory=lambda: (os.getenv("NCBI_TOOL") or "PathwayGPS"))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    ai_model: str = field(default_factory=lambda: (os.getenv("PATHWAYGPS_AI_MODEL") or "claude-opus-5-5"))


settings = Settings()
