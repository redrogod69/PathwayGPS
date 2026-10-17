"""Graph construction: turn a Resolution plus source records into a typed, evidence-backed graph.

Display limits (documented, not relevance claims):
* pathways: up to MAX_PATHWAYS lowest-level Reactome pathways are drawn initially, ordered by
  (1) pathway name mentions the gene symbol, (2) disease pathways when the variant carries a
  somatic/oncogenic/pathogenic classification, (3) Reactome order. The rest are one click away.
* downstream cascade: for one focus pathway (the first displayed), up to MAX_FOCUS_REACTIONS
  reactions in which the protein participates, and up to MAX_FOLLOWING Reactome following events
  for each. Each reaction's non-small-molecule outputs are drawn (≤2).
* interactors: top MAX_INTERACTORS IntAct partners with MI-score ≥ 0.6, hidden by default.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Awaitable, Dict, List, Optional, Tuple

from app.adapters.civic import CivicAdapter
from app.adapters.clinvar import ClinVarAdapter, germline_group
from app.adapters.ensembl import EnsemblAdapter
from app.adapters.opentargets import OpenTargetsAdapter
from app.adapters.reactome import ReactomeAdapter, browser_url
from app.adapters.uniprot import ECO_LABEL, features_at
from app.core.http import HttpClient, SourceError, Tracker
from app.domain.model import Evidence, Graph, Node, Xref
from app.pipeline.resolver import Resolution

MAX_PATHWAYS = 12
MAX_FOCUS_REACTIONS = 6
MAX_FOLLOWING = 3
MAX_INTERACTORS = 10
MAX_OT_DISEASES = 6
MAX_OT_DRUGS = 6
MAX_CIVIC_THERAPIES = 8
SKIP_TRAITS = {"not provided", "not specified", "see cases", "none provided"}
SALT_WORDS = {"MESYLATE", "TOSYLATE", "HYDROCHLORIDE", "DIHYDROCHLORIDE", "MALEATE", "DIMALEATE", "SULFATE", "CITRATE",
              "PHOSPHATE", "SODIUM", "POTASSIUM", "MONOHYDRATE", "HYDRATE", "ACETATE", "BESYLATE", "FUMARATE", "TARTRATE",
              "SUCCINATE", "DIMESYLATE", "HYDROBROMIDE", "MALATE", "ESYLATE", "CAMSYLATE", "ISETHIONATE"}


async def _safe(coro: Awaitable[Any], tracker: Tracker, source: str, label: str) -> Tuple[Any, Optional[str]]:
    try:
        return await coro, None
    except SourceError as exc:
        tracker.note(source, f"{label}: {exc.message}")
        return None, exc.message
    except Exception as exc:  # defensive: one adapter must never break the analysis
        tracker.note(source, f"{label}: unexpected {exc.__class__.__name__}")
        return None, str(exc)


def drug_key(name: str) -> str:
    words = [w for w in re.split(r"[\s\-]+", (name or "").upper()) if w]
    core = [w for w in words if w not in SALT_WORDS] or words
    return " ".join(core)


def _origin_label(value: Optional[str]) -> Optional[str]:
    return value.lower() if value else None


class AnalysisBuilder:
    def __init__(self, http: HttpClient) -> None:
        self.http = http
        self.clinvar = ClinVarAdapter(http)
        self.reactome = ReactomeAdapter(http)
        self.ot = OpenTargetsAdapter(http)
        self.civic = CivicAdapter(http)
        self.ensembl = EnsemblAdapter(http)

    # ================================================================== entry point
    async def build(self, res: Resolution, tracker: Tracker) -> Dict[str, Any]:
        g = Graph()
        ctx: Dict[str, Any] = {"res": res, "graph": g, "tracker": tracker, "disease_index": {}, "drug_index": {},
                               "gaps": [], "data": {}}
        symbol = (res.gene or {}).get("symbol")
        acc = (res.protein or {}).get("accession")
        ensg = (res.gene or {}).get("ensembl_id")
        change = res.protein_change

        tasks: Dict[str, Awaitable[Any]] = {
            "resolution_enrichment": asyncio.gather(*res.pending),
            "reactome_release": self.reactome.version(tracker),
            "ensembl_release": self.ensembl.release(tracker),
        }
        if res.clinvar:
            tasks["submissions"] = _safe(self.clinvar.submissions(res.clinvar["variation_id"], tracker), tracker, "clinvar", "submissions")
        if acc:
            tasks["pathways"] = _safe(self.reactome.pathways_for_uniprot(acc, tracker), tracker, "reactome", "pathways")
            tasks["reactions"] = _safe(self.reactome.reactions_for_uniprot(acc, tracker), tracker, "reactome", "reactions")
            tasks["interactors"] = _safe(self.reactome.interactors(acc, tracker), tracker, "intact", "interactors")
        if ensg:
            tasks["ot_assoc"] = _safe(self.ot.associations(ensg, tracker, size=12), tracker, "opentargets", "associations")
            tasks["ot_drugs"] = _safe(self.ot.drugs(ensg, symbol or "", tracker), tracker, "opentargets", "drugs")
        if res.has_variant and change and symbol and change.kind in ("missense", "nonsense", "synonymous"):
            tasks["civic"] = _safe(self.civic.evidence_for_variant(symbol, change.short, tracker), tracker, "civic", "evidence")
        res.pending = []
        keys = list(tasks)
        results = await asyncio.gather(*(tasks[k] for k in keys))
        data = dict(zip(keys, results))
        ctx["data"] = data
        if data.get("reactome_release"):
            tracker.releases["reactome"] = str(data["reactome_release"])
        if data.get("ensembl_release"):
            tracker.releases["ensembl"] = str(data["ensembl_release"])

        self._add_root(ctx)
        self._add_gene_protein(ctx)
        self._add_regions(ctx)
        await self._add_reactome(ctx)
        self._add_interactors(ctx)
        self._add_clinvar_conditions(ctx)
        self._add_civic(ctx)
        self._add_clinvar_therapies(ctx)
        self._add_opentargets(ctx)
        self._assign_roles(ctx)
        return ctx

    # ================================================================== helpers
    @staticmethod
    def root_id(res: Resolution) -> str:
        if res.has_variant:
            if res.clinvar:
                return f"variant:clinvar:{res.clinvar['variation_id']}"
            if res.vep and res.vep.get("input"):
                return f"variant:{res.vep['input']}"
            return f"variant:{(res.gene or {}).get('symbol')}:{res.protein_change.short if res.protein_change else res.query}"
        return f"gene:{(res.gene or {}).get('ensembl_id')}"

    # ================================================================== root, gene, protein
    def _add_root(self, ctx: Dict[str, Any]) -> None:
        res: Resolution = ctx["res"]
        g: Graph = ctx["graph"]
        if not res.has_variant:
            return
        cv = res.clinvar or {}
        vep = res.vep or {}
        primary = vep.get("primary") or {}
        change = res.protein_change
        label = f"{res.gene['symbol']} {change.short}" if change and res.gene else (cv.get("title") or res.query)
        flags = []
        germ = (cv.get("germline") or {}).get("description") or ""
        if "uncertain" in germ.lower():
            flags.append("vus")
        if "conflicting" in germ.lower():
            flags.append("conflicting")
        xrefs = []
        if cv:
            xrefs.append(Xref("ClinVar", cv["accession"], cv["url"]))
        rsid = cv.get("rsid") or next(iter((vep.get("colocated") or {}).get("rsids") or []), None)
        if rsid:
            xrefs.append(Xref("dbSNP", rsid, f"https://www.ncbi.nlm.nih.gov/snp/{rsid}"))
        if cv.get("clingen_allele"):
            xrefs.append(Xref("ClinGen Allele Registry", cv["clingen_allele"], f"https://reg.clinicalgenome.org/redmine/projects/registry/genboree_registry/by_caid?caid={cv['clingen_allele']}"))
        if cv.get("uniprot_variant"):
            xrefs.append(Xref("UniProt variant", cv["uniprot_variant"], None))
        for cosv in ((vep.get("colocated") or {}).get("cosmic") or [])[:2]:
            xrefs.append(Xref("COSMIC", cosv, f"https://cancer.sanger.ac.uk/cosmic/search?q={cosv}"))
        g.add_node(Node(
            id=self.root_id(res), type="variant", label=label, source="clinvar" if cv else ("ensembl" if vep else "user"),
            subtitle=cv.get("title") or primary.get("hgvsc") or (f"p.{change.long}" if change else None),
            xrefs=xrefs, role="query", flags=flags,
            attributes={
                "hgvs_c": primary.get("hgvsc") or cv.get("cdna_change"),
                "hgvs_p": primary.get("hgvsp"),
                "protein_change": change.to_dict() if change else None,
                "spdi": cv.get("canonical_spdi"),
                "grch38": cv.get("grch38") or ({"chr": vep.get("chromosome"), "start": vep.get("start"), "stop": vep.get("end")} if vep else None),
                "consequence": primary.get("consequence_terms"),
                "impact": primary.get("impact"),
                "transcript": primary.get("transcript_id"),
                "mane_select": primary.get("mane_select"),
                "sift": {"prediction": primary.get("sift_prediction"), "score": primary.get("sift_score")} if primary.get("sift_prediction") else None,
                "polyphen": {"prediction": primary.get("polyphen_prediction"), "score": primary.get("polyphen_score")} if primary.get("polyphen_prediction") else None,
                "germline": cv.get("germline"),
                "somatic_clinical_impact": cv.get("somatic_clinical_impact"),
                "oncogenicity": cv.get("oncogenicity"),
                "genomic_resolution": "resolved" if (cv or vep) else "not resolved (protein-level only)",
            },
        ))

    def _add_gene_protein(self, ctx: Dict[str, Any]) -> None:
        res: Resolution = ctx["res"]
        g: Graph = ctx["graph"]
        gene = res.gene
        if not gene:
            return
        gid = f"gene:{gene['ensembl_id']}"
        xrefs = [Xref("Ensembl", gene["ensembl_id"], gene["url"])]
        if gene.get("hgnc_id"):
            xrefs.append(Xref("HGNC", gene["hgnc_id"], f"https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/{gene['hgnc_id']}"))
        xrefs.append(Xref("KEGG (external link only)", f"hsa gene {gene['symbol']}", f"https://www.kegg.jp/entry/hsa:{gene['symbol']}"))
        g.add_node(Node(id=gid, type="gene", label=gene["symbol"], source="ensembl", subtitle=gene.get("description"), xrefs=xrefs,
                        role="query" if not res.has_variant else "core",
                        attributes={k: gene.get(k) for k in ("chromosome", "start", "end", "strand", "biotype", "assembly", "canonical_transcript")}))
        root = self.root_id(res)
        cv = res.clinvar
        vep = res.vep or {}
        primary = vep.get("primary") or {}
        if res.has_variant:
            ev: List[Evidence] = []
            if cv:
                ev.append(Evidence("clinvar", cv["accession"], cv["url"], "ClinVar variation record", "curated",
                                   f"ClinVar {cv['accession']} is assigned to gene {', '.join(cv.get('genes') or [gene['symbol']])}.",
                                   retrieved_at=cv.get("retrieved_at")))
            if primary.get("gene_symbol"):
                ev.append(Evidence("ensembl", primary.get("transcript_id") or "VEP", f"https://www.ensembl.org/Homo_sapiens/Transcript/Summary?t={primary.get('transcript_id')}",
                                   "Ensembl VEP transcript consequence", "computational",
                                   f"VEP places the variant in {primary['gene_symbol']} transcript {primary.get('transcript_id')} ({', '.join(primary.get('consequence_terms') or [])}).",
                                   release=ctx["tracker"].releases.get("ensembl"),
                                   method="Ensembl Variant Effect Predictor (rule-based against Ensembl gene models)"))
            if not ev:
                ev.append(Evidence("user", res.query, None, "User-specified gene", "inferred",
                                   f"The gene {gene['symbol']} was given in the query; no genomic record links this exact variant to it.",
                                   inference="Gene taken from the input; residue checked against UniProt only.",
                                   limitations=["No ClinVar or VEP record for this variant."]))
            g.add_edge(root, gid, "VARIANT_IN_GENE", "located in", ev)

        prot = res.protein
        if not prot:
            return
        pid = f"protein:{prot['accession']}"
        g.add_node(Node(id=pid, type="protein", label=prot["accession"], source="uniprot", subtitle=prot.get("protein_name"),
                        xrefs=[Xref("UniProtKB", prot["accession"], prot["url"]),
                               Xref("AlphaFold DB (structure model)", prot["accession"], f"https://alphafold.ebi.ac.uk/entry/{prot['accession']}")],
                        attributes={"protein_name": prot.get("protein_name"), "length": prot.get("length"), "function": prot.get("function"),
                                    "function_pmids": prot.get("function_pmids"), "subcellular_location": prot.get("subcellular_location"),
                                    "uniprot_diseases": prot.get("diseases"), "annotation_score": prot.get("annotation_score"),
                                    "pdb_structures": prot.get("pdb_count"), "entry_name": prot.get("entry_name")}))
        g.add_edge(gid, pid, "GENE_ENCODES_PROTEIN", "encodes", [
            Evidence("uniprot", prot["accession"], prot["url"], "UniProtKB/Swiss-Prot entry", "curated",
                     f"Reviewed UniProt entry {prot['accession']} ({prot.get('protein_name')}) is encoded by {gene['symbol']}.",
                     retrieved_at=prot.get("retrieved_at"))])

        if not res.has_variant or not res.protein_change:
            return
        change = res.protein_change
        ev = []
        if primary.get("hgvsp"):
            score = None
            preds = []
            if primary.get("sift_prediction"):
                preds.append(f"SIFT {primary['sift_prediction']} ({primary.get('sift_score')})")
            if primary.get("polyphen_prediction"):
                preds.append(f"PolyPhen-2 {primary['polyphen_prediction']} ({primary.get('polyphen_score')})")
            ev.append(Evidence("ensembl", primary.get("hgvsp"), f"https://www.ensembl.org/Homo_sapiens/Transcript/Summary?t={primary.get('transcript_id')}",
                               "Ensembl VEP protein consequence", "computational",
                               f"VEP predicts {primary.get('hgvsp')} ({', '.join(primary.get('consequence_terms') or [])}, impact {primary.get('impact')})."
                               + (f" In-silico predictors: {'; '.join(preds)}." if preds else ""),
                               release=ctx["tracker"].releases.get("ensembl"),
                               method="VEP consequence calling; SIFT and PolyPhen-2 are computational predictions (ACMG PP3/BP4 supporting level only)",
                               score={"name": "SIFT / PolyPhen-2", "value": "; ".join(preds), "meaning": "computational predictions of tolerance; not evidence of pathogenicity on their own"} if preds else score))
        if cv and cv.get("protein_change") and cv["protein_change"]["short"] == change.short:
            ev.append(Evidence("clinvar", cv["accession"], cv["url"], "ClinVar HGVS expression", "curated",
                               f"ClinVar describes {cv['accession']} as {cv['title']}.", retrieved_at=cv.get("retrieved_at")))
        at = features_at(prot, change.pos)
        for f in at["at_residue"]:
            if f["type"] == "Natural variant" and change.alt in (f.get("alternatives") or []):
                ev.append(Evidence("uniprot", f.get("feature_id") or f"{prot['accession']}:{change.pos}", prot["url"] + "#variants",
                                   "UniProt natural-variant annotation", "curated",
                                   f"UniProt annotates {change.ref}{change.pos}{change.alt}: {f['description']}",
                                   publications=f.get("pmids", [])[:12], retrieved_at=prot.get("retrieved_at"),
                                   method=", ".join(ECO_LABEL.get(c, c) for c in f.get("evidence_codes", []))))
            elif f["type"] == "Mutagenesis":
                ev.append(Evidence("uniprot", f"{prot['accession']}:mutagen:{f['start']}", prot["url"] + "#function",
                                   "UniProt mutagenesis annotation", "experimental",
                                   f"Mutagenesis {f.get('original') or change.ref}{f['start']}→{'/'.join(f.get('alternatives') or [])}: {f['description']}",
                                   publications=f.get("pmids", [])[:12], retrieved_at=prot.get("retrieved_at"),
                                   limitations=[] if change.alt in (f.get("alternatives") or []) else
                                   [f"Mutagenesis tested {'/'.join(f.get('alternatives') or [])}, not {change.alt}; same residue only."]))
        if res.residue_check and res.residue_check.get("ok"):
            ev.append(Evidence("uniprot", f"{prot['accession']}:{change.pos}", prot["url"] + "#sequences", "Reference sequence check", "inferred",
                               f"Residue {change.pos} of the UniProt canonical sequence is {change.ref}, consistent with p.{change.long}.",
                               inference="PathwayGPS compared the input reference residue with the UniProt canonical sequence."))
        g.add_edge(root, pid, "VARIANT_ALTERS_PROTEIN", f"p.{change.short}", ev,
                   attributes={"position": change.pos, "ref": change.ref, "alt": change.alt})

    def _add_regions(self, ctx: Dict[str, Any]) -> None:
        res: Resolution = ctx["res"]
        g: Graph = ctx["graph"]
        prot = res.protein
        if not (prot and res.has_variant and res.protein_change):
            return
        pos = res.protein_change.pos
        at = features_at(prot, pos, window=5)
        ctx["data"]["features_at"] = at
        root = self.root_id(res)
        pid = f"protein:{prot['accession']}"
        for f in at["covering"]:
            if f["type"] == "Modified residue" and f["start"] != pos:
                continue
            rid = f"region:{prot['accession']}:{f['type']}:{f['start']}-{f['end']}"
            name = f["description"] or f["type"]
            g.add_node(Node(id=rid, type="protein_region", label=name if len(name) < 40 else name[:38] + "…",
                            subtitle=f"{f['type']} {f['start']}–{f['end']}", source="uniprot",
                            xrefs=[Xref("UniProtKB feature", f"{prot['accession']} {f['start']}-{f['end']}", prot["url"] + "#family_and_domains")],
                            attributes={"feature_type": f["type"], "start": f["start"], "end": f["end"], "description": f["description"],
                                        "evidence_codes": f["evidence_codes"], "evidence_labels": [ECO_LABEL.get(c, c) for c in f["evidence_codes"]],
                                        "evidence_sources": f["evidence_sources"]}))
            g.add_edge(pid, rid, "PROTEIN_HAS_REGION", "has feature", [
                Evidence("uniprot", f"{prot['accession']}:{f['type']}:{f['start']}-{f['end']}", prot["url"] + "#family_and_domains",
                         f"UniProt feature annotation ({f['type']})", f["category"],
                         f"UniProt annotates {f['type'].lower()} '{f['description'] or f['type']}' at residues {f['start']}–{f['end']} of {prot['accession']}.",
                         publications=f["pmids"][:10], retrieved_at=prot.get("retrieved_at"),
                         method=", ".join(ECO_LABEL.get(c, c) for c in f["evidence_codes"]) or None,
                         limitations=["Feature boundary predicted from a sequence model (e.g. PROSITE ProRule), not determined experimentally."]
                         if f["category"] == "computational" else [])])
            g.add_edge(root, rid, "VARIANT_IN_PROTEIN_REGION", "falls within", [
                Evidence("uniprot", f"{prot['accession']}:{pos}", prot["url"] + "#family_and_domains", "Coordinate overlap", "inferred",
                         f"Residue {pos} lies within {f['type'].lower()} {f['start']}–{f['end']} ('{f['description'] or f['type']}').",
                         inference="PathwayGPS computed the overlap between the variant position and UniProt feature coordinates.",
                         limitations=["Location inside a feature does not by itself establish a functional effect."])])

    # ================================================================== Reactome
    def _rank_pathways(self, ctx: Dict[str, Any], pathways: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        res: Resolution = ctx["res"]
        symbol = (res.gene or {}).get("symbol", "").upper()
        cv = res.clinvar or {}
        disease_context = any(
            k in " ".join(str((cv.get(b) or {}).get("description") or "") for b in ("germline", "somatic_clinical_impact", "oncogenicity")).lower()
            for k in ("pathogenic", "oncogenic", "tier i", "tier ii", "conflicting"))
        indexed = list(enumerate(pathways))

        def key(item: Tuple[int, Dict[str, Any]]) -> tuple:
            idx, p = item
            mentions = bool(symbol) and re.search(rf"\b{re.escape(symbol)}\b", p["name"].upper()) is not None
            return (0 if mentions else 1, 0 if (disease_context and p["isInDisease"]) else 1, idx)

        return [p for _, p in sorted(indexed, key=key)]

    async def _add_reactome(self, ctx: Dict[str, Any]) -> None:
        res: Resolution = ctx["res"]
        g: Graph = ctx["graph"]
        tracker: Tracker = ctx["tracker"]
        data = ctx["data"]
        prot = res.protein
        if not prot:
            return
        pid = f"protein:{prot['accession']}"
        pathways, perr = data.get("pathways") or (None, None)
        reactions, rerr = data.get("reactions") or (None, None)
        pathways = pathways or []
        reactions = reactions or []
        ctx["data"]["all_pathways"] = pathways
        ctx["data"]["all_reactions"] = reactions
        if perr is None and not pathways:
            ctx["gaps"].append({"kind": "no_pathways", "message": f"Reactome maps no pathways to {prot['accession']}. Pathway-level navigation is not possible for this protein."})
        ranked = self._rank_pathways(ctx, pathways)
        shown = ranked[:MAX_PATHWAYS]
        ctx["data"]["pathways_shown"] = [p["stId"] for p in shown]

        # Pathway details (summation + literature) and hierarchy, concurrently.
        detail_task = _safe(self.reactome.query_ids([p["stId"] for p in shown], tracker), tracker, "reactome", "pathway details")
        anc_tasks = [_safe(self.reactome.ancestors(p["stId"], tracker), tracker, "reactome", "hierarchy") for p in shown]
        details_res, *anc_res = await asyncio.gather(detail_task, *anc_tasks)
        details = details_res[0] or {}
        for p, (anc, _) in zip(shown, anc_res):
            tops = sorted({path[-1]["name"] for path in (anc or []) if path})
            p["top_level"] = tops
        for p in shown:
            self._add_pathway_node(ctx, p, details.get(p["stId"]))
            g.add_edge(pid, f"reactome:{p['stId']}", "PROTEIN_PARTICIPATES_IN_PATHWAY", "participates in", [self._pathway_membership_evidence(ctx, p, details.get(p["stId"]))])

        # Curated mutant entity for this exact variant (strict name match in disease pathways)
        hits: List[Dict[str, Any]] = []
        if res.has_variant and res.protein_change and res.gene and res.protein_change.kind in ("missense", "nonsense", "synonymous"):
            hits, herr = await _safe(self.reactome.find_variant_entities(res.gene["symbol"], res.protein_change.short, ranked, tracker),
                                     tracker, "reactome", "variant entity lookup")
            hits = hits or []
            if herr:
                ctx["gaps"].append({"kind": "reactome_variant_entity_unknown",
                                    "message": "Reactome participant lookup failed, so it is unknown whether Reactome curates this exact mutant protein."})
            elif not hits:
                ctx["gaps"].append({"kind": "no_reactome_variant_entity",
                                    "message": f"No Reactome disease pathway contains an entity named exactly '{res.gene['symbol']} {res.protein_change.short}'. "
                                               "Pathway context below describes the wild-type protein."})
        ctx["data"]["variant_entities"] = hits
        if hits:
            root = self.root_id(res)
            hit_pathways = {h["pathway"] for h in hits}
            missing = [p for p in ranked if p["stId"] in hit_pathways and p["stId"] not in {x["stId"] for x in shown}]
            for p in missing:
                self._add_pathway_node(ctx, p, None)
                g.add_edge(pid, f"reactome:{p['stId']}", "PROTEIN_PARTICIPATES_IN_PATHWAY", "participates in", [self._pathway_membership_evidence(ctx, p, None)])
                shown.append(p)
                ctx["data"]["pathways_shown"].append(p["stId"])
            for h in hits:
                eid = f"reactome:{h['stId']}"
                g.add_node(Node(id=eid, type="reactome_entity", label=h["name"].split(" [")[0], subtitle=f"Reactome mutant entity · {h['name'].split(' [')[-1].rstrip(']') if ' [' in h['name'] else ''}",
                                source="reactome", xrefs=[Xref("Reactome", h["stId"], h["url"])], role="core",
                                attributes={"full_name": h["name"], "member_of_set": h.get("via_set"), "pathway": h["pathway_name"]}))
                statement = f"Reactome curates '{h['name']}'" + (f" as a member of '{h['via_set']['name']}'" if h.get("via_set") else "") + f" in '{h['pathway_name']}'."
                g.add_edge(root, eid, "VARIANT_REPRESENTED_AS", "curated as", [
                    Evidence("reactome", h["stId"], h["url"], "Reactome curated mutant entity", "curated", statement,
                             release=tracker.releases.get("reactome"),
                             inference=f"Matched by exact entity name '{res.gene['symbol']} {res.protein_change.short}' within Reactome disease-pathway participants.")])
                g.add_edge(eid, f"reactome:{h['pathway']}", "MUTANT_ENTITY_IN_PATHWAY", "participates in", [
                    Evidence("reactome", h["pathway"], h["url"], "Reactome pathway participant", "curated",
                             f"'{h['name']}' participates in '{h['pathway_name']}'" + (f" via the set '{h['via_set']['name']}'." if h.get("via_set") else "."),
                             release=tracker.releases.get("reactome"))])
            hit_order = [p for p in shown if p["stId"] in hit_pathways]
            if hit_order:
                shown = hit_order + [p for p in shown if p["stId"] not in hit_pathways]

        # Downstream cascade for the focus pathway
        if shown and reactions:
            ctx["data"]["focus_reason"] = ("contains the curated entity for this exact variant" if hits else
                                           "first pathway in display order (no variant-specific Reactome entity found)")
            await self._add_focus_cascade(ctx, shown[0], reactions)

    def _add_pathway_node(self, ctx: Dict[str, Any], p: Dict[str, Any], detail: Optional[Dict[str, Any]]) -> None:
        g: Graph = ctx["graph"]
        flags = ["disease_pathway"] if p.get("isInDisease") else []
        if p.get("isInferred"):
            flags.append("orthology_inferred")
        g.add_node(Node(id=f"reactome:{p['stId']}", type="pathway", label=p["name"], source="reactome",
                        subtitle=", ".join(p.get("top_level") or []) or "Reactome pathway",
                        xrefs=[Xref("Reactome", p["stId"], p["url"])] + ([Xref("DOI", detail["doi"], f"https://doi.org/{detail['doi']}")] if detail and detail.get("doi") else []),
                        flags=flags,
                        attributes={"top_level": p.get("top_level"), "is_in_disease": p.get("isInDisease"), "is_inferred": p.get("isInferred"),
                                    "has_diagram": p.get("hasDiagram"), "release_date": p.get("releaseDate"), "last_updated": p.get("lastUpdatedDate"),
                                    "summation": (detail or {}).get("summation"), "review_status": (detail or {}).get("reviewStatus"),
                                    "literature": (detail or {}).get("literature", [])[:10]}))

    def _pathway_membership_evidence(self, ctx: Dict[str, Any], p: Dict[str, Any], detail: Optional[Dict[str, Any]]) -> Evidence:
        res: Resolution = ctx["res"]
        pmids = [r["pmid"] for r in (detail or {}).get("literature", []) if r.get("pmid")][:8]
        return Evidence("reactome", p["stId"], p["url"], "Reactome pathway membership (curated)",
                        "inferred" if p.get("isInferred") else "curated",
                        f"Reactome maps {res.protein['accession']} to the lowest-level pathway '{p['name']}'.",
                        publications=pmids, retrieved_at=p.get("retrieved_at"), release=ctx["tracker"].releases.get("reactome"),
                        inference="Event inferred from another species by orthology (Reactome)." if p.get("isInferred") else None,
                        limitations=["Pathway references describe the pathway as a whole, not necessarily this protein's specific role."] if pmids else
                        ["No literature reference recorded on the pathway object; see the participating reactions."])

    async def _add_focus_cascade(self, ctx: Dict[str, Any], focus: Dict[str, Any], reactions: List[Dict[str, Any]]) -> None:
        tracker: Tracker = ctx["tracker"]
        contained, err = await _safe(self.reactome.contained_event_ids(focus["stId"], tracker), tracker, "reactome", "focus pathway events")
        if not contained:
            return
        involved = {r["stId"]: r for r in reactions}
        in_focus = [involved[s] for s in contained if s in involved]
        in_focus.sort(key=lambda r: (r.get("isInferred", False), 0 if r.get("isInDisease") == focus.get("isInDisease") else 1))
        await self.expand_reactions(ctx, [r["stId"] for r in in_focus[:MAX_FOCUS_REACTIONS]], focus["stId"], follow=True)
        ctx["data"]["focus_pathway"] = {"stId": focus["stId"], "name": focus["name"], "reactions_involving_protein": len(in_focus),
                                        "reason": ctx["data"].get("focus_reason")}

    async def expand_reactions(self, ctx: Dict[str, Any], reaction_ids: List[str], pathway_st_id: Optional[str], follow: bool = True) -> None:
        """Add reactions the protein participates in, their outputs and following events."""
        res: Resolution = ctx["res"]
        g: Graph = ctx["graph"]
        tracker: Tracker = ctx["tracker"]
        if not reaction_ids or not res.protein:
            return
        pid = f"protein:{res.protein['accession']}"
        details, _ = await _safe(self.reactome.query_ids(reaction_ids, tracker), tracker, "reactome", "reaction details")
        details = details or {}
        following: Dict[str, List[Dict[str, Any]]] = {}
        if follow:
            fol = await asyncio.gather(*(_safe(self.reactome.following_events(r, tracker), tracker, "reactome", "following events") for r in reaction_ids))
            following = {r: (f[0] or [])[:MAX_FOLLOWING] for r, f in zip(reaction_ids, fol)}
            fids = [f["stId"] for lst in following.values() for f in lst if f["stId"] not in details]
            more, _ = await _safe(self.reactome.query_ids(fids, tracker), tracker, "reactome", "downstream reaction details") if fids else ({}, None)
            details.update(more or {})
        for rid in reaction_ids:
            d = details.get(rid)
            if not d:
                continue
            node = self._add_reaction_node(ctx, d, role="downstream")
            g.add_edge(pid, node.id, "PROTEIN_PARTICIPATES_IN_REACTION", "participates in", [self._reaction_evidence(ctx, d,
                       f"Reactome curates {res.protein['accession']} ({res.gene['symbol'] if res.gene else ''}) as a participant of '{d['name']}'.")])
            if pathway_st_id and g.has_node(f"reactome:{pathway_st_id}"):
                g.add_edge(node.id, f"reactome:{pathway_st_id}", "REACTION_PART_OF_PATHWAY", "part of", [
                    Evidence("reactome", pathway_st_id, browser_url(rid, pathway_st_id), "Reactome event hierarchy", "curated",
                             f"'{d['name']}' is an event of pathway {pathway_st_id} in Reactome.", retrieved_at=d.get("retrieved_at"),
                             release=tracker.releases.get("reactome"))])
            self._add_outputs(ctx, d, node.id)
            for f in following.get(rid, []):
                fd = details.get(f["stId"])
                if not fd:
                    continue
                fnode = self._add_reaction_node(ctx, fd, role="downstream")
                g.add_edge(node.id, fnode.id, "REACTION_PRECEDES", "precedes", [self._reaction_evidence(ctx, fd,
                           f"Reactome records '{d['name']}' as a preceding event of '{fd['name']}'.", ordering=True)])
                self._add_outputs(ctx, fd, fnode.id)

    async def expand_downstream(self, ctx: Dict[str, Any], reaction_st_id: str) -> int:
        """Follow Reactome followingEvent links from one reaction (one hop)."""
        g: Graph = ctx["graph"]
        tracker: Tracker = ctx["tracker"]
        src = f"reactome:{reaction_st_id}"
        if src not in g.nodes:
            return 0
        fol, _ = await _safe(self.reactome.following_events(reaction_st_id, tracker), tracker, "reactome", "following events")
        fol = (fol or [])[:6]
        if not fol:
            return 0
        details, _ = await _safe(self.reactome.query_ids([f["stId"] for f in fol], tracker), tracker, "reactome", "downstream reaction details")
        src_name = g.nodes[src].label
        added = 0
        for f in fol:
            fd = (details or {}).get(f["stId"])
            if not fd:
                continue
            node = self._add_reaction_node(ctx, fd, role="downstream")
            g.add_edge(src, node.id, "REACTION_PRECEDES", "precedes", [self._reaction_evidence(ctx, fd,
                       f"Reactome records '{src_name}' as a preceding event of '{fd['name']}'.", ordering=True)])
            self._add_outputs(ctx, fd, node.id)
            added += 1
        return added

    async def expand_consumers(self, ctx: Dict[str, Any], entity_st_id: str) -> int:
        """Reactions that consume a physical entity (Reactome consumedByEvent)."""
        g: Graph = ctx["graph"]
        tracker: Tracker = ctx["tracker"]
        src = f"reactome:{entity_st_id}"
        if src not in g.nodes:
            return 0
        rows, _ = await _safe(self.reactome.consumed_by(entity_st_id, tracker), tracker, "reactome", "consuming reactions")
        rows = (rows or [])[:6]
        details, _ = await _safe(self.reactome.query_ids([r["stId"] for r in rows], tracker), tracker, "reactome", "reaction details") if rows else ({}, None)
        added = 0
        for r in rows:
            d = (details or {}).get(r["stId"])
            if not d:
                continue
            node = self._add_reaction_node(ctx, d, role="downstream")
            g.add_edge(src, node.id, "ENTITY_INPUT_OF_REACTION", "input of", [self._reaction_evidence(ctx, d,
                       f"Reactome lists '{g.nodes[src].attributes.get('full_name') or g.nodes[src].label}' as an input of '{d['name']}'.")])
            self._add_outputs(ctx, d, node.id)
            added += 1
        return added

    async def expand_pathway(self, ctx: Dict[str, Any], pathway_st_id: str) -> int:
        tracker: Tracker = ctx["tracker"]
        reactions = ctx["data"].get("all_reactions") or []
        contained, _ = await _safe(self.reactome.contained_event_ids(pathway_st_id, tracker), tracker, "reactome", "pathway events")
        involved = {r["stId"] for r in reactions}
        ids = [s for s in (contained or []) if s in involved][:8]
        before = len(ctx["graph"].nodes)
        await self.expand_reactions(ctx, ids, pathway_st_id, follow=False)
        return len(ctx["graph"].nodes) - before

    async def expand_all_pathways(self, ctx: Dict[str, Any]) -> int:
        res: Resolution = ctx["res"]
        g: Graph = ctx["graph"]
        tracker: Tracker = ctx["tracker"]
        pathways = ctx["data"].get("all_pathways") or []
        shown = set(ctx["data"].get("pathways_shown") or [])
        rest = [p for p in pathways if p["stId"] not in shown]
        if not rest or not res.protein:
            return 0
        details, _ = await _safe(self.reactome.query_ids([p["stId"] for p in rest], tracker), tracker, "reactome", "pathway details")
        anc = await asyncio.gather(*(_safe(self.reactome.ancestors(p["stId"], tracker), tracker, "reactome", "hierarchy") for p in rest))
        pid = f"protein:{res.protein['accession']}"
        for p, (a, _) in zip(rest, anc):
            p["top_level"] = sorted({path[-1]["name"] for path in (a or []) if path})
            self._add_pathway_node(ctx, p, (details or {}).get(p["stId"]))
            g.add_edge(pid, f"reactome:{p['stId']}", "PROTEIN_PARTICIPATES_IN_PATHWAY", "participates in",
                       [self._pathway_membership_evidence(ctx, p, (details or {}).get(p["stId"]))])
            shown.add(p["stId"])
        ctx["data"]["pathways_shown"] = list(shown)
        return len(rest)

    def _add_reaction_node(self, ctx: Dict[str, Any], d: Dict[str, Any], role: str) -> Node:
        g: Graph = ctx["graph"]
        flags = []
        if d.get("isInDisease"):
            flags.append("disease_event")
        if d.get("isInferred"):
            flags.append("orthology_inferred")
        return g.add_node(Node(id=f"reactome:{d['stId']}", type="reaction", label=d["name"], source="reactome",
                               subtitle=f"{d.get('schemaClass') or 'Reaction'}" + (" · disease variant event" if d.get("isInDisease") else ""),
                               xrefs=[Xref("Reactome", d["stId"], d["url"])], role=role, flags=flags,
                               attributes={"inputs": d.get("inputs"), "outputs": d.get("outputs"), "catalysts": d.get("catalysts"),
                                           "regulators": d.get("regulators"), "compartments": d.get("compartments"),
                                           "summation": d.get("summation"), "literature": d.get("literature", [])[:12],
                                           "diseases": d.get("diseases"), "review_status": d.get("reviewStatus"),
                                           "release_date": d.get("releaseDate"), "is_inferred": d.get("isInferred")}))

    def _reaction_evidence(self, ctx: Dict[str, Any], d: Dict[str, Any], statement: str, ordering: bool = False) -> Evidence:
        pmids = [r["pmid"] for r in d.get("literature", []) if r.get("pmid")][:10]
        lim = []
        if not pmids:
            lim.append("Reactome lists no literature reference on this reaction.")
        if d.get("isInDisease"):
            lim.append("Disease-variant event: Reactome models a class of mutant proteins; check that it includes this variant.")
        return Evidence("reactome", d["stId"], d["url"],
                        "Reactome event ordering (precedingEvent)" if ordering else "Reactome curated reaction",
                        "inferred" if d.get("isInferred") else "curated", statement, publications=pmids,
                        retrieved_at=d.get("retrieved_at"), release=ctx["tracker"].releases.get("reactome"),
                        review_status=d.get("reviewStatus"),
                        inference="Reaction inferred from another species by orthology (Reactome)." if d.get("isInferred") else None,
                        limitations=lim, context={"summation": (d.get("summation") or "")[:400]})

    def _add_outputs(self, ctx: Dict[str, Any], d: Dict[str, Any], reaction_node_id: str) -> None:
        g: Graph = ctx["graph"]
        outputs = [o for o in d.get("outputs", []) if o.get("schemaClass") not in ("SimpleEntity", "ChemicalDrug")][:2]
        for o in outputs:
            eid = f"reactome:{o['stId']}"
            g.add_node(Node(id=eid, type="physical_entity", label=o["name"].split(" [")[0][:48], subtitle=o.get("schemaClass"), source="reactome",
                            xrefs=[Xref("Reactome", o["stId"], browser_url(o["stId"]))], role="downstream",
                            flags=["disease_entity"] if o.get("inDisease") else [],
                            attributes={"full_name": o["name"], "schema_class": o.get("schemaClass")}))
            g.add_edge(reaction_node_id, eid, "REACTION_PRODUCES", "produces", [
                Evidence("reactome", d["stId"], d["url"], "Reactome reaction output", "inferred" if d.get("isInferred") else "curated",
                         f"Reactome lists '{o['name']}' as an output of '{d['name']}'.", retrieved_at=d.get("retrieved_at"),
                         release=ctx["tracker"].releases.get("reactome"),
                         publications=[r["pmid"] for r in d.get("literature", []) if r.get("pmid")][:5])])

    # ================================================================== interactors
    def _add_interactors(self, ctx: Dict[str, Any]) -> None:
        res: Resolution = ctx["res"]
        g: Graph = ctx["graph"]
        rows, err = ctx["data"].get("interactors") or (None, None)
        if not res.protein or not rows:
            return
        pid = f"protein:{res.protein['accession']}"
        ctx["data"]["interactor_total"] = len(rows)
        for it in [r for r in rows if (r.get("score") or 0) >= 0.6][:MAX_INTERACTORS]:
            if not it.get("accession") or it["accession"] == res.protein["accession"]:
                continue
            nid = f"protein:{it['accession']}"
            g.add_node(Node(id=nid, type="interactor", label=it.get("alias") or it["accession"], subtitle=f"IntAct MI-score {it.get('score')}",
                            source="intact", xrefs=[Xref("UniProtKB", it["accession"], f"https://www.uniprot.org/uniprotkb/{it['accession']}/entry")],
                            role="secondary", secondary=True, attributes={"mi_score": it.get("score"), "evidence_count": it.get("evidence_count")}))
            g.add_edge(pid, nid, "PROTEIN_INTERACTS_WITH_PROTEIN", "interacts with", [
                Evidence("intact", f"{res.protein['accession']}-{it['accession']}", it.get("intact_url"), "IntAct molecular interaction", "experimental",
                         f"IntAct records {it.get('evidence_count')} interaction evidence(s) between {res.gene['symbol'] if res.gene else res.protein['accession']} and {it.get('alias') or it['accession']}.",
                         retrieved_at=it.get("retrieved_at"),
                         score={"name": "IntAct MI-score", "value": it.get("score"),
                                "meaning": "0–1 composite of detection methods, interaction types and publications; not a probability"},
                         limitations=["Physical interaction evidence for the wild-type proteins; says nothing about the variant's effect."])],
                       secondary=True)

    # ================================================================== diseases & drugs
    def _disease_node(self, ctx: Dict[str, Any], name: str, ids: List[str], source: str, attrs: Optional[Dict[str, Any]] = None,
                      url: Optional[str] = None) -> str:
        """Create or reuse a disease node; nodes merge only on a shared ontology identifier."""
        g: Graph = ctx["graph"]
        index: Dict[str, str] = ctx["disease_index"]
        norm = []
        for i in ids:
            if not i:
                continue
            i = str(i).replace("_", ":")
            prefix, _, rest = i.partition(":")
            norm.append(f"{prefix.upper()}:{rest}" if rest else i)
        existing = next((index[i] for i in norm if i in index), None)
        if existing:
            node = g.nodes[existing]
            harmonized = node.attributes.setdefault("harmonized_sources", [])
            if source not in harmonized:
                harmonized.append(source)
            for i in norm:
                index.setdefault(i, existing)
                db = i.split(":")[0]
                if not any(x.id == i for x in node.xrefs):
                    node.xrefs.append(Xref(db, i, None))
            return existing
        primary = next((i for i in norm if i.startswith("MONDO:")), None) or (norm[0] if norm else f"NAME:{name.lower()}")
        nid = f"disease:{primary}"
        g.add_node(Node(id=nid, type="disease", label=name[:48], subtitle=primary, source=source, role="context",
                        xrefs=[Xref(i.split(":")[0], i, url if i == primary else None) for i in norm[:6]],
                        attributes={**(attrs or {}), "harmonized_sources": [source], "full_name": name}))
        for i in norm:
            index.setdefault(i, nid)
        return nid

    def _drug_node(self, ctx: Dict[str, Any], name: str, source: str, ident: Optional[str] = None, attrs: Optional[Dict[str, Any]] = None,
                   url: Optional[str] = None) -> str:
        g: Graph = ctx["graph"]
        index: Dict[str, str] = ctx["drug_index"]
        key = drug_key(name)
        if key in index:
            node = g.nodes[index[key]]
            hs = node.attributes.setdefault("harmonized_sources", [])
            if source not in hs:
                hs.append(source)
            names = node.attributes.setdefault("source_names", [])
            if name not in names:
                names.append(name)
            if ident and not any(x.id == ident for x in node.xrefs):
                node.xrefs.append(Xref(source, ident, url))
            for k, v in (attrs or {}).items():
                node.attributes.setdefault(k, v)
            return node.id
        nid = f"drug:{key.lower().replace(' ', '-')}"
        g.add_node(Node(id=nid, type="drug", label=key.title(), source=source, role="context",
                        xrefs=[Xref(source, ident or name, url)], subtitle=None,
                        attributes={**(attrs or {}), "harmonized_sources": [source], "source_names": [name],
                                    "harmonization_rule": "names compared case-insensitively after removing salt/hydrate words"}))
        index[key] = nid
        return nid

    def _add_clinvar_conditions(self, ctx: Dict[str, Any]) -> None:
        res: Resolution = ctx["res"]
        g: Graph = ctx["graph"]
        cv = res.clinvar
        if not cv:
            return
        root = self.root_id(res)
        subs_payload, err = ctx["data"].get("submissions") or (None, None)
        subs = (subs_payload or {}).get("submissions", [])
        ctx["data"]["clinvar_submissions"] = subs
        if err:
            ctx["gaps"].append({"kind": "clinvar_submissions_missing", "message": f"ClinVar submission details could not be retrieved ({err}); only aggregate classifications are shown."})
        for block, label in (("germline", "Germline classification"), ("somatic_clinical_impact", "Somatic clinical impact"), ("oncogenicity", "Oncogenicity")):
            cls = cv.get(block)
            if not cls:
                continue
            for trait in cls.get("traits", []):
                name = trait.get("name") or ""
                if not name or name.lower() in SKIP_TRAITS:
                    continue
                ids = [f"{x['db']}:{x['id']}" if not str(x["id"]).startswith(("MONDO:", "HP:")) else x["id"] for x in trait.get("xrefs", [])]
                ids = [i.replace("MedGen:", "MEDGEN:").replace("Human Phenotype Ontology:", "") for i in ids]
                did = self._disease_node(ctx, name, ids, "clinvar")
                matching = [s for s in subs if s.get("classification_type") == block and any(c.lower() == name.lower() for c in s.get("conditions", []))]
                ev = [Evidence("clinvar", f"{cv['accession']}:{block}", cv["url"], f"ClinVar aggregate {label.lower()}", "curated",
                               f"ClinVar aggregate {label.lower()} for {name}: {cls['description']} ({cls.get('review_status')}).",
                               classification=cls["description"], review_status=cls.get("review_status"),
                               retrieved_at=cv.get("retrieved_at"), context={"stars": cls.get("stars"), "last_evaluated": cls.get("last_evaluated")},
                               limitations=["Aggregate classification computed by ClinVar from submissions; see individual submissions for disagreements."]
                               if "conflicting" in (cls["description"] or "").lower() else [])]
                for s in matching[:12]:
                    ev.append(self._submission_evidence(cv, s, name))
                g.add_edge(root, did, "VARIANT_ASSOCIATED_WITH_CONDITION", "classified for", ev,
                           attributes={"classification_type": block})

    @staticmethod
    def _submission_evidence(cv: Dict[str, Any], s: Dict[str, Any], condition: str) -> Evidence:
        tc = s.get("therapeutic_context") or {}
        statement = f"{s.get('submitter')}: {s.get('classification')} for {condition}"
        if tc.get("DrugForTherapeuticAssertion"):
            statement += f" ({tc.get('ClinicalImpactAssertionType')}, {tc.get('ClinicalImpactClinicalSignificance')}, {tc.get('DrugForTherapeuticAssertion')})"
        return Evidence("clinvar", s["scv"], s.get("url"), "ClinVar submission (SCV)", "curated", statement + ".",
                        publications=s.get("pmids", [])[:12], classification=s.get("classification"), review_status=s.get("review_status"),
                        origin=_origin_label(s.get("origin")), method=s.get("method"), retrieved_at=cv.get("retrieved_at"),
                        context={"date_last_evaluated": s.get("date_last_evaluated"), "submitter": s.get("submitter"),
                                 "comment": s.get("comment"), "classification_type": s.get("classification_type")})

    def _add_clinvar_therapies(self, ctx: Dict[str, Any]) -> None:
        res: Resolution = ctx["res"]
        g: Graph = ctx["graph"]
        cv = res.clinvar
        if not cv:
            return
        root = self.root_id(res)
        for s in ctx["data"].get("clinvar_submissions", []):
            tc = s.get("therapeutic_context") or {}
            drug = tc.get("DrugForTherapeuticAssertion")
            if not drug:
                continue
            did = self._drug_node(ctx, drug, "clinvar")
            cond = ", ".join(s.get("conditions") or []) or "unspecified condition"
            g.add_edge(root, did, "VARIANT_PREDICTIVE_FOR_THERAPY", "therapeutic evidence", [
                Evidence("clinvar", s["scv"], s.get("url"), "ClinVar somatic clinical-impact submission (therapeutic)", "curated",
                         f"{s.get('submitter')}: {s.get('classification')} — {tc.get('ClinicalImpactClinicalSignificance')} to {drug} in {cond}.",
                         publications=s.get("pmids", [])[:12], classification=s.get("classification"), review_status=s.get("review_status"),
                         origin=_origin_label(s.get("origin")), retrieved_at=cv.get("retrieved_at"),
                         context={"disease": cond, "significance": tc.get("ClinicalImpactClinicalSignificance")},
                         limitations=["Disease-specific clinical evidence; not a treatment recommendation for any individual."])])

    def _add_civic(self, ctx: Dict[str, Any]) -> None:
        res: Resolution = ctx["res"]
        g: Graph = ctx["graph"]
        if "civic" not in ctx["data"]:
            return
        payload, err = ctx["data"]["civic"]
        if err or not payload:
            return
        ctx["data"]["civic_payload"] = payload
        if not payload.get("profile"):
            ctx["gaps"].append({"kind": "no_civic_profile", "message": f"CIViC has no molecular profile named exactly '{res.gene['symbol']} {res.protein_change.short}'."
                                + (f" Related composite profiles exist: {', '.join(p['name'] for p in payload.get('related_profiles', [])[:3])}." if payload.get("related_profiles") else "")})
            return
        root = self.root_id(res)
        therapy_best: Dict[str, int] = {}
        level_rank = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
        for item in payload["items"]:
            for t in item.get("therapies") or []:
                therapy_best[t] = min(therapy_best.get(t, 9), level_rank.get(item.get("level") or "", 9))
        allowed_therapies = {t for t, _ in sorted(therapy_best.items(), key=lambda kv: (kv[1], kv[0]))[:MAX_CIVIC_THERAPIES]}
        for item in payload["items"]:
            ev = Evidence("civic", f"EID{item['eid']}", item["url"], f"CIViC {str(item.get('type') or '').lower()} evidence item", "curated",
                          self._civic_statement(item), publications=[item["pmid"]] if item.get("pmid") else [],
                          classification=f"{item.get('significance')} (level {item.get('level')})", direction=item.get("direction"),
                          origin=_origin_label(item.get("origin")), retrieved_at=payload.get("retrieved_at"),
                          score={"name": "CIViC evidence rating", "value": item.get("rating"), "meaning": "curator's 1–5 star rating of the study's quality; not an effect size"} if item.get("rating") else None,
                          context={"level": item.get("level"), "level_label": item.get("level_label"), "disease": item.get("disease"),
                                   "type": item.get("type"), "description": item.get("description"), "citation": item.get("citation")},
                          limitations=(["Evidence direction is DOES_NOT_SUPPORT: the study argues against this association."] if item.get("direction") == "DOES_NOT_SUPPORT" else [])
                          + (["Clinical evidence in a specific disease context; not a treatment recommendation."] if item.get("type") == "PREDICTIVE" else []))
            if item.get("type") == "PREDICTIVE" and item.get("therapies"):
                for t in item["therapies"]:
                    if t not in allowed_therapies:
                        continue
                    did = self._drug_node(ctx, t, "civic", attrs={})
                    g.add_edge(root, did, "VARIANT_PREDICTIVE_FOR_THERAPY", "therapeutic evidence", [ev])
            elif item.get("disease") and item.get("type") in ("DIAGNOSTIC", "PROGNOSTIC", "ONCOGENIC", "PREDISPOSING", "FUNCTIONAL"):
                did = self._disease_node(ctx, item["disease"], [f"DOID:{item['doid']}"] if item.get("doid") else [], "civic")
                g.add_edge(root, did, "VARIANT_ASSOCIATED_WITH_CONDITION", f"{str(item['type']).lower()} evidence", [ev])

    @staticmethod
    def _civic_statement(item: Dict[str, Any]) -> str:
        sig = str(item.get("significance") or "").replace("SENSITIVITYRESPONSE", "sensitivity/response").replace("_", " ").lower()
        therapies = (" + " if item.get("therapy_interaction") == "COMBINATION" else " / ").join(item.get("therapies") or [])
        base = f"CIViC EID{item['eid']} ({item.get('type')}, level {item.get('level')}, {str(item.get('direction') or '').lower().replace('_', ' ')}): {sig}"
        if therapies:
            base += f" to {therapies}"
        if item.get("disease"):
            base += f" in {item['disease']}"
        return base + "."

    def _add_opentargets(self, ctx: Dict[str, Any]) -> None:
        res: Resolution = ctx["res"]
        g: Graph = ctx["graph"]
        if not res.gene:
            return
        gid = f"gene:{res.gene['ensembl_id']}"
        assoc, err = ctx["data"].get("ot_assoc") or (None, None)
        if assoc:
            ctx["data"]["ot_assoc_payload"] = assoc
            for row in assoc["rows"][:MAX_OT_DISEASES]:
                ids = [row["disease_id"]] + [x for x in row.get("xrefs", []) if x.split(":")[0] in ("DOID", "MEDGEN", "MESH", "Orphanet", "OMIMPS", "NCIT")]
                ids = [i.replace("MEDGEN:", "MEDGEN:") for i in ids]
                did = self._disease_node(ctx, row["name"], ids, "opentargets", url=row["url"],
                                         attrs={"therapeutic_areas": row.get("therapeutic_areas")})
                top = sorted(row["datatype_scores"].items(), key=lambda kv: -kv[1])[:4]
                g.add_edge(gid, did, "TARGET_ASSOCIATED_WITH_DISEASE", "associated with (gene-level)", [
                    Evidence("opentargets", f"{res.gene['ensembl_id']}-{row['disease_id']}", row["url"], "Open Targets target–disease association", "association",
                             f"Open Targets associates {res.gene['symbol']} with {row['name']} (overall score {row['score']:.2f}; strongest data types: "
                             + ", ".join(f"{k} {v:.2f}" for k, v in top) + ").",
                             retrieved_at=assoc.get("retrieved_at"), release=ctx["tracker"].releases.get("opentargets"),
                             score={"name": "Open Targets association score", "value": round(row["score"], 3),
                                    "meaning": "0–1 harmonic-sum aggregate of evidence across data types; relative ranking, not a probability"},
                             context={"datatype_scores": row["datatype_scores"]},
                             limitations=["Gene-level association aggregated over all variants and evidence types; it is not specific to the queried variant."])])
        drugs, derr = ctx["data"].get("ot_drugs") or (None, None)
        if drugs and res.protein:
            ctx["data"]["ot_drugs_payload"] = drugs
            pid = f"protein:{res.protein['accession']}"
            for d in drugs["drugs"][:MAX_OT_DRUGS]:
                did = self._drug_node(ctx, d["name"] or d["chembl_id"], "opentargets", ident=d["chembl_id"], url=d["url"],
                                      attrs={"max_stage": d.get("max_stage"), "drug_type": d.get("drug_type"), "indications": d.get("indications")})
                mech = d["mechanisms"][0] if d["mechanisms"] else {}
                g.add_edge(did, pid, "DRUG_TARGETS_PROTEIN", (mech.get("action_type") or "targets").lower(), [
                    Evidence("opentargets", d["chembl_id"], d["url"], "ChEMBL drug mechanism of action (via Open Targets)", "curated",
                             f"{d['name']}: {mech.get('mechanism') or 'mechanism of action'} (targets: {', '.join(mech.get('targets') or [])}); max clinical stage {d.get('max_stage')}.",
                             publications=mech.get("pmids", [])[:8], retrieved_at=drugs.get("retrieved_at"),
                             context={"max_stage": d.get("max_stage"), "indications": d.get("indications"), "reference_sources": mech.get("reference_sources")},
                             limitations=["Drug–target mechanism at the gene/protein level; it does not imply activity against, or benefit for, this variant."])])
            if drugs.get("excluded_other_target"):
                ctx["gaps"].append({"kind": "ot_drugs_other_targets",
                                    "message": f"{len(drugs['excluded_other_target'])} drug(s) listed by Open Targets for {res.gene['symbol']} have mechanisms naming other targets "
                                               f"({', '.join(x['name'] for x in drugs['excluded_other_target'][:4])}); they were not drawn as targeting {res.gene['symbol']}."})

    # ================================================================== roles
    def _assign_roles(self, ctx: Dict[str, Any]) -> None:
        g: Graph = ctx["graph"]
        for n in g.nodes.values():
            if n.role == "query":
                continue
            if n.type in ("gene", "protein", "protein_region", "reactome_entity"):
                n.role = "core"
            elif n.type in ("reaction", "pathway", "physical_entity"):
                n.role = "downstream"
            elif n.type in ("disease", "drug"):
                n.role = "context"
        # Keep the initial view legible: diseases beyond the 12 with the most supporting records
        # are hidden by default ("secondary"), never removed.
        support: Dict[str, int] = {}
        for e in g.edges.values():
            for end in (e.source, e.target):
                if end in g.nodes and g.nodes[end].type == "disease":
                    support[end] = support.get(end, 0) + len(e.evidence)
        ranked = sorted(support, key=lambda nid: (-support[nid], g.nodes[nid].label))
        for nid in ranked[12:]:
            g.nodes[nid].secondary = True
            g.nodes[nid].role = "secondary"
            for e in g.edges.values():
                if nid in (e.source, e.target):
                    e.secondary = True
