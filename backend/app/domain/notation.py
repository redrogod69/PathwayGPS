"""Input normalisation: detect what the user typed and parse variant notation.

Nothing here contacts a database; it only decides *what kind* of identifier
was entered so the resolver can choose the right sources.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

AA3_TO_1 = {
    "Ala": "A", "Arg": "R", "Asn": "N", "Asp": "D", "Cys": "C", "Gln": "Q", "Glu": "E", "Gly": "G",
    "His": "H", "Ile": "I", "Leu": "L", "Lys": "K", "Met": "M", "Phe": "F", "Pro": "P", "Ser": "S",
    "Thr": "T", "Trp": "W", "Tyr": "Y", "Val": "V", "Ter": "*", "Sec": "U",
}
AA1_TO_3 = {v: k for k, v in AA3_TO_1.items()}
AA1 = set(AA1_TO_3)

_AA3 = "|".join(AA3_TO_1)
PROTEIN_CHANGE_RE = re.compile(
    rf"^(?:p\.)?\(?(?P<ref>{_AA3}|[ACDEFGHIKLMNPQRSTVWYU])(?P<pos>\d{{1,5}})(?P<alt>{_AA3}|[ACDEFGHIKLMNPQRSTVWYU]|\*|X|=|fs\*?\d*|del|dup)\)?$",
    re.IGNORECASE,
)
GENE_SYMBOL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9\-\.]{0,19}$")
RSID_RE = re.compile(r"^rs\d{1,12}$", re.IGNORECASE)
VCV_RE = re.compile(r"^(?:VCV)?0*(\d{1,10})(?:\.\d+)?$", re.IGNORECASE)
CLINVAR_ACC_RE = re.compile(r"^VCV\d{9}(?:\.\d+)?$", re.IGNORECASE)
TRANSCRIPT_HGVS_RE = re.compile(r"^(?P<tx>(?:NM_|NR_|XM_|ENST|LRG_)[\w\.]+?)(?:\((?P<gene>[A-Za-z0-9\-]+)\))?:(?P<kind>[cn])\.(?P<change>\S+)$")
PROTEIN_HGVS_RE = re.compile(r"^(?P<prot>(?:NP_|XP_|ENSP)[\w\.]+?)(?:\((?P<gene>[A-Za-z0-9\-]+)\))?:p\.(?P<change>\S+)$")
GENOMIC_HGVS_RE = re.compile(r"^(?P<seq>NC_0000(?P<chrnum>\d{2})\.(?P<ver>\d+)|(?:chr)?(?P<chr>[0-9]{1,2}|X|Y|MT?))\:g\.(?P<change>\S+)$", re.IGNORECASE)
UNIPROT_ACC_RE = re.compile(r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})(?:-\d+)?$")

# GRCh38 RefSeq chromosome accession versions (NC_0000NN.vv)
GRCH38_NC_VERSIONS = {
    "01": "11", "02": "12", "03": "12", "04": "12", "05": "10", "06": "12", "07": "14", "08": "11",
    "09": "12", "10": "11", "11": "10", "12": "12", "13": "11", "14": "9", "15": "10", "16": "10",
    "17": "11", "18": "10", "19": "10", "20": "11", "21": "9", "22": "11", "23": "11", "24": "10",
}


@dataclass
class ProteinChange:
    ref: str  # one-letter
    pos: int
    alt: str  # one-letter, '*' for stop, or a keyword such as 'fs'
    kind: str  # missense | nonsense | synonymous | frameshift | other

    @property
    def short(self) -> str:
        return f"{self.ref}{self.pos}{self.alt}"

    @property
    def long(self) -> str:
        ref3 = AA1_TO_3.get(self.ref, self.ref)
        alt3 = AA1_TO_3.get(self.alt, self.alt)
        return f"{ref3}{self.pos}{alt3}"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.update({"short": self.short, "long": self.long, "hgvs_short": f"p.{self.short}", "hgvs_long": f"p.{self.long}"})
        return data


def _aa_to_one(token: str) -> Optional[str]:
    if len(token) == 1:
        up = token.upper()
        return up if up in AA1 or up == "*" else None
    for three, one in AA3_TO_1.items():
        if token.lower() == three.lower():
            return one
    return None


def parse_protein_change(text: str) -> Optional[ProteinChange]:
    """Parse p.L858R / L858R / p.Leu858Arg / R213* / R213Ter / V600= notations."""
    if not text:
        return None
    match = PROTEIN_CHANGE_RE.match(text.strip())
    if not match:
        return None
    ref = _aa_to_one(match.group("ref"))
    if ref is None:
        return None
    pos = int(match.group("pos"))
    alt_raw = match.group("alt")
    if alt_raw.lower().startswith("fs"):
        return ProteinChange(ref, pos, "fs", "frameshift")
    if alt_raw.lower() in {"del", "dup"}:
        return ProteinChange(ref, pos, alt_raw.lower(), "other")
    if alt_raw == "=":
        return ProteinChange(ref, pos, ref, "synonymous")
    if alt_raw.upper() == "X":
        return ProteinChange(ref, pos, "*", "nonsense")
    alt = _aa_to_one(alt_raw)
    if alt is None:
        return None
    if alt == "*":
        kind = "nonsense"
    elif alt == ref:
        kind = "synonymous"
    else:
        kind = "missense"
    return ProteinChange(ref, pos, alt, kind)


def protein_change_from_title(title: str) -> Optional[ProteinChange]:
    """Extract the protein change from a ClinVar title like 'NM_..(EGFR):c.2573T>G (p.Leu858Arg)'."""
    match = re.search(r"\(p\.([A-Za-z]{3}\d+(?:[A-Za-z]{3}|=|\*|fs\S*))\)", title or "")
    return parse_protein_change(match.group(1)) if match else None


@dataclass
class ParsedQuery:
    raw: str
    input_type: str  # protein_change | transcript_hgvs | protein_hgvs | genomic_hgvs | rsid | clinvar_id | gene | uniprot | invalid
    gene: Optional[str] = None
    protein_change: Optional[ProteinChange] = None
    hgvs: Optional[str] = None
    rsid: Optional[str] = None
    clinvar_id: Optional[str] = None
    uniprot: Optional[str] = None
    assembly_note: Optional[str] = None
    problems: List[str] = field(default_factory=list)
    hints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["protein_change"] = self.protein_change.to_dict() if self.protein_change else None
        return data


def parse_query(raw: str) -> ParsedQuery:
    text = " ".join((raw or "").strip().split())
    if not text:
        return ParsedQuery(raw, "invalid", problems=["Enter a variant, rsID, HGVS expression, ClinVar ID or gene symbol."])
    if len(text) > 200:
        return ParsedQuery(raw, "invalid", problems=["Input is too long (max 200 characters)."])

    if RSID_RE.match(text):
        return ParsedQuery(raw, "rsid", rsid=text.lower())

    if CLINVAR_ACC_RE.match(text):
        return ParsedQuery(raw, "clinvar_id", clinvar_id=str(int(VCV_RE.match(text).group(1))))

    m = TRANSCRIPT_HGVS_RE.match(text)
    if m:
        hgvs = f"{m.group('tx')}:{m.group('kind')}.{m.group('change')}"
        return ParsedQuery(raw, "transcript_hgvs", gene=(m.group("gene") or None), hgvs=hgvs)

    m = PROTEIN_HGVS_RE.match(text)
    if m:
        return ParsedQuery(raw, "protein_hgvs", gene=(m.group("gene") or None), hgvs=f"{m.group('prot')}:p.{m.group('change')}",
                           protein_change=parse_protein_change(m.group("change")))

    m = GENOMIC_HGVS_RE.match(text)
    if m:
        if m.group("chrnum"):
            chrnum, ver = m.group("chrnum"), m.group("ver")
            if GRCH38_NC_VERSIONS.get(chrnum) != ver:
                return ParsedQuery(raw, "invalid", problems=[
                    f"{m.group('seq')} is not a GRCh38 chromosome accession. PathwayGPS resolves genomic HGVS on GRCh38 only; "
                    f"use NC_0000{chrnum}.{GRCH38_NC_VERSIONS.get(chrnum, '?')} or a transcript-level HGVS expression."])
            return ParsedQuery(raw, "genomic_hgvs", hgvs=text)
        chrom = m.group("chr").upper().replace("CHR", "")
        return ParsedQuery(raw, "genomic_hgvs", hgvs=f"{chrom}:g.{m.group('change')}",
                           assembly_note="No reference sequence accession was given; coordinates were interpreted on GRCh38. "
                                         "If your coordinates are GRCh37/hg19, results will be wrong — use an NC_ accession or transcript HGVS.")

    # "GENE CHANGE", "GENE:p.CHANGE", "GENE p.CHANGE"
    m = re.match(r"^(?P<gene>[A-Za-z][A-Za-z0-9\-\.]{0,19})(?:\s+|:)(?P<change>(?:p\.)?\(?[A-Za-z]{1,3}\d{1,5}\S*)$", text)
    if m:
        change = parse_protein_change(m.group("change"))
        if change:
            return ParsedQuery(raw, "protein_change", gene=m.group("gene").upper(), protein_change=change)
        return ParsedQuery(raw, "invalid", gene=m.group("gene").upper(), problems=[
            f"'{m.group('change')}' is not a supported protein change. Supported: single-residue substitutions such as "
            "L858R, p.Leu858Arg, R213*, or a transcript HGVS expression (e.g. NM_005228.5:c.2573T>G)."])

    if parse_protein_change(text):
        return ParsedQuery(raw, "invalid", problems=[
            f"'{text}' is a protein change without a gene. The same change exists in many proteins; add the gene symbol, e.g. 'EGFR {text}'."])

    if UNIPROT_ACC_RE.match(text) and any(ch.isdigit() for ch in text[1:]) and len(text) in (6, 10) and not text.isalpha():
        # Could also be a gene symbol (rare overlap); the resolver checks UniProt first and falls back to a gene lookup.
        return ParsedQuery(raw, "uniprot", uniprot=text.upper())

    if VCV_RE.match(text) and text.isdigit():
        return ParsedQuery(raw, "clinvar_id", clinvar_id=str(int(text)),
                           hints=["A bare number was interpreted as a ClinVar Variation ID."])

    if GENE_SYMBOL_RE.match(text):
        return ParsedQuery(raw, "gene", gene=text.upper())

    return ParsedQuery(raw, "invalid", problems=[
        "Could not recognise the input. Examples: 'EGFR L858R', 'BRAF p.Val600Glu', 'rs121434568', "
        "'NM_005228.5:c.2573T>G', 'NC_000007.14:g.55191822T>G', 'VCV000016609', or a gene symbol such as 'TP53'."])
