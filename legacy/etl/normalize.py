from __future__ import annotations

import sys
import re
from pathlib import Path
from typing import Any

repo_root = Path(__file__).resolve().parents[1]
backend_root = repo_root / 'backend'
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

def normalize_graph(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    output: dict[str, Any] = {"genes": [], "variants": [], "relationships": [], "sources": payload.get("sources", {})}
    report = {"records_downloaded": 0, "records_parsed": 0, "records_retained": 0, "duplicate_count": 0, "invalid_count": 0, "missing_identifier_count": 0}
    for kind, fields in (("genes", ("canonical_id", "gene_symbol")), ("variants", ("variant_id", "gene_symbol", "protein_change")), ("relationships", ("source", "target", "relationship"))):
        seen: set[tuple[str, ...]] = set()
        for item in payload.get(kind, []) or []:
            report["records_downloaded"] += 1
            if not isinstance(item, dict):
                report["invalid_count"] += 1
                continue
            report["records_parsed"] += 1
            key = tuple(str(item.get(field) or "") for field in fields)
            if not all(key):
                report["missing_identifier_count"] += 1
            elif key in seen:
                report["duplicate_count"] += 1
            else:
                seen.add(key)
                output[kind].append(item)
                report["records_retained"] += 1
    return output, report


_AA = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def clean_record(raw: Any, source: str = "") -> dict[str, Any] | None:
    """Strip transport noise and discard empty records before mapping."""
    if not isinstance(raw, dict):
        return None
    cleaned: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            value = re.sub(r"<[^>]+>", " ", value)
            value = " ".join(value.split())
        if value not in ("", None, "N/A", "NA", "unknown"):
            cleaned[key] = value
    if source:
        cleaned.setdefault("source_database", source)
    return cleaned


def map_identifiers(record: dict[str, Any]) -> dict[str, Any]:
    """Preserve cross-database identifiers under explicit canonical keys."""
    mapped = dict(record)
    for target, aliases in {
        "gene_symbol": ("gene_symbol", "hgnc_symbol", "gene"),
        "ensembl_id": ("ensembl_id", "canonical_gene_id"),
        "uniprot_accession": ("uniprot_accession", "accession", "primaryAccession"),
        "clinvar_id": ("clinvar_id", "variant_id", "uid"),
    }.items():
        for alias in aliases:
            if mapped.get(alias):
                mapped[target] = str(mapped[alias])
                break
    return mapped


def normalize_variant_notation(text: str) -> str | None:
    """Normalize one- or three-letter amino-acid substitutions to HGVS protein form."""
    match = re.search(r"(?:p\.)?([A-Za-z]{1,3})(\d+)([A-Za-z]{1,3})", text or "")
    if not match:
        return None
    first = _AA.get(match.group(1).upper(), match.group(1).upper()[:1])
    last = _AA.get(match.group(3).upper(), match.group(3).upper()[:1])
    if first not in set(_AA.values()) or last not in set(_AA.values()):
        return None
    return f"p.{first}{match.group(2)}{last}"


def deduplicate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable deduplication by the first available canonical identifier."""
    seen: set[str] = set()
    result = []
    for record in records:
        key = str(record.get("canonical_id") or record.get("variant_id") or record.get("source_id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def validate(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Partition records with identifiers from records that cannot enter the graph."""
    valid, invalid, reasons = [], [], []
    for record in records:
        if record.get("canonical_id") or record.get("variant_id") or record.get("source_id"):
            valid.append(record)
        else:
            invalid.append(record)
            reasons.append("missing canonical identifier")
    return valid, invalid, reasons


def main() -> None:
    from app.services.real_pipeline import RealDataPipeline
    pipeline = RealDataPipeline(repo_root)
    payload = pipeline.run_quick()
    print(f"Normalized {len(payload.get('genes', []))} genes and {len(payload.get('relationships', []))} relationships.")


if __name__ == '__main__':
    main()
