"""Unit tests: notation parsing, graph model invariants, path ranking, parsers."""

import pytest

from app.adapters.clinvar import ClinVarAdapter, germline_group
from app.adapters.pubmed import PubMedAdapter
from app.adapters.reactome import normalize_event
from app.adapters.uniprot import features_at, reference_residue
from app.domain.model import Evidence, Graph, Node
from app.domain.notation import parse_protein_change, parse_query, protein_change_from_title
from app.pipeline.builder import drug_key
from app.pipeline.insights import explain_path


@pytest.mark.parametrize("text,kind,gene,change", [
    ("EGFR L858R", "protein_change", "EGFR", "L858R"),
    ("braf p.Val600Glu", "protein_change", "BRAF", "V600E"),
    ("EGFR:p.L858R", "protein_change", "EGFR", "L858R"),
    ("TP53 R213*", "protein_change", "TP53", "R213*"),
    ("rs121434568", "rsid", None, None),
    ("NM_005228.5:c.2573T>G", "transcript_hgvs", None, None),
    ("NM_004333.6(BRAF):c.1799T>A", "transcript_hgvs", "BRAF", None),
    ("NC_000007.14:g.55191822T>G", "genomic_hgvs", None, None),
    ("VCV000016609", "clinvar_id", None, None),
    ("TP53", "gene", "TP53", None),
    ("P00533", "uniprot", None, None),
])
def test_parse_query_detects_input_type(text, kind, gene, change):
    q = parse_query(text)
    assert q.input_type == kind
    assert q.gene == gene
    assert (q.protein_change.short if q.protein_change else None) == change


@pytest.mark.parametrize("text,needle", [
    ("L858R", "without a gene"),
    ("EGFR L858", "not a supported protein change"),
    ("NC_000007.13:g.55259515T>G", "GRCh38"),
    ("", "Enter a variant"),
    ("!!!!", "Could not recognise"),
])
def test_invalid_inputs_explain_why(text, needle):
    q = parse_query(text)
    assert q.input_type == "invalid"
    assert needle in " ".join(q.problems)


def test_bare_chromosome_genomic_hgvs_warns_about_assembly():
    q = parse_query("7:g.55191822T>G")
    assert q.input_type == "genomic_hgvs"
    assert "GRCh38" in (q.assembly_note or "")


def test_protein_change_forms_are_equivalent():
    a, b = parse_protein_change("p.Leu858Arg"), parse_protein_change("L858R")
    assert (a.short, a.long, a.kind) == (b.short, b.long, b.kind) == ("L858R", "Leu858Arg", "missense")
    assert parse_protein_change("R213Ter").kind == "nonsense"
    assert protein_change_from_title("NM_005228.5(EGFR):c.2573T>G (p.Leu858Arg)").short == "L858R"


def test_graph_never_creates_edges_without_evidence_or_endpoints():
    g = Graph()
    g.add_node(Node("a", "gene", "A", "ensembl"))
    g.add_node(Node("b", "protein", "B", "uniprot"))
    assert g.add_edge("a", "b", "GENE_ENCODES_PROTEIN", "encodes", []) is None
    assert g.add_edge("a", "missing", "X", "x", [Evidence("uniprot", "1", None, "t", "curated", "s")]) is None
    e = g.add_edge("a", "b", "GENE_ENCODES_PROTEIN", "encodes", [Evidence("uniprot", "1", None, "t", "inferred", "s")])
    g.add_edge("a", "b", "GENE_ENCODES_PROTEIN", "encodes", [Evidence("uniprot", "2", None, "t", "curated", "s2")])
    assert e.category == "curated" and e.categories == ["curated", "inferred"] and len(e.evidence) == 2


def test_unknown_evidence_category_is_rejected():
    with pytest.raises(ValueError):
        Evidence("x", "1", None, "t", "probably-true", "s")


def _chain_graph():
    g = Graph()
    for nid in "vabct":
        g.add_node(Node(nid, "reaction", nid, "reactome"))
    cur = lambda rid: [Evidence("reactome", rid, None, "t", "curated", rid)]
    inf = lambda rid: [Evidence("user", rid, None, "t", "inferred", rid)]
    g.add_edge("v", "a", "R", "r", cur("1")); g.add_edge("a", "t", "R", "r", cur("2"))   # curated, 2 hops
    g.add_edge("v", "b", "R", "r", inf("3")); g.add_edge("b", "t", "R", "r", inf("4"))   # inferred, 2 hops
    return g


