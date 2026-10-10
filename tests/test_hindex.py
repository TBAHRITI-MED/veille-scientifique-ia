"""h-index des auteurs : Semantic Scholar (batch), repli OpenAlex, cache SQLite."""

from datetime import datetime, timezone

import pytest

from enrichment import hindex
from enrichment.cache import JsonCache
from models import Paper
from sources import http

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def _paper(title, **ids):
    return Paper(title=title, abstract="", authors=["x"], published=NOW, url="u", source="arxiv", **ids)


ARXIV_PAPER = _paper("Federated chest X-ray", arxiv_id="2610.04567")
DOI_PAPER = _paper("Journal paper", doi="10.1016/j.media.2026.103456")
RECENT_PAPER = _paper("Very recent preprint", arxiv_id="2610.09999")     # inconnu de S2
GHOST_PAPER = _paper("Nobody knows me", pmid="41000009")                 # inconnu partout

S2_RESPONSE = [
    {"paperId": "a", "authors": [
        {"authorId": "1", "name": "Alice Martin", "hIndex": 12},
        {"authorId": "2", "name": "Bob Chen", "hIndex": 4},
        {"authorId": "3", "name": "Grace Liu", "hIndex": 41},
    ]},
    {"paperId": "b", "authors": [{"authorId": "4", "name": "Eve Laurent", "hIndex": None}]},   # aucun h connu
    None,                                                                                      # inconnu
    None,
]
OPENALEX_WORKS = {"results": [{
    "doi": "https://doi.org/10.48550/arxiv.2610.09999",
    "authorships": [
        {"author": {"id": "https://openalex.org/A111", "display_name": "Zoé Petit"}},
        {"author": {"id": "https://openalex.org/A222", "display_name": "Hugo Moreau"}},
    ],
}]}
OPENALEX_AUTHORS = {"results": [
    {"id": "https://openalex.org/A111", "summary_stats": {"h_index": 3}},
    {"id": "https://openalex.org/A222", "summary_stats": {"h_index": 27}},
]}


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


@pytest.fixture
def fake_apis(monkeypatch):
    calls = []

    def fake_post(url, *, json=None, params=None, **kwargs):
        calls.append(("POST", url, json, params))
        ids = json["ids"]
        by_id = {"ARXIV:2610.04567": S2_RESPONSE[0], "DOI:10.1016/j.media.2026.103456": S2_RESPONSE[1]}
        return _Resp([by_id.get(i) for i in ids])

    def fake_get(url, *, params=None, **kwargs):
        calls.append(("GET", url, None, params))
        return _Resp(OPENALEX_WORKS if url.endswith("/works") else OPENALEX_AUTHORS)

    monkeypatch.setattr(http, "post", fake_post)
    monkeypatch.setattr(http, "get", fake_get)
    return calls


# --- Calculs --------------------------------------------------------------------------

def test_identifiers_priority():
    assert hindex.s2_identifier(_paper("t", arxiv_id="1", doi="10.1/x")) == "ARXIV:1"
    assert hindex.s2_identifier(DOI_PAPER) == "DOI:10.1016/j.media.2026.103456"
    assert hindex.s2_identifier(GHOST_PAPER) == "PMID:41000009"
    assert hindex.openalex_doi(RECENT_PAPER) == "10.48550/arxiv.2610.09999"
    assert hindex.openalex_doi(_paper("t", doi="10.1/a,b")) is None      # casserait le filtre


def test_paper_metrics():
    metric = hindex.parse_s2_paper(S2_RESPONSE[0])
    assert (metric.h_max, metric.h_max_author, metric.h_first, metric.h_last) == (41, "Grace Liu", 12, 41)
    assert hindex.parse_s2_paper(S2_RESPONSE[1]) is None                 # aucun h-index connu
    assert hindex.parse_s2_paper(None) is None
    assert hindex.PaperHIndex.from_dict(metric.to_dict()).to_dict() == metric.to_dict()


# --- Sources --------------------------------------------------------------------------

def test_semantic_scholar_batch_alignment(fake_apis, monkeypatch):
    monkeypatch.setattr(hindex, "S2_BATCH_SIZE", 2)                     # force 2 appels
    found = hindex.fetch_semantic_scholar([ARXIV_PAPER, DOI_PAPER, RECENT_PAPER])
    posts = [c for c in fake_apis if c[0] == "POST"]
    assert [c[2]["ids"] for c in posts] == [
        ["ARXIV:2610.04567", "DOI:10.1016/j.media.2026.103456"], ["ARXIV:2610.09999"],
    ]
    assert posts[0][3] == {"fields": "authors.name,authors.hIndex"}
    assert list(found) == ["arXiv:2610.04567"]


def test_openalex_fallback(fake_apis):
    found = hindex.fetch_openalex([RECENT_PAPER])
    works, authors = [c for c in fake_apis if c[0] == "GET"]
    assert works[3]["filter"] == "doi:10.48550/arxiv.2610.09999"
    assert authors[3]["filter"] == "openalex:A111|A222"
    metric = found["arXiv:2610.09999"]
    assert metric.source == "openalex"
    assert (metric.h_max, metric.h_max_author, metric.h_last) == (27, "Hugo Moreau", 27)


# --- Orchestration et cache -----------------------------------------------------------

def test_enrich_uses_both_sources_then_cache(fake_apis, tmp_path):
    cache = JsonCache(tmp_path / "cache.db")
    papers = [ARXIV_PAPER, DOI_PAPER, RECENT_PAPER, GHOST_PAPER]

    first = hindex.enrich(papers, cache)
    assert first.metrics["arXiv:2610.04567"].source == "semantic_scholar"
    assert first.metrics["arXiv:2610.09999"].source == "openalex"
    assert first.metrics["PMID:41000009"] is None
    assert first.by_source == {"semantic_scholar": 1, "openalex": 1}
    assert first.errors == {}

    calls_before = len(fake_apis)
    second = hindex.enrich(papers, cache)
    assert len(fake_apis) == calls_before                              # tout vient du cache
    assert second.from_cache == 4
    assert second.metrics["arXiv:2610.04567"].h_max == 41
    assert second.metrics["PMID:41000009"] is None


def test_enrich_survives_semantic_scholar_outage(fake_apis, monkeypatch, tmp_path):
    def down(*a, **k):
        raise http.SourceError("Semantic Scholar a répondu 429")
    monkeypatch.setattr(http, "post", down)
    cache = JsonCache(tmp_path / "cache.db")

    result = hindex.enrich([RECENT_PAPER, GHOST_PAPER], cache)
    assert result.errors == {"semantic_scholar": "Semantic Scholar a répondu 429"}
    assert result.metrics["arXiv:2610.09999"].source == "openalex"      # repli OpenAlex
    # « introuvable » n'est pas mémorisé quand une source était en panne
    assert cache.get_many(hindex.CACHE_NAMESPACE, ["PMID:41000009"]) == {}


def test_cache_expiry(tmp_path, monkeypatch):
    cache = JsonCache(tmp_path / "c.db")
    cache.set_many("ns", {"k": {"v": 1}}, ttl_seconds=60)
    assert cache.get_many("ns", ["k", "absent"]) == {"k": {"v": 1}}
    monkeypatch.setattr("enrichment.cache.time.time", lambda: 10**12)
    assert cache.get_many("ns", ["k"]) == {}
