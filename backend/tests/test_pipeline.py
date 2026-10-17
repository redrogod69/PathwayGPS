"""End-to-end pipeline tests over recorded (replayed) source responses.

Assertions target identifiers and structural/scientific invariants, not record counts,
so they remain valid when the fixtures are re-recorded against newer database releases.
"""

import asyncio
import re

import pytest

from app.core.http import HttpClient, SourceError, Tracker
from app.pipeline.report import build_blocks, to_markdown
from app.pipeline.service import AnalysisService

CATEGORIES = {"curated", "experimental", "association", "computational", "inferred", "hypothesis"}


@pytest.fixture(scope="module")
def service():
    return AnalysisService(HttpClient())


@pytest.fixture(scope="module")
def egfr(service):
    return asyncio.run(service.analyze("EGFR L858R"))


@pytest.fixture(scope="module")
def braf(service):
    return asyncio.run(service.analyze("BRAF V600E"))


def _types(p, t):
    return [n for n in p["graph"]["nodes"] if n["type"] == t]


def _edges(p, t):
    return [e for e in p["graph"]["edges"] if e["type"] == t]


def test_egfr_l858r_resolves_to_expected_records(egfr):
    r = egfr["resolution"]
    assert r["status"] == "resolved"
    assert r["gene"]["symbol"] == "EGFR" and r["gene"]["ensembl_id"] == "ENSG00000146648"
    assert r["protein"]["accession"] == "P00533"
    assert r["protein_change"]["short"] == "L858R"
    assert r["clinvar_variation_id"] == "16609"
    assert r["residue_check"]["ok"] is True
    assert egfr["root_id"] == "variant:clinvar:16609"


def test_braf_v600e_is_distinct_and_uses_its_own_curated_mutant_entity(egfr, braf):
    assert braf["resolution"]["gene"]["symbol"] == "BRAF" and braf["resolution"]["protein"]["accession"] == "P15056"
    assert braf["root_id"] != egfr["root_id"]
    entities = _types(braf, "reactome_entity")
    assert any(n["label"] == "BRAF V600E" for n in entities)
    # the focus pathway must be the one containing the exact variant (high-kinase activity class), not list order
    assert "high-kinase" in braf["impact"]["focus_pathway"]["name"]
    assert braf["impact"]["focus_pathway"]["reason"].startswith("contains the curated entity")


@pytest.mark.parametrize("name", ["egfr", "braf"])
def test_graph_invariants_every_edge_has_provenance(name, request):
    p = request.getfixturevalue(name)
    nodes = {n["id"] for n in p["graph"]["nodes"]}
    assert len(nodes) == len(p["graph"]["nodes"]), "node ids must be unique"
    assert p["root_id"] in nodes
    ev = p["graph"]["evidence"]
    for e in p["graph"]["edges"]:
        assert e["source"] in nodes and e["target"] in nodes
        assert e["evidence"], f"edge {e['type']} has no evidence"
        assert e["category"] in CATEGORIES
        for eid in e["evidence"]:
            rec = ev[eid]
            assert rec["source"] and rec["record_id"] and rec["statement"]
            assert rec["category"] in CATEGORIES
            assert all(re.fullmatch(r"\d{1,9}", pm) for pm in rec["publications"]), "PMIDs must be real identifiers"


def test_core_route_variant_gene_protein_pathway_downstream(egfr):
    assert _edges(egfr, "VARIANT_IN_GENE") and _edges(egfr, "GENE_ENCODES_PROTEIN") and _edges(egfr, "VARIANT_ALTERS_PROTEIN")
    assert _edges(egfr, "PROTEIN_PARTICIPATES_IN_PATHWAY")
    assert _edges(egfr, "PROTEIN_PARTICIPATES_IN_REACTION")
    downstream = egfr["impact"]["downstream"]
    assert downstream and all(d["verdict"] for d in downstream)


def test_variant_protein_edge_separates_prediction_from_curation(egfr):
    edge = _edges(egfr, "VARIANT_ALTERS_PROTEIN")[0]
    cats = {egfr["graph"]["evidence"][e]["category"] for e in edge["evidence"]}
    assert "computational" in cats  # VEP / SIFT / PolyPhen
    assert "curated" in cats        # ClinVar HGVS / UniProt natural variant


def test_region_overlap_is_marked_as_inferred(egfr):
    for e in _edges(egfr, "VARIANT_IN_PROTEIN_REGION"):
        assert e["category"] == "inferred"
        assert all(egfr["graph"]["evidence"][x]["inference"] for x in e["evidence"])


def test_gene_level_associations_are_never_curated_variant_facts(egfr):
    for e in _edges(egfr, "TARGET_ASSOCIATED_WITH_DISEASE"):
        assert e["category"] == "association"
        assert e["source"].startswith("gene:"), "Open Targets associations attach to the gene, not the variant"
        rec = egfr["graph"]["evidence"][e["evidence"][0]]
        assert "not a probability" in rec["score"]["meaning"]


def test_conflicting_submissions_are_preserved_not_collapsed(braf):
    kinds = {c["kind"] for c in braf["conflicts"]}
    assert "clinvar_germline_classification" in kinds
    conflict = next(c for c in braf["conflicts"] if c["kind"] == "clinvar_germline_classification")
    assert len(conflict["positions"]) >= 2
    assert "does not adjudicate" in conflict["explanation"]


