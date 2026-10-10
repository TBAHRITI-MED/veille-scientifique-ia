from datetime import datetime, timezone
from pathlib import Path

import pytest

from sources import arxiv_client, http
from sources.arxiv_client import ArxivSource, build_query, parse_feed
from sources.http import SourceError
from sources.query import SearchRequest, parse_topic

FIXTURE = (Path(__file__).parent / "fixtures" / "arxiv_sample.xml").read_text()
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


# --- Requête -----------------------------------------------------------------

def test_parse_topic_and_or():
    assert parse_topic("federated learning, medical imaging | radiology") == [
        ["federated learning"],
        ["medical imaging", "radiology"],
    ]


def test_parse_topic_strips_special_chars_keeps_inner_hyphen():
    assert parse_topic(' "LLM" (agents) , , | ') == [["LLM agents"]]
    assert parse_topic("fine-tuning, -noise") == [["fine-tuning"], ["noise"]]


def test_build_query_structure():
    query = build_query(
        "federated learning, medical imaging | radiology",
        datetime(2026, 9, 10), datetime(2026, 10, 10), ["cs.LG", "eess.IV"],
    )
    assert query == (
        '(ti:"federated learning" OR abs:"federated learning") AND '
        '(ti:"medical imaging" OR abs:"medical imaging" OR ti:"radiology" OR abs:"radiology") AND '
        "(cat:cs.LG OR cat:eess.IV) AND "
        "submittedDate:[202609100000 TO 202610102359]"
    )


def test_build_query_empty_topic():
    with pytest.raises(ValueError):
        build_query(" , | ", NOW, NOW)


# --- Parsing -----------------------------------------------------------------

def test_parse_feed_fields():
    papers, total = parse_feed(FIXTURE)
    assert total == 137
    assert len(papers) == 3

    p = papers[0]
    assert p.arxiv_id == "2610.04567"
    assert p.paper_id == "arXiv:2610.04567"
    assert p.title == ("Personalized Federated Learning for "
                       "Chest X-ray Classification under Label Skew")
    assert p.abstract.startswith("We propose")
    assert p.authors_short == "Alice Martin, Bob Chen, Chloé Durand et al."
    assert p.published == datetime(2026, 10, 5, 17, 59, 58, tzinfo=timezone.utc)
    assert p.url == "https://arxiv.org/abs/2610.04567"
    assert p.pdf_url == "http://arxiv.org/pdf/2610.04567v2"
    assert p.venue_type == "preprint"
    assert p.sources == ["arxiv"]
    assert p.categories == ["cs.CV", "cs.LG"]


def test_parse_feed_api_error_entry():
    error_feed = """<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <id>http://arxiv.org/api/errors#incorrect_id_format</id>
      <summary>incorrect id format</summary></entry></feed>"""
    with pytest.raises(SourceError, match="incorrect id format"):
        parse_feed(error_feed)


def test_parse_feed_invalid_xml():
    with pytest.raises(SourceError):
        parse_feed("<not xml")


# --- Recherche complète (HTTP simulé) -----------------------------------------

def test_arxiv_source_filters_by_date(monkeypatch):
    captured = {}

    def fake_fetch(params):
        captured.update(params)
        return FIXTURE

    monkeypatch.setattr(arxiv_client, "_fetch_feed", fake_fetch)
    request = SearchRequest.last_days("federated learning", days=30, max_results=500, now=NOW)
    result = ArxivSource().search(request)

    assert captured["sortBy"] == "submittedDate"
    assert captured["max_results"] == arxiv_client.MAX_RESULTS_LIMIT   # plafonné
    assert [p.arxiv_id for p in result.papers] == ["2610.04567", "2609.11111"]
    assert result.total_results == 137


# --- Client HTTP commun --------------------------------------------------------

class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


def test_http_retries_then_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(http.requests, "get", lambda *a, **k: calls.append(1) or _Resp(503))
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    with pytest.raises(SourceError, match="injoignable"):
        http.get("https://x", source="X", throttle=http.Throttle(0))
    assert len(calls) == 3


def test_http_client_error_no_retry(monkeypatch):
    calls = []
    monkeypatch.setattr(http.requests, "get", lambda *a, **k: calls.append(1) or _Resp(400, "bad"))
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    with pytest.raises(SourceError, match="400"):
        http.get("https://x", source="X", throttle=http.Throttle(0))
    assert len(calls) == 1
