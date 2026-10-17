"""HTTP API contract tests (offline replay)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_mode_and_ai_status():
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["mode"] == "offline_replay"
    assert body["ai"]["enabled"] is False


def test_analyze_then_path_report_and_exports():
    p = client.post("/api/analyze", json={"query": "EGFR L858R"}).json()
    aid = p["analysis_id"]
    assert p["resolution"]["status"] == "resolved"
    assert client.get(f"/api/analysis/{aid}").status_code == 200

    drug = next(n for n in p["graph"]["nodes"] if n["type"] == "drug")
    path = client.get(f"/api/analysis/{aid}/path", params={"target": drug["id"]}).json()
    assert path["found"]

    md = client.post(f"/api/analysis/{aid}/report", json={"format": "md"})
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown") and "Data sources" in md.text
    html = client.post(f"/api/analysis/{aid}/report", json={"format": "html"})
    assert html.status_code == 200 and "<table>" in html.text
    graph = client.get(f"/api/analysis/{aid}/export/graph", params={"format": "cytoscape"}).json()
    assert graph["elements"]["nodes"] and graph["evidence"]


def test_legacy_variant_field_is_still_accepted():
    p = client.post("/api/analyze", json={"variant": "BRAF V600E"}).json()
    assert p["resolution"]["gene"]["symbol"] == "BRAF"


def test_invalid_input_is_200_with_explanation():
    p = client.post("/api/analyze", json={"query": "L858R"}).json()
    assert p["resolution"]["status"] == "invalid" and "gene" in p["resolution"]["message"]


def test_expand_rejects_unsupported_action_and_unknown_ids():
    p = client.post("/api/analyze", json={"query": "EGFR L858R"}).json()
    aid = p["analysis_id"]
    r = client.post(f"/api/analysis/{aid}/expand", json={"node_id": p["root_id"], "action": "all_pathways"})
    assert r.status_code == 400
    assert client.post("/api/analysis/nope/expand", json={"node_id": "x", "action": "y"}).status_code == 404


def test_synthesis_without_credentials_is_explicitly_unavailable():
    p = client.post("/api/analyze", json={"query": "EGFR L858R"}).json()
    r = client.post(f"/api/analysis/{p['analysis_id']}/synthesis").json()
    assert r["mode"] == "unavailable" and "ANTHROPIC_API_KEY" in r["message"]


def test_bad_pmid_is_rejected():
    assert client.get("/api/publications/abc/abstract").status_code == 400


def test_routes_and_retrieval_assistant_are_grounded():
    p = client.post("/api/analyze", json={"query": "BRAF V600E"}).json()
    aid = p["analysis_id"]
    target = next(n for n in p["graph"]["nodes"] if n["type"] == "physical_entity")
    r = client.get(f"/api/analysis/{aid}/routes", params={"target": target["id"], "k": 3}).json()
    assert r["routes"] and r["routes"][0]["rank"] == 1
    keys = [tuple(h["edge_id"] for h in x["hops"]) for x in r["routes"]]
    assert len(keys) == len(set(keys))
    assert p["assistant_suggestions"]
    for q in ["Which drugs have evidence?", "Where do sources disagree?", "Explain the downstream mechanism", "kinase domain"]:
        a = client.post(f"/api/analysis/{aid}/chat", json={"messages": [{"role": "user", "content": q}]}).json()
        assert a["mode"] == "retrieval" and a["answer"]
        assert all(c in p["graph"]["evidence"] for c in a["citations"])