def test_path_prefers_stronger_evidence_at_equal_length_and_reports_verdict():
    p = explain_path(_chain_graph(), "v", "t")
    assert p["nodes"] == ["v", "a", "t"]
    assert p["verdict"] == "supported_by_curated_or_experimental_evidence"


def test_path_flags_inferred_steps_and_returns_none_when_disconnected():
    g = _chain_graph()
    g.edges = {k: e for k, e in g.edges.items() if e.source != "a" and e.target != "a"}
    assert explain_path(g, "v", "t")["verdict"] == "contains_inferred_steps"
    g.add_node(Node("island", "drug", "island", "civic"))
    assert explain_path(g, "v", "island") is None


def test_clinvar_vcv_xml_parsing_preserves_each_submission():
    xml = """<root><VariationArchive><ClassifiedRecord><ClinicalAssertionList>
      <ClinicalAssertion ContributesToAggregateClassification="true"><ClinVarAccession Accession="SCV1" SubmitterName="Lab A" OrgID="1"/>
        <Classification DateLastEvaluated="2020-01-01"><ReviewStatus>criteria provided, single submitter</ReviewStatus><GermlineClassification>Pathogenic</GermlineClassification></Classification>
        <ObservedInList><ObservedIn><Sample><Origin>germline</Origin></Sample><Method><MethodType>clinical testing</MethodType></Method></ObservedIn></ObservedInList>
        <TraitSet><Trait><Name><ElementValue Type="Preferred">Disease X</ElementValue></Name></Trait></TraitSet>
        <Citation><ID Source="PubMed">123</ID></Citation></ClinicalAssertion>
      <ClinicalAssertion><ClinVarAccession Accession="SCV2" SubmitterName="Lab B" OrgID="2"/>
        <Classification><ReviewStatus>criteria provided, single submitter</ReviewStatus><GermlineClassification>Uncertain significance</GermlineClassification></Classification></ClinicalAssertion>
    </ClinicalAssertionList></ClassifiedRecord></VariationArchive></root>"""
    subs = ClinVarAdapter.parse_vcv_xml(xml)
    assert [s["scv"] for s in subs] == ["SCV1", "SCV2"]
    assert subs[0]["origin"] == "germline" and subs[0]["pmids"] == ["123"] and subs[0]["conditions"] == ["Disease X"]
    assert germline_group(subs[0]["classification"]) == "pathogenic" and germline_group(subs[1]["classification"]) == "uncertain"


def test_pubmed_abstract_parser_handles_structured_abstracts():
    xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation><Article><ArticleTitle>T</ArticleTitle>
      <Abstract><AbstractText Label="BACKGROUND">B.</AbstractText><AbstractText Label="RESULTS">R.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""
    out = PubMedAdapter.parse_abstract_xml(xml)
    assert out["title"] == "T" and [s["label"] for s in out["sections"]] == ["BACKGROUND", "RESULTS"]


def test_uniprot_feature_overlap_and_reference_residue():
    protein = {"sequence": "MAL", "features": [
        {"type": "Domain", "start": 1, "end": 2, "description": "D"},
        {"type": "Active site", "start": 3, "end": 3, "description": ""},
        {"type": "Mutagenesis", "start": 2, "end": 2, "description": "loss"},
    ]}
    at = features_at(protein, 2, window=1)
    assert [f["type"] for f in at["covering"]] == ["Domain"]
    assert [f["type"] for f in at["nearby"]] == ["Active site"]
    assert [f["type"] for f in at["at_residue"]] == ["Mutagenesis"]
    assert reference_residue(protein, 2) == "A" and reference_residue(protein, 9) is None


def test_reactome_event_normalisation_keeps_literature_and_flags():
    ev = normalize_event({"stId": "R-HSA-1", "displayName": "R", "isInDisease": True, "isInferred": False,
                          "literatureReference": [{"pubMedIdentifier": 42, "title": "Paper", "year": 2001}],
                          "input": [{"stId": "R-HSA-2", "displayName": "X [cytosol]", "schemaClass": "Complex"}]})
    assert ev["literature"][0]["pmid"] == "42" and ev["isInDisease"] and ev["inputs"][0]["stId"] == "R-HSA-2"


def test_drug_name_harmonisation_strips_salts_only():
    assert drug_key("DABRAFENIB MESYLATE") == drug_key("Dabrafenib") == "DABRAFENIB"
    assert drug_key("Erlotinib hydrochloride") == "ERLOTINIB"
    assert drug_key("Trametinib") != drug_key("Dabrafenib")
