"""Connecteurs OpenAlex, Semantic Scholar et PubMed (HTTP simulé à partir de fixtures)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import settings
from sources import http
from sources.http import SourceError
from sources.openalex_client import OpenAlexSource, build_params as openalex_params, rebuild_abstract
from sources.pubmed_client import PubMedSource, build_term, parse_articles
from sources.query import SearchRequest
from sources.semantic_scholar_client import SemanticScholarSource, build_params as s2_params

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
REQUEST = SearchRequest.last_days(
    "federated learning, medical imaging | radiology", days=30, max_results=20, now=NOW
)


class FakeResponse:
    def __init__(self, text: str):
        self.text = text
        self.status_code = 200

    def json(self):
        return json.loads(self.text)


@pytest.fixture
def fake_http(monkeypatch):
    """Remplace http.get : renvoie la fixture associée à l'URL et mémorise les appels."""
    calls = []
    routes = {}

    def fake_get(url, *, source, throttle, params=None, headers=None, **kwargs):
        calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        for fragment, text in routes.items():
            if fragment in url:
                return FakeResponse(text)
        raise AssertionError(f"URL inattendue : {url}")

    monkeypatch.setattr(http, "get", fake_get)
    return routes, calls


# --- OpenAlex ------------------------------------------------------------------

def test_openalex_params(monkeypatch):
    monkeypatch.setattr(settings, "OPENALEX_API_KEY", "k")
    monkeypatch.setattr(settings, "CONTACT_EMAIL", "me@example.org")
    params = openalex_params(REQUEST)
    assert params["filter"] == (
        'title_and_abstract.search:"federated learning" AND ("medical imaging" OR "radiology"),'
        "from_publication_date:2026-09-10,to_publication_date:2026-10-10"
    )
    assert params["sort"] == "publication_date:desc"
    assert params["api_key"] == "k" and params["mailto"] == "me@example.org"


def test_rebuild_abstract():
    assert rebuild_abstract({"world": [1], "Hello": [0], "again": [2]}) == "Hello world again"
    assert rebuild_abstract(None) == ""


def test_openalex_parsing(fake_http):
    routes, _ = fake_http
    routes["api.openalex.org"] = (FIXTURES / "openalex_sample.json").read_text()
    result = OpenAlexSource().search(REQUEST)

    assert result.total_results == 42
    journal, preprint, conference = result.papers
    assert journal.doi == "10.1016/j.media.2026.103456"
    assert journal.arxiv_id == "2610.04567"            # retrouvé via les « locations »
    assert journal.pmid == "41000001"
    assert journal.venue == "Medical Image Analysis" and journal.venue_type == "journal"
    assert journal.issn == ["13618415", "13618423"]
    assert journal.abstract == "We propose a personalized federated method."
    assert journal.citation_count == 3

    assert preprint.venue_type == "preprint"
    assert preprint.arxiv_id == "2610.09999"           # extrait du DOI arXiv
    assert preprint.abstract == ""

    assert conference.venue_type == "conference" and conference.venue == "MICCAI 2026"


# --- Semantic Scholar ------------------------------------------------------------

def test_s2_params():
    params = s2_params(REQUEST)
    assert params["query"] == '"federated learning" + ("medical imaging" | "radiology")'
    assert params["publicationDateOrYear"] == "2026-09-10:2026-10-10"
    assert params["sort"] == "publicationDate:desc"


def test_s2_parsing_and_api_key(fake_http, monkeypatch):
    monkeypatch.setattr(settings, "SEMANTIC_SCHOLAR_API_KEY", "secret")
    routes, calls = fake_http
    routes["semanticscholar.org"] = (FIXTURES / "semantic_scholar_sample.json").read_text()
    result = SemanticScholarSource().search(REQUEST)

    assert calls[0]["headers"] == {"x-api-key": "secret"}
    assert result.total_results == 57
    assert len(result.papers) == 2                      # l'article sans date est ignoré
    journal, conference = result.papers
    assert journal.arxiv_id == "2610.04567" and journal.issn == ["13618415"]
    assert journal.pdf_url is None                      # URL vide → None
    assert conference.venue_type == "conference"
    assert conference.venue_aliases == ["NeurIPS", "NIPS"]
    assert conference.url == "https://www.semanticscholar.org/paper/def456"
    assert conference.abstract == ""


# --- PubMed ----------------------------------------------------------------------

def test_pubmed_term():
    assert build_term(REQUEST) == (
        '"federated learning"[tiab] AND ("medical imaging"[tiab] OR "radiology"[tiab])'
    )


def test_pubmed_parsing():
    journal, preprint = parse_articles((FIXTURES / "pubmed_efetch.xml").read_text())

    assert journal.pmid == "41000001"
    assert journal.doi == "10.1016/j.media.2026.103456"
    assert journal.published == datetime(2026, 10, 8, tzinfo=timezone.utc)   # ArticleDate prioritaire
    assert journal.authors == ["Alice Martin", "FedX Consortium"]
    assert journal.abstract == (
        "Background : Hospitals cannot share raw images.\n"
        "Methods : We propose a personalized federated method."
    )
    assert journal.issn == ["13618423", "13618415"]
    assert journal.venue_aliases == ["Med Image Anal"]
    assert journal.pdf_url == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12345678/"

    assert preprint.venue_type == "preprint"
    assert preprint.published == datetime(2026, 9, 1, tzinfo=timezone.utc)  # « 2026 Sep-Oct »


def test_pubmed_search_two_calls(fake_http):
    routes, calls = fake_http
    routes["esearch"] = json.dumps({"esearchresult": {"count": "2", "idlist": ["41000001", "41000002"]}})
    routes["efetch"] = (FIXTURES / "pubmed_efetch.xml").read_text()
    result = PubMedSource().search(REQUEST)

    assert [c["url"].rsplit("/", 1)[-1] for c in calls] == ["esearch.fcgi", "efetch.fcgi"]
    assert calls[0]["params"]["datetype"] == "edat"
    assert calls[0]["params"]["mindate"] == "2026/09/10"
    assert calls[1]["params"]["id"] == "41000001,41000002"
    assert result.total_results == 2 and len(result.papers) == 2


def test_pubmed_no_result_skips_efetch(fake_http):
    routes, calls = fake_http
    routes["esearch"] = json.dumps({"esearchresult": {"count": "0", "idlist": []}})
    assert PubMedSource().search(REQUEST).papers == []
    assert len(calls) == 1


def test_pubmed_error_message(fake_http):
    routes, _ = fake_http
    routes["esearch"] = json.dumps({"esearchresult": {"ERROR": "Invalid query"}})
    with pytest.raises(SourceError, match="Invalid query"):
        PubMedSource().search(REQUEST)
