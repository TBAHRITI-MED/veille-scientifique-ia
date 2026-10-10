"""API FastAPI de bout en bout, avec les 4 sources simulées."""

import pytest

import settings
from api import main
from sources import arxiv_client, http
from tests.conftest import FIXTURES

def _search(client, **overrides):
    body = {"topic": "federated learning", "days": 30, "max_results": 30, **overrides}
    response = client.post("/api/search", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_meta(client):
    data = client.get("/api/meta").json()
    assert [s["name"] for s in data["sources"]] == ["arxiv", "openalex", "semantic_scholar", "pubmed"]
    assert data["sources"][0]["key_env"] is None
    assert "Q1" in data["levels"] and data["level_order"]["Préprint"] == 5


def test_search_merges_and_ranks(client):
    data = _search(client)
    assert data["stats"]["cached"] is False
    assert set(data["by_source"]) == {"arxiv", "openalex", "semantic_scholar", "pubmed"}
    assert data["errors"] == {}

    merged = next(p for p in data["papers"] if p["doi"] == "10.1016/j.media.2026.103456")
    assert merged["sources"] == ["arxiv", "openalex", "semantic_scholar", "pubmed"]
    assert merged["level"] == "Q1"
    assert merged["url"] == "https://doi.org/10.1016/j.media.2026.103456"
    assert data["stats"]["duplicates_merged"] == 3
    assert data["stats"]["overlap"]["4"] == 1
    levels = {p["level"] for p in data["papers"]}
    assert {"Q1", "A*", "A", "Préprint"} <= levels


def test_search_is_cached(client):
    first = _search(client)
    calls_after_first = len(client.calls)
    second = _search(client)
    assert second["stats"]["cached"] is True
    assert second["search_id"] == first["search_id"]
    assert len(client.calls) == calls_after_first          # aucun nouvel appel réseau


def test_search_source_error_is_isolated(client, monkeypatch):
    def broken(params):
        raise http.SourceError("arXiv a répondu 503")
    monkeypatch.setattr(arxiv_client, "_fetch_feed", broken)
    data = _search(client, sources=["arxiv", "openalex"])
    assert data["errors"]["arxiv"]["message"] == "arXiv a répondu 503"
    assert data["papers"]                                  # OpenAlex a quand même répondu


@pytest.mark.parametrize("body,status", [
    ({"topic": " , | "}, 422),
    ({"topic": "x", "sources": ["google_scholar"]}, 422),
    ({"topic": "x", "sources": []}, 422),
    ({"topic": ""}, 422),
])
def test_search_validation(client, body, status):
    assert client.post("/api/search", json=body).status_code == status


def test_export_csv_and_markdown(client):
    data = _search(client)
    keys = [p["key"] for p in data["papers"][:2]]

    csv_resp = client.post("/api/export", json={"search_id": data["search_id"], "keys": keys, "format": "csv"})
    assert csv_resp.status_code == 200
    assert "attachment" in csv_resp.headers["content-disposition"]
    lines = csv_resp.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0].startswith("titre;auteurs;date")
    assert len(lines) == 3

    md = client.post("/api/export", json={"search_id": data["search_id"], "keys": keys, "format": "markdown"})
    assert md.text.startswith("# Veille : federated learning")


def test_export_expired_search(client):
    r = client.post("/api/export", json={"search_id": "nope", "keys": [], "format": "csv"})
    assert r.status_code == 404


def test_rankings_status_and_upload(client):
    assert client.get("/api/rankings").json()["journals"] == 3

    bad = client.post("/api/rankings/upload?kind=sjr", files={"file": ("x.csv", b"a;b\n1;2\n")})
    assert bad.status_code == 400

    monkey_target = settings.DATA_DIR / "sjr.csv"
    settings.SJR_FILE = monkey_target                      # restauré par monkeypatch à la fin
    good = client.post("/api/rankings/upload?kind=sjr",
                       files={"file": ("sjr.csv", (FIXTURES / "sjr_sample.csv").read_bytes())})
    assert good.json() == {"count": 3}
    assert monkey_target.exists()


def test_diagnostic(client):
    report = client.post("/api/diagnostic").json()
    assert [r["source"] for r in report] == ["arxiv", "openalex", "semantic_scholar", "pubmed"]
    assert all(r["ok"] for r in report)


def test_enrich_hindex_and_export(client):
    data = _search(client)
    r = client.post("/api/enrich/hindex", json={"search_id": data["search_id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    merged_key = next(p["key"] for p in data["papers"] if p["arxiv_id"] == "2610.04567")
    assert body["metrics"][merged_key]["h_max"] == 41
    assert body["metrics"][merged_key]["h_max_author"] == "Grace Liu"
    assert body["stats"]["found"] >= 1
    assert set(body["metrics"]) == {p["key"] for p in data["papers"]}

    again = client.post("/api/enrich/hindex", json={"search_id": data["search_id"]}).json()
    assert again["stats"]["cached"] is True

    csv_text = client.post("/api/export", json={
        "search_id": data["search_id"], "keys": [merged_key], "format": "csv",
    }).content.decode("utf-8-sig")
    header, row = csv_text.strip().splitlines()[:2]
    assert "h_index_max" in header
    columns = dict(zip(header.split(";"), row.split(";")))
    assert columns["h_index_max"] == "41" and columns["auteur_h_index_max"] == "Grace Liu"


def test_enrich_unknown_search(client):
    assert client.post("/api/enrich/hindex", json={"search_id": "nope"}).status_code == 404


def test_invalid_arxiv_category_rejected(client):
    r = client.post("/api/search", json={"topic": "x", "arxiv_categories": ['cs.LG") OR all:"x']})
    assert r.status_code == 422


def test_upload_too_large(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)
    r = client.post("/api/rankings/upload?kind=sjr", files={"file": ("x.csv", b"a" * 50)})
    assert r.status_code == 413


def test_unknown_api_route_is_404_not_html(client):
    r = client.get("/api/nexiste-pas")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
