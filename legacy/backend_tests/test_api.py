from __future__ import annotations

from fastapi.testclient import TestClient

from app.graph import GraphService
from app.main import app

client = TestClient(app)


def _mock_live_graph(monkeypatch, *, gene_symbol: str = "EGFR", accession: str = "P00533") -> None:
    mock_variant = {
        "gene_symbol": gene_symbol,
        "variant_id": "VCV12345",
        "source_database": "ClinVar",
        "source_id": "12345",
        "clinical_significance": "drug response",
        "downloaded_at": "2026-01-01T00:00:00Z",
        "title": f"NM_0000.1({gene_symbol}):c.1A>G (p.{gene_symbol}X)",
    }
    mock_gene = {"source_id": "ENSG00000146648", "gene_symbol": gene_symbol, "downloaded_at": "2026-01-01T00:00:00Z"}
    mock_protein = {"source_id": accession, "gene_symbol": gene_symbol, "protein_name": "Test protein", "downloaded_at": "2026-01-01T00:00:00Z"}
    mock_pathways = [{"stId": "R-HSA-1", "displayName": "Test pathway", "name": ["Test pathway"]}]
    mock_reactions = [{"stId": "R-HSA-10", "displayName": "Test reaction", "type": "Reaction"}]

    monkeypatch.setattr(GraphService, "_pick_record", staticmethod(lambda records, query, gene_symbol, target_change: records[0]))
    monkeypatch.setattr(GraphService, "_source_metadata", lambda self: {
        "clinvar": {"source_url": "https://www.ncbi.nlm.nih.gov/clinvar/", "version": "live", "retrieved_at": "2026-01-01T00:00:00Z"},
        "ensembl": {"source_url": "https://rest.ensembl.org/", "version": "live", "retrieved_at": "2026-01-01T00:00:00Z"},
        "uniprot": {"source_url": "https://rest.uniprot.org/", "version": "live", "retrieved_at": "2026-01-01T00:00:00Z"},
        "reactome": {"source_url": "https://reactome.org/ContentService/data", "version": "live", "retrieved_at": "2026-01-01T00:00:00Z"},
    })
    monkeypatch.setattr(GraphService, "analyze", lambda self, variant_name: {
        "query": variant_name,
        "status": "resolved",
        "message": "resolved from live source data",
        "variant": mock_variant,
        "graph": {"nodes": [{"id": "variant:VCV12345", "name": variant_name, "type": "variant"}, {"id": "gene:EGFR", "name": "EGFR", "type": "gene"}, {"id": "protein:P00533", "name": "Test protein", "type": "protein"}, {"id": "pathway:R-HSA-1", "name": "Test pathway", "type": "pathway"}, {"id": "reaction:R-HSA-10", "name": "Test reaction", "type": "reaction"}], "edges": [{"source": "variant:VCV12345", "target": "gene:EGFR", "relationship": "VARIANT_OF", "source_database": "ClinVar", "source_id": "12345"}, {"source": "gene:EGFR", "target": "protein:P00533", "relationship": "ENCODES", "source_database": "UniProt", "source_id": "P00533"}, {"source": "protein:P00533", "target": "pathway:R-HSA-1", "relationship": "PARTICIPATES_IN", "source_database": "Reactome", "source_id": "R-HSA-1"}, {"source": "pathway:R-HSA-1", "target": "reaction:R-HSA-10", "relationship": "CONTAINS", "source_database": "Reactome", "source_id": "R-HSA-10"}]},
        "paths": [{"nodes": ["variant:VCV12345", "gene:EGFR", "protein:P00533", "pathway:R-HSA-1", "reaction:R-HSA-10"], "edges": [{"source": "variant:VCV12345", "target": "gene:EGFR", "relationship": "VARIANT_OF"}, {"source": "gene:EGFR", "target": "protein:P00533", "relationship": "ENCODES"}, {"source": "protein:P00533", "target": "pathway:R-HSA-1", "relationship": "PARTICIPATES_IN"}, {"source": "pathway:R-HSA-1", "target": "reaction:R-HSA-10", "relationship": "CONTAINS"}], "evidence": [{"source_database": "ClinVar", "source_id": "12345", "relationship": "VARIANT_OF"}, {"source_database": "UniProt", "source_id": accession, "relationship": "ENCODES"}, {"source_database": "Reactome", "source_id": "R-HSA-1", "relationship": "PARTICIPATES_IN"}, {"source_database": "Reactome", "source_id": "R-HSA-10", "relationship": "CONTAINS"}] }],
        "sources": {"clinvar": {"source_url": "https://www.ncbi.nlm.nih.gov/clinvar/"}, "uniprot": {"source_url": "https://rest.uniprot.org/"}, "ensembl": {"source_url": "https://rest.ensembl.org/"}, "reactome": {"source_url": "https://reactome.org/ContentService/data"}},
        "candidate_drugs": [],
    })
    monkeypatch.setattr(GraphService, "list_variants", lambda self: ["EGFR L858R", "BRAF V600E"])
    monkeypatch.setattr(GraphService, "get_variant", lambda self, _name: {"gene_symbol": gene_symbol, "source_database": "ClinVar"})
    monkeypatch.setattr(GraphService, "get_node_detail", lambda self, node_id: {"id": node_id, "type": "variant"})


def test_health_endpoint() -> None:
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'


def test_analyze_endpoint_uses_live_sources(monkeypatch) -> None:
    _mock_live_graph(monkeypatch)
    response = client.post('/api/analyze', json={'variant': 'EGFR L858R'})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['query'] == 'EGFR L858R'
    assert payload['status'] == 'resolved'
    assert payload['graph']['nodes'][0]['id'].startswith('variant:')
    assert payload['graph']['edges'][0]['source'].startswith('variant:')
    assert payload['paths'][0]['nodes'][0].startswith('variant:')
    assert payload['sources']['reactome']['source_url'].startswith('https://reactome.org')


def test_negative_inputs_remain_not_resolved(monkeypatch) -> None:
    monkeypatch.setattr(GraphService, 'analyze', lambda self, variant_name: {
        'query': variant_name,
        'status': 'not_resolved',
        'message': 'not resolved / insufficient source data',
        'variant': None,
        'graph': {'nodes': [], 'edges': []},
        'paths': [],
        'sources': {},
        'candidate_drugs': [],
    })
    for variant_name in ['ZZZFAKEGENE X999Y', 'EGFR L999R', '!!!!', '']:
        response = client.post('/api/analyze', json={'variant': variant_name})
        assert response.status_code == 200
        payload = response.json()
        assert payload['status'] == 'not_resolved'
        assert payload['variant'] is None
        assert payload['graph']['nodes'] == []


def test_traversal_endpoint_removed() -> None:
    assert not any(route.path == '/api/analyze/traversal' for route in app.routes)


def test_graph_api_aliases_and_traverse() -> None:
    response = client.get("/api/health")
    assert response.json()["backend"] == "memory-json"
    response = client.post("/api/traverse", json={"node_id": "gene-egfr", "algorithm": "dfs", "max_depth": 1})
    assert response.status_code == 200
    assert response.json()["algorithm"] == "dfs"
    assert client.get("/api/graph/stats").status_code == 200
    assert client.get("/api/graph/neighbors/gene-egfr").status_code == 200


def test_search_type_filter_and_path_query() -> None:
    assert client.get("/api/search", params={"q": "EGFR", "type": "gene"}).status_code == 200
    response = client.get("/api/path", params={"source": "gene-egfr", "target": "protein-egfr", "weighted": "true", "k": 1})
    assert response.status_code == 200
    assert "paths" in response.json()