def test_missing_literature_is_reported_as_missing(egfr):
    no_pub = [e for e in egfr["graph"]["evidence"].values() if not e["publications"]]
    assert no_pub, "fixture should contain evidence without publications"
    assert any(g["kind"] == "edges_without_literature" for g in egfr["gaps"])


def test_gene_only_query_never_invents_a_variant(service):
    p = asyncio.run(service.analyze("TP53"))
    assert p["resolution"]["status"] == "gene_level"
    assert not _types(p, "variant")
    assert p["root_id"].startswith("gene:")
    assert "never picks a variant" in p["resolution"]["message"]


def test_alias_symbol_is_resolved_with_a_warning(service):
    p = asyncio.run(service.analyze("HER2"))
    assert p["resolution"]["gene"]["symbol"] == "ERBB2"
    assert any("not an approved HGNC symbol" in w for w in p["resolution"]["warnings"])


@pytest.mark.parametrize("query,status", [
    ("L858R", "invalid"),
    ("ZZZFAKEGENE L858R", "not_found"),
    ("EGFR L859R", "invalid"),
])
def test_bad_input_gets_an_explanation_and_no_graph(service, query, status):
    p = asyncio.run(service.analyze(query))
    assert p["resolution"]["status"] == status
    assert p["resolution"]["message"]
    assert p["graph"]["nodes"] == []


def test_residue_mismatch_explains_the_reference_residue(service):
    p = asyncio.run(service.analyze("EGFR L859R"))
    rc = p["resolution"]["residue_check"]
    assert rc["ok"] is False and rc["observed"] != "L"


def test_multiple_nucleotide_records_are_listed_not_substituted(service):
    p = asyncio.run(service.analyze("KRAS G12C"))
    r = p["resolution"]
    assert r["status"] == "resolved" and r["clinvar_alternatives"]
    assert any("distinct ClinVar records" in w for w in r["warnings"])


def test_rsid_and_transcript_hgvs_inputs(service):
    rs = asyncio.run(service.analyze("rs121434568"))
    assert rs["resolution"]["status"] == "resolved" and rs["resolution"]["clinvar_variation_id"] == "16609"
    assert rs["resolution"]["protein_change"]["short"] == "L858R"  # the ClinVar allele, not the other rs allele
    tx = asyncio.run(service.analyze("NM_000546.6:c.524G>A"))
    assert tx["resolution"]["gene"]["symbol"] == "TP53" and tx["resolution"]["protein_change"]["short"] == "R175H"


class FailingOpenTargets(HttpClient):
    async def request(self, source, method, url, **kwargs):
        if source == "opentargets":
            tracker = kwargs.get("tracker")
            err = SourceError("opentargets", "http", "HTTP 503", 503)
            if tracker is not None:
                from app.core.http import CallRecord
                tracker.add(CallRecord(source, url, False, 503, False, False, 0, "2026-10-17T00:00:00+00:00", "HTTP 503"))
            raise err
        return await super().request(source, method, url, **kwargs)


def test_unavailable_source_yields_partial_result_not_fabrication():
    svc = AnalysisService(FailingOpenTargets())
    p = asyncio.run(svc.analyze("EGFR L858R"))
    assert p["resolution"]["status"] == "resolved"
    status = {s["source"]: s["status"] for s in p["sources"]}
    assert status["opentargets"] == "failed" and status["clinvar"] == "ok"
    assert not _edges(p, "TARGET_ASSOCIATED_WITH_DISEASE")
    assert any(g["kind"] == "source_failures" for g in p["gaps"])
    assert _edges(p, "PROTEIN_PARTICIPATES_IN_PATHWAY"), "other sources still contribute"


def test_expansion_adds_source_backed_nodes(service, egfr):
    pw = next(n for n in _types(egfr, "pathway") if "Overexpressed" in n["label"])
    res = asyncio.run(service.expand(egfr["analysis_id"], pw["id"], "reactions"))
    assert res["added_nodes"]
    added = set(res["added_nodes"])
    for e in res["analysis"]["graph"]["edges"]:
        if e["target"] in added or e["source"] in added:
            assert e["evidence"]


def test_explain_path_endpoint_logic(service, egfr):
    drug = _types(egfr, "drug")[0]
    p = service.path(egfr["analysis_id"], drug["id"])
    assert p["found"] and p["hops"] and p["verdict_text"]


def test_report_contains_sources_limitations_and_no_abstracts(egfr):
    md = to_markdown(build_blocks(egfr, {"notes": [{"kind": "hypothesis", "target_label": "EGFR", "text": "test note"}], "marked": []}))
    for heading in ("Input and resolution", "Key relationships", "Conflicting evidence", "Evidence gaps", "References", "Data sources", "Limitations"):
        assert heading in md
    assert "ClinVar" in md and "Reactome" in md and "test note" in md
    assert "Research use only" in md


def test_snapshot_roundtrip_is_frozen_and_read_only(service, egfr):
    snap = service.save_snapshot(egfr["analysis_id"], {"notes": [], "marked": []})
    loaded = service.load_snapshot(snap["id"])
    assert loaded["snapshot"]["id"] == snap["id"]
    assert loaded["created_at"] == egfr["created_at"], "retrieval timestamp is preserved"
    with pytest.raises(ValueError):
        asyncio.run(service.expand(loaded["analysis_id"], loaded["root_id"], "downstream"))
    assert service.path(loaded["analysis_id"], _types(egfr, "drug")[0]["id"])["found"]


def test_enrichment_refuses_single_gene(service):
    with pytest.raises(ValueError):
        asyncio.run(service.enrichment(["EGFR"]))
