"""Fixture partagée : client de l'API avec les 4 sources et le h-index simulés (aucun appel réseau)."""

from datetime import datetime, timedelta, timezone
from json import dumps, loads
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import settings
from api import main
from sources import arxiv_client, http

FIXTURES = Path(__file__).parent / "fixtures"


class _Resp:
    status_code = 200

    def __init__(self, text):
        self.text = text

    def json(self):
        return loads(self.text)


@pytest.fixture
def client(monkeypatch, tmp_path):
    routes = {
        "api.openalex.org": (FIXTURES / "openalex_sample.json").read_text(),
        "semanticscholar.org": (FIXTURES / "semantic_scholar_sample.json").read_text(),
        "esearch": dumps({"esearchresult": {"count": "2", "idlist": ["41000001", "41000002"]}}),
        "efetch": (FIXTURES / "pubmed_efetch.xml").read_text(),
    }
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _Resp(next(text for fragment, text in routes.items() if fragment in url))

    # Les articles arXiv sont filtrés sur les 30 derniers jours réels : on recale leurs dates.
    now = datetime.now(timezone.utc)
    feed = (FIXTURES / "arxiv_sample.xml").read_text()
    for old, days_ago in (("2026-10-05T17:59:58Z", 5), ("2026-09-20T09:00:00Z", 20)):
        feed = feed.replace(old, (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"))

    monkeypatch.setattr(http, "get", fake_get)
    monkeypatch.setattr(arxiv_client, "_fetch_feed", lambda params: calls.append("arxiv") or feed)
    monkeypatch.setattr(settings, "SJR_FILE", FIXTURES / "sjr_sample.csv")
    monkeypatch.setattr(settings, "CORE_FILE", FIXTURES / "core_sample.csv")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "CACHE_FILE", tmp_path / "cache.db")
    monkeypatch.setattr(settings, "PROFILE_FILE", tmp_path / "profil.txt")
    # Le .env du développeur ne doit pas influencer les tests.
    monkeypatch.setattr(settings, "APP_PASSWORD", None)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)

    def fake_post(url, json=None, **kwargs):  # noqa: A002 (même nom que l'argument de requests)
        calls.append(url)
        return _Resp(dumps([
            {"authors": [{"name": "Alice Martin", "hIndex": 12}, {"name": "Grace Liu", "hIndex": 41}]}
            if i == "ARXIV:2610.04567" else None
            for i in json["ids"]
        ]))
    monkeypatch.setattr(http, "post", fake_post)
    main.cache.clear()
    test_client = TestClient(main.app)
    test_client.calls = calls
    return test_client
