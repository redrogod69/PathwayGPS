from __future__ import annotations

import re
from typing import Any

import httpx


class VariantResolver:
    def __init__(self) -> None:
        self.gene_pattern = re.compile(r"\b(?P<gene>[A-Z][A-Za-z0-9]+)\b")
        self.protein_pattern = re.compile(r"(?:p\.)?(?P<aa1>[A-Za-z])(?P<pos>\d+)(?P<aa2>[A-Za-z])", re.IGNORECASE)

    def canonical_protein_change(self, value: str | None) -> str | None:
        if not value:
            return None
        text = value.strip()
        patterns = [
            r"(?:p\.)?(?P<aa1>[A-Za-z]{1,3})(?P<pos>\d+)(?P<aa2>[A-Za-z]{1,3})(?![A-Za-z])",
            r"(?:p\.)?(?P<aa1>[A-Za-z])(?P<pos>\d+)(?P<aa2>[A-Za-z])(?![A-Za-z])",
        ]
        aa_map = {
            "A": "A", "R": "R", "N": "N", "D": "D", "C": "C", "Q": "Q", "E": "E", "G": "G",
            "H": "H", "I": "I", "L": "L", "K": "K", "M": "M", "F": "F", "P": "P", "S": "S",
            "T": "T", "W": "W", "Y": "Y", "V": "V",
            "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q", "GLU": "E",
            "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F",
            "PRO": "P", "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
        }
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            aa1 = match.group('aa1').upper()
            aa2 = match.group('aa2').upper()
            aa1 = aa_map.get(aa1, aa1[0])
            aa2 = aa_map.get(aa2, aa2[0])
            pos = match.group('pos')
            return f"p.{aa1}{pos}{aa2}"
        return None

    def normalize(self, variant: str) -> dict[str, Any]:
        text = (variant or "").strip()
        gene_symbol = None
        if not re.match(r"^(?:p\.)?[A-Za-z]{1,3}\d+[A-Za-z]{1,3}$", text, re.IGNORECASE):
            gene_match = self.gene_pattern.search(text)
            if gene_match:
                gene_symbol = gene_match.group("gene").upper()
        protein_change = self.canonical_protein_change(text)
        return {
            "input": text,
            "gene_symbol": gene_symbol,
            "protein_change": protein_change,
            "genome_build": "GRCh38",
            "variant_type": "single_amino_acid_change" if protein_change else "gene_symbol_only",
        }

    def resolve(self, variant: str) -> dict[str, Any]:
        normalized = self.normalize(variant)
        gene_symbol = normalized["gene_symbol"]
        if not gene_symbol:
            raise ValueError(f"Unable to parse a gene symbol from: {variant}")
        record = httpx.get(
            f"https://rest.uniprot.org/uniprotkb/search?query=gene:{gene_symbol}+AND+organism_id:9606&format=json&fields=accession,gene_names,protein_name,length,reviewed",
            timeout=30,
        )
        record.raise_for_status()
        payload = record.json()
        result = payload.get("results", [{}])[0]
        normalized["canonical_gene_id"] = result.get("primaryAccession")
        normalized["protein_name"] = result.get("proteinDescription", {}).get("recommendedName", {}).get("fullName", {}).get("value")
        return normalized
