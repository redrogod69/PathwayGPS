"""Variant resolution: from user input to a validated gene / protein / variant context.

Principles enforced here:
* never substitute one variant for another — when several records fit, all are reported;
* a gene-only query is gene-level exploration, never "the first variant in ClinVar";
* the reference residue is checked against the reviewed UniProt sequence;
* every step is logged with its source and outcome so the UI can show *how* the input was interpreted.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.adapters.clinvar import ClinVarAdapter, REVIEW_STARS
from app.adapters.ensembl import EnsemblAdapter, summarize_vep
from app.adapters.uniprot import UniProtAdapter, reference_residue
from app.core.http import HttpClient, SourceError, Tracker
from app.domain.notation import ParsedQuery, ProteinChange, parse_protein_change, parse_query


@dataclass
class Resolution:
    query: str
    parsed: ParsedQuery
    status: str = "pending"  # resolved | protein_level | gene_level | ambiguous | not_found | invalid | error
    message: str = ""
    gene: Optional[Dict[str, Any]] = None
    protein: Optional[Dict[str, Any]] = None
    protein_change: Optional[ProteinChange] = None
    clinvar: Optional[Dict[str, Any]] = None
    clinvar_alternatives: List[Dict[str, Any]] = field(default_factory=list)
    vep: Optional[Dict[str, Any]] = None
    alt_allele: Optional[str] = None
    residue_check: Optional[Dict[str, Any]] = None
    steps: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    resolved_via: List[str] = field(default_factory=list)
    # Coroutines that enrich the resolution but are not needed to decide it (e.g. VEP);
    # the graph builder awaits them concurrently with its own source queries.
    pending: List[Any] = field(default_factory=list, repr=False)

    def step(self, name: str, source: str, outcome: str, detail: str) -> None:
        self.steps.append({"step": name, "source": source, "outcome": outcome, "detail": detail})

    @property
    def has_variant(self) -> bool:
        return self.status in ("resolved", "protein_level")

    def to_dict(self) -> Dict[str, Any]:
        protein = None
        if self.protein:
            protein = {k: v for k, v in self.protein.items() if k not in ("sequence", "features")}
        return {
            "query": self.query,
            "input_type": self.parsed.input_type,
            "parsed": self.parsed.to_dict(),
            "status": self.status,
            "message": self.message,
            "gene": self.gene,
            "protein": protein,
            "protein_change": self.protein_change.to_dict() if self.protein_change else None,
            "clinvar_variation_id": (self.clinvar or {}).get("variation_id"),
            "clinvar_alternatives": [
                {"variation_id": r["variation_id"], "accession": r["accession"], "title": r["title"], "url": r["url"],
                 "query": r["accession"] or r["variation_id"]} for r in self.clinvar_alternatives
            ],
            "alt_allele": self.alt_allele,
            "residue_check": self.residue_check,
            "steps": self.steps,
            "warnings": self.warnings,
            "candidates": self.candidates,
            "resolved_via": self.resolved_via,
        }


def _spdi_parts(spdi: Optional[str]) -> Optional[Dict[str, Any]]:
    # NC_000007.14:55191821:T:G  (0-based position)
    if not spdi or spdi.count(":") != 3:
        return None
    seq, pos, ref, alt = spdi.split(":")
    try:
        start = int(pos) + 1
    except ValueError:
        return None
    return {"seq": seq, "start": start, "ref": ref, "alt": alt, "snv": len(ref) == 1 and len(alt) == 1}


def _record_rank(rec: Dict[str, Any]) -> tuple:
    stars = max([(rec.get(k) or {}).get("stars") or 0 for k in ("germline", "somatic_clinical_impact", "oncogenicity")] or [0])
    return (-stars, -len(rec.get("scv_accessions") or []), rec.get("variation_id") or "")


class VariantResolver:
    def __init__(self, http: HttpClient) -> None:
        self.clinvar = ClinVarAdapter(http)
        self.ensembl = EnsemblAdapter(http)
        self.uniprot = UniProtAdapter(http)

    async def resolve(self, query: str, tracker: Tracker) -> Resolution:
        parsed = parse_query(query)
        res = Resolution(query=query.strip(), parsed=parsed, protein_change=parsed.protein_change)
        if parsed.assembly_note:
            res.warnings.append(parsed.assembly_note)
        res.warnings.extend(parsed.hints)
        res.step("Detect input type", "PathwayGPS", "ok" if parsed.input_type != "invalid" else "failed",
                 f"Interpreted as: {parsed.input_type.replace('_', ' ')}")
        if parsed.input_type == "invalid":
            res.status, res.message = "invalid", " ".join(parsed.problems)
            return res
        try:
            handler = {
                "protein_change": self._protein_change,
                "rsid": self._rsid,
                "transcript_hgvs": self._hgvs,
                "protein_hgvs": self._hgvs,
                "genomic_hgvs": self._hgvs,
                "clinvar_id": self._clinvar_id,
                "gene": self._gene_only,
                "uniprot": self._uniprot_only,
            }[parsed.input_type]
            await handler(res, tracker)
        except SourceError as exc:
            res.status = "error"
            if exc.kind == "offline_miss":
                res.message = ("Offline replay mode is on and this query was not recorded. Only the recorded demo inputs can be analysed "
                               "offline; unset PATHWAYGPS_OFFLINE to query the live databases. No result was fabricated.")
            else:
                res.message = f"A required source failed during resolution ({exc.source}: {exc.message}). No result was fabricated; retry later."
            res.step("Resolution aborted", exc.source, "failed", exc.message)
        return res

    # ------------------------------------------------------------------ gene + protein
    async def _gene(self, symbol: str, res: Resolution, tracker: Tracker) -> bool:
        gene = await self.ensembl.lookup_symbol(symbol, tracker)
        if gene and (gene.get("symbol") or "").upper() == symbol.upper():
            res.gene = gene
            res.step("Gene symbol", "Ensembl", "ok", f"{symbol} → {gene['ensembl_id']} ({gene.get('hgnc_id') or 'HGNC n/a'}), {gene.get('description')}")
            return True
        ids = await self.ensembl.resolve_alias(symbol, tracker)
        genes = [g for g in await asyncio.gather(*(self.ensembl.lookup_id(i, tracker) for i in ids[:6])) if g]
        genes = [g for g in genes if g.get("biotype") == "protein_coding"] or genes
        if len(genes) == 1:
            res.gene = genes[0]
            msg = f"'{symbol}' is not an approved HGNC symbol; Ensembl maps it to {genes[0]['symbol']} ({genes[0]['ensembl_id']}). Results use {genes[0]['symbol']}."
            res.warnings.append(msg)
            res.step("Gene symbol", "Ensembl", "warning", msg)
            return True
        if len(genes) > 1:
            res.status = "ambiguous"
            res.message = f"'{symbol}' matches several genes. Choose the intended gene."
            rest = res.query[len(symbol):].strip() if res.query.upper().startswith(symbol.upper()) else ""
            res.candidates = [{"label": f"{g['symbol']} — {g.get('description')}", "query": f"{g['symbol']} {rest}".strip(),
                               "reason": f"{g['ensembl_id']}, chr{g.get('chromosome')}"} for g in genes]
            res.step("Gene symbol", "Ensembl", "warning", res.message)
            return False
        res.status = "not_found"
        res.message = f"No human gene named '{symbol}' was found in Ensembl (checked approved symbols and aliases)."
        res.step("Gene symbol", "Ensembl", "failed", res.message)
        return False

    async def _fetch_reviewed(self, symbol: str, tracker: Tracker) -> tuple:
        try:
            return await self.uniprot.reviewed_entries_for_gene(symbol, tracker), None
        except SourceError as exc:
            return [], exc

    def _apply_protein(self, res: Resolution, symbol: str, result: tuple) -> None:
        entries, err = result
        if err is not None:
            res.step("Protein", "UniProt", "failed", f"UniProt unavailable: {err.message}")
            res.warnings.append("UniProt was unavailable — protein features and residue validation are missing.")
            return
        exact = [e for e in entries if e["gene_names"] and e["gene_names"][0].upper() == symbol.upper()]
        chosen = (exact or entries or [None])[0]
        if chosen is None:
            res.step("Protein", "UniProt", "warning", f"No reviewed (Swiss-Prot) human entry for {symbol}.")
            res.warnings.append(f"No reviewed UniProt entry for {symbol}; protein-level annotation is unavailable.")
            return
        if len(exact) > 1:
            res.warnings.append(f"{len(exact)} reviewed UniProt entries name {symbol} as primary gene; using {chosen['accession']}.")
        res.protein = chosen
        res.step("Protein", "UniProt", "ok", f"{symbol} → {chosen['accession']} ({chosen['protein_name']}), {chosen['length']} aa, reviewed")

    async def _protein(self, res: Resolution, tracker: Tracker) -> None:
        symbol = res.gene["symbol"]
        self._apply_protein(res, symbol, await self._fetch_reviewed(symbol, tracker))

    async def _fetch_clinvar(self, symbol: str, change: ProteinChange, tracker: Tracker) -> tuple:
        try:
            ids = await self.clinvar.search_protein_change(symbol, change, tracker)
            return await self.clinvar.summaries(ids, tracker), None
        except SourceError as exc:
            return [], exc

    def _check_residue(self, res: Resolution) -> Optional[bool]:
        change = res.protein_change
        if not change or not res.protein:
            return None
        observed = reference_residue(res.protein, change.pos)
        ok = observed == change.ref
        res.residue_check = {"position": change.pos, "expected": change.ref, "observed": observed, "ok": ok,
                             "accession": res.protein["accession"], "length": res.protein["length"]}
        if observed is None:
            detail = f"Position {change.pos} is beyond the end of {res.protein['accession']} ({res.protein['length']} aa)."
        elif ok:
            detail = f"Residue {change.pos} of {res.protein['accession']} (canonical isoform) is {observed}, matching the input."
        else:
            detail = (f"Residue {change.pos} of {res.protein['accession']} (canonical isoform) is {observed}, not {change.ref}. "
                      "The input may use a different isoform/transcript numbering or contain a typo.")
        res.step("Reference residue check", "UniProt", "ok" if ok else "warning", detail)
        if not ok:
            res.warnings.append(detail)
        return ok

    # ------------------------------------------------------------------ VEP
    async def _vep_from_clinvar(self, res: Resolution, tracker: Tracker) -> None:
        rec = res.clinvar or {}
        spdi = _spdi_parts(rec.get("canonical_spdi"))
        loc = rec.get("grch38") or {}
        try:
            if spdi and spdi["snv"] and loc.get("chr"):
                entries = await self.ensembl.vep_region(loc["chr"], spdi["start"], spdi["start"], spdi["alt"], tracker)
                res.alt_allele = spdi["alt"]
            else:
                title = rec.get("title") or ""
                hgvs = title.split(" ")[0].replace(f"({(rec.get('genes') or [''])[0]})", "") if ":c." in title else None
                if not hgvs:
                    res.step("Consequence annotation", "Ensembl VEP", "skipped", "No SNV coordinates or transcript HGVS available for VEP.")
                    return
                entries = await self.ensembl.vep_hgvs(hgvs, tracker)
        except SourceError as exc:
            res.step("Consequence annotation", "Ensembl VEP", "failed", f"VEP unavailable: {exc.message}")
            res.warnings.append("Ensembl VEP did not respond; transcript consequences and SIFT/PolyPhen predictions are missing.")
            return
        if not entries:
            res.step("Consequence annotation", "Ensembl VEP", "warning", "VEP returned no annotation.")
            return
        res.vep = summarize_vep(entries[0], prefer_allele=res.alt_allele, prefer_gene=(res.gene or {}).get("symbol"))
        p = res.vep.get("primary") or {}
        res.step("Consequence annotation", "Ensembl VEP", "ok",
                 f"{', '.join(p.get('consequence_terms') or [])} on {p.get('transcript_id')} (MANE {p.get('mane_select') or 'n/a'}): {p.get('hgvsp') or p.get('hgvsc')}")

    # ------------------------------------------------------------------ handlers
    async def _protein_change(self, res: Resolution, tracker: Tracker) -> None:
        change = res.protein_change
        typed = (res.parsed.gene or "").upper()
        # Speculative: query UniProt and ClinVar with the typed symbol while Ensembl validates it.
        up_task = asyncio.ensure_future(self._fetch_reviewed(typed, tracker))
        cv_task = asyncio.ensure_future(self._fetch_clinvar(typed, change, tracker))
        if not await self._gene(typed, res, tracker):
            up_task.cancel()
            cv_task.cancel()
            return
        symbol = res.gene["symbol"]
        if symbol.upper() != typed:  # alias resolved to another approved symbol: redo with it
            up_task.cancel()
            cv_task.cancel()
            up_task = asyncio.ensure_future(self._fetch_reviewed(symbol, tracker))
            cv_task = asyncio.ensure_future(self._fetch_clinvar(symbol, change, tracker))
        up_result, (records, cv_err) = await asyncio.gather(up_task, cv_task)
        self._apply_protein(res, symbol, up_result)
        clinvar_ok = cv_err is None
        if cv_err is not None:
            res.step("ClinVar lookup", "ClinVar", "failed", f"ClinVar unavailable: {cv_err.message}")
            res.warnings.append("ClinVar was unavailable; clinical classifications and genomic coordinates could not be retrieved.")
        residue_ok = self._check_residue(res)

        exact = [r for r in records if r.get("protein_change") and r["protein_change"]["short"] == change.short
                 and symbol in (r.get("genes") or [symbol])]
        exact.sort(key=_record_rank)
        if clinvar_ok:
            ignored = len(records) - len(exact)
            detail = f"{len(exact)} ClinVar record(s) with exactly {symbol} p.{change.long}"
            if ignored:
                detail += f"; {ignored} other record(s) returned by the search did not match exactly and were ignored"
            res.step("ClinVar lookup", "ClinVar", "ok" if exact else "warning", detail)
        if exact:
            res.clinvar = exact[0]
            res.clinvar_alternatives = exact[1:]
            res.resolved_via.append("ClinVar")
            if res.clinvar_alternatives:
                res.warnings.append(
                    f"p.{change.long} corresponds to {len(exact)} distinct ClinVar records at the nucleotide level "
                    f"({', '.join(r['title'].split(' ')[0] for r in exact[:4])}). Showing {exact[0]['accession']} "
                    "(highest review status); the alternatives are listed and can be opened explicitly.")
            res.pending.append(self._vep_from_clinvar(res, tracker))
            res.status = "resolved"
            res.message = f"Resolved to {res.clinvar['accession']} — {res.clinvar['title']}"
            return

        # No ClinVar record: try Ensembl Variant Recoder (bounded; it was unreliable in testing).
        hgvsg: List[str] = []
        try:
            hgvsg = await self.ensembl.variant_recoder(f"{symbol}:p.{change.long}", tracker)
        except SourceError as exc:
            res.step("Genomic mapping", "Ensembl Variant Recoder", "failed", f"{exc.message} (protein → genomic conversion is slow on the public server)")
        if hgvsg:
            try:
                entries = await self.ensembl.vep_hgvs(hgvsg[0], tracker)
                if entries:
                    vep = summarize_vep(entries[0], prefer_gene=symbol)
                    hgvsp = ((vep.get("primary") or {}).get("hgvsp") or "")
                    if hgvsp.endswith(f"p.{change.long}"):
                        res.vep = vep
                        res.alt_allele = (vep.get("primary") or {}).get("allele")
                        res.resolved_via.append("Ensembl Variant Recoder + VEP")
                        if len(hgvsg) > 1:
                            res.warnings.append(f"{len(hgvsg)} genomic changes encode p.{change.long}; annotated {hgvsg[0]} (alternatives: {', '.join(hgvsg[1:4])}).")
                        res.step("Genomic mapping", "Ensembl Variant Recoder", "ok", f"p.{change.long} → {hgvsg[0]}")
            except SourceError as exc:
                res.step("Consequence annotation", "Ensembl VEP", "failed", exc.message)
        if res.vep:
            res.status = "resolved"
            res.message = f"No ClinVar record exists for {symbol} p.{change.long}; resolved through Ensembl. This variant has no submitted clinical classification."
            return
        if residue_ok is False:
            res.status = "invalid"
            res.message = (f"{symbol} {change.short} could not be resolved: {res.residue_check and res.residue_check.get('observed') or '?'} "
                           f"is the reference residue at position {change.pos}, and no ClinVar record matches. Check the residue or provide transcript-level HGVS.")
            return
        if res.protein is None:
            res.status = "not_found"
            res.message = f"No ClinVar record and no reviewed UniProt protein could be found for {symbol} {change.short}."
            return
        res.status = "protein_level"
        res.message = (f"{symbol} p.{change.long} has no ClinVar record and genomic coordinates could not be determined automatically. "
                       "PathwayGPS shows protein-level context only (residue validated against UniProt). Provide transcript HGVS "
                       "(e.g. NM_…:c.) or an rsID for nucleotide-level annotation.")

    async def _finish_from_vep(self, res: Resolution, tracker: Tracker, entries: List[Dict[str, Any]], via: str,
                               prefer_allele: Optional[str] = None) -> None:
        """Shared path for HGVS / rsID inputs once VEP has answered."""
        vep = summarize_vep(entries[0], prefer_allele=prefer_allele, prefer_gene=res.parsed.gene)
        res.vep = vep
        primary = vep.get("primary") or {}
        symbol = primary.get("gene_symbol")
        res.alt_allele = primary.get("allele")
        res.step("Consequence annotation", "Ensembl VEP", "ok",
                 f"{', '.join(primary.get('consequence_terms') or [])} in {symbol or 'no gene'} ({primary.get('transcript_id')}): {primary.get('hgvsp') or primary.get('hgvsc') or ''}")
        if not symbol:
            res.status = "not_found"
            res.message = "The variant was annotated by VEP but does not overlap a gene transcript, so there is no gene/protein route to follow."
            return
        hgvsp = primary.get("hgvsp") or ""
        if ":p." in hgvsp and not res.protein_change:
            res.protein_change = parse_protein_change(hgvsp.split(":p.")[-1].replace("(", "").replace(")", ""))
        if not await self._gene(symbol, res, tracker):
            return
        await self._protein(res, tracker)
        self._check_residue(res)
        res.resolved_via.append(via)

    async def _match_clinvar_by_position(self, res: Resolution, tracker: Tracker) -> None:
        if not (res.vep and res.gene and res.protein_change):
            return
        try:
            ids = await self.clinvar.search_protein_change(res.gene["symbol"], res.protein_change, tracker)
            records = await self.clinvar.summaries(ids, tracker)
        except SourceError as exc:
            res.step("ClinVar lookup", "ClinVar", "failed", exc.message)
            return
        start = res.vep.get("start")
        matches = []
        for r in records:
            spdi = _spdi_parts(r.get("canonical_spdi"))
            if spdi and spdi["start"] == start and spdi["alt"] == res.alt_allele:
                matches.append(r)
        if matches:
            res.clinvar = sorted(matches, key=_record_rank)[0]
            res.step("ClinVar lookup", "ClinVar", "ok", f"Same genomic change found in ClinVar: {res.clinvar['accession']}")
        else:
            res.step("ClinVar lookup", "ClinVar", "warning", "No ClinVar record for this exact nucleotide change.")

    async def _hgvs(self, res: Resolution, tracker: Tracker) -> None:
        hgvs = res.parsed.hgvs or ""
        clinvar_task = None
        if res.parsed.input_type == "transcript_hgvs" and hgvs.startswith(("NM_", "NR_")):
            clinvar_task = asyncio.ensure_future(self.clinvar.search(f'"{hgvs}"[varname]', tracker))
        try:
            entries = await self.ensembl.vep_hgvs(hgvs, tracker)
        except SourceError as exc:
            if clinvar_task:
                clinvar_task.cancel()
            if exc.status == 400:
                res.status = "invalid"
                res.message = f"Ensembl VEP could not interpret '{hgvs}': {exc.message}"
                res.step("Consequence annotation", "Ensembl VEP", "failed", exc.message)
                return
            raise
        if not entries:
            res.status, res.message = "not_found", f"VEP returned no annotation for {hgvs}."
            return
        await self._finish_from_vep(res, tracker, entries, "Ensembl VEP")
        if res.status in ("ambiguous", "not_found", "invalid"):
            return
        if clinvar_task:
            try:
                ids = await clinvar_task
                recs = await self.clinvar.summaries(ids, tracker)
                if recs:
                    res.clinvar = sorted(recs, key=_record_rank)[0]
                    res.step("ClinVar lookup", "ClinVar", "ok", f"{hgvs} → {res.clinvar['accession']}")
            except SourceError as exc:
                res.step("ClinVar lookup", "ClinVar", "failed", exc.message)
        if res.clinvar is None:
            await self._match_clinvar_by_position(res, tracker)
        res.status = "resolved"
        res.message = f"Resolved {hgvs}" + (f" → {res.clinvar['accession']}" if res.clinvar else " (no ClinVar record for this exact change)")

    async def _rsid(self, res: Resolution, tracker: Tracker) -> None:
        rsid = res.parsed.rsid or ""
        clinvar_task = asyncio.ensure_future(self.clinvar.search(rsid, tracker))
        try:
            entries = await self.ensembl.vep_id(rsid, tracker)
        except SourceError as exc:
            clinvar_task.cancel()
            if exc.status == 400:
                res.status, res.message = "not_found", f"{rsid} is not a known dbSNP identifier in Ensembl ({exc.message})."
                return
            raise
        try:
            records = [r for r in await self.clinvar.summaries(await clinvar_task, tracker) if r.get("rsid") == rsid]
        except SourceError as exc:
            records = []
            res.step("ClinVar lookup", "ClinVar", "failed", exc.message)
        if not entries:
            res.status, res.message = "not_found", f"No Ensembl annotation for {rsid}."
            return
        vep = summarize_vep(entries[0])
        alleles = list(vep.get("per_allele_primary", {}).keys())
        res.step("Allele check", "Ensembl VEP", "ok" if len(alleles) <= 1 else "warning",
                 f"{rsid} allele string {vep.get('allele_string')} → {len(alleles)} alternate allele(s) with consequences")
        if len(records) > 1 or (not records and len(alleles) > 1):
            res.status = "ambiguous"
            res.message = f"{rsid} is multi-allelic ({vep.get('allele_string')}). An rsID names a position, not a single change — choose the allele."
            if records:
                res.candidates = [{"label": r["title"], "query": r["accession"], "reason": "ClinVar record"} for r in sorted(records, key=_record_rank)]
            else:
                res.candidates = [{"label": f"{vep['chromosome']}:g.{vep['start']}{vep['allele_string'].split('/')[0]}>{a} — {tc.get('hgvsp') or tc.get('hgvsc')}",
                                   "query": f"{vep['chromosome']}:g.{vep['start']}{vep['allele_string'].split('/')[0]}>{a}", "reason": "VEP allele"}
                                  for a, tc in vep["per_allele_primary"].items()]
            return
        if records:
            res.clinvar = records[0]
            spdi = _spdi_parts(records[0].get("canonical_spdi"))
            if len(alleles) > 1 and spdi:
                res.warnings.append(f"{rsid} is multi-allelic ({vep.get('allele_string')}); only the {spdi['ref']}>{spdi['alt']} allele has a ClinVar record, and that allele is shown.")
            prefer = spdi["alt"] if spdi else None
            res.parsed.gene = (records[0].get("genes") or [None])[0]
            if records[0].get("protein_change"):
                res.protein_change = parse_protein_change(records[0]["protein_change"]["short"])
            await self._finish_from_vep(res, tracker, [entries[0]], "dbSNP rsID via Ensembl VEP + ClinVar", prefer_allele=prefer)
            if res.status in ("ambiguous", "not_found"):
                return
            res.status = "resolved"
            res.message = f"{rsid} → {res.clinvar['accession']} — {res.clinvar['title']}"
            return
        await self._finish_from_vep(res, tracker, entries, "dbSNP rsID via Ensembl VEP")
        if res.status in ("ambiguous", "not_found"):
            return
        res.status = "resolved"
        res.message = f"{rsid} resolved through Ensembl VEP; no ClinVar record references it."

    async def _clinvar_id(self, res: Resolution, tracker: Tracker) -> None:
        records = await self.clinvar.summaries([res.parsed.clinvar_id or ""], tracker)
        if not records:
            res.status, res.message = "not_found", f"ClinVar has no Variation ID {res.parsed.clinvar_id}."
            return
        rec = records[0]
        res.clinvar = rec
        res.step("ClinVar lookup", "ClinVar", "ok", f"{rec['accession']} — {rec['title']}")
        genes = rec.get("genes") or []
        if len(genes) != 1:
            res.status = "not_found" if not genes else "ambiguous"
            res.message = ("This ClinVar record spans several genes (" + ", ".join(genes[:8]) + "); PathwayGPS follows single-gene variants."
                           if genes else "This ClinVar record is not assigned to a gene.")
            return
        if rec.get("protein_change"):
            res.protein_change = parse_protein_change(rec["protein_change"]["short"])
        if not await self._gene(genes[0], res, tracker):
            return
        await self._protein(res, tracker)
        self._check_residue(res)
        res.pending.append(self._vep_from_clinvar(res, tracker))
        res.resolved_via.append("ClinVar")
        res.status = "resolved"
        res.message = f"Resolved to {rec['accession']} — {rec['title']}"

    async def _gene_only(self, res: Resolution, tracker: Tracker) -> None:
        if not await self._gene(res.parsed.gene or "", res, tracker):
            return
        await self._protein(res, tracker)
        res.status = "gene_level"
        res.message = (f"Gene-level exploration of {res.gene['symbol']}. No variant was given, so none is shown — "
                       "PathwayGPS never picks a variant on your behalf. Add a protein change (e.g. "
                       f"'{res.gene['symbol']} R175H') for variant-level analysis.")

    async def _uniprot_only(self, res: Resolution, tracker: Tracker) -> None:
        entry = await self.uniprot.entry(res.parsed.uniprot or "", tracker)
        if entry is None or not entry.get("gene_names"):
            # Not a UniProt accession after all: try as a gene symbol.
            res.parsed.input_type, res.parsed.gene = "gene", res.parsed.uniprot
            await self._gene_only(res, tracker)
            return
        res.step("Protein", "UniProt", "ok", f"{entry['accession']} → gene {entry['gene_names'][0]}")
        if not await self._gene(entry["gene_names"][0], res, tracker):
            return
        res.protein = entry
        res.status = "gene_level"
        res.message = f"Protein-level exploration of {entry['accession']} ({entry['protein_name']}); no variant was given."


__all__ = ["VariantResolver", "Resolution", "REVIEW_STARS"]
