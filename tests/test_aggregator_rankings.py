import json
from datetime import datetime, timezone
from pathlib import Path

from aggregator import deduplicate, search_all
from models import Paper
from quality.rankings import Rankings, parse_core, parse_sjr
from sources import arxiv_client, openalex_client, pubmed_client, semantic_scholar_client
from sources.base import SourceResult
from sources.query import SearchRequest

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
REQUEST = SearchRequest.last_days("federated learning", days=30, now=NOW)


def _all_fixture_papers() -> list[Paper]:
    arxiv, _ = arxiv_client.parse_feed((FIXTURES / "arxiv_sample.xml").read_text())
    openalex = [openalex_client.parse_work(w) for w in
                json.loads((FIXTURES / "openalex_sample.json").read_text())["results"]]
    s2 = [p for p in map(semantic_scholar_client.parse_paper,
                         json.loads((FIXTURES / "semantic_scholar_sample.json").read_text())["data"]) if p]
    pubmed = pubmed_client.parse_articles((FIXTURES / "pubmed_efetch.xml").read_text())
    return arxiv[:2] + openalex + s2 + pubmed


# --- Dédoublonnage ------------------------------------------------------------------

def test_same_article_from_four_sources_is_merged():
    papers = deduplicate(_all_fixture_papers())
    merged = next(p for p in papers if p.doi == "10.1016/j.media.2026.103456")

    assert merged.sources == ["arxiv", "openalex", "semantic_scholar", "pubmed"]
    assert merged.venue == "Medical Image Analysis"          # la revue l'emporte sur le préprint
    assert merged.venue_type == "journal"
    assert merged.url == "https://doi.org/10.1016/j.media.2026.103456"   # version publiée
    assert merged.arxiv_id == "2610.04567" and merged.pmid == "41000001"
    assert merged.citation_count == 5                         # maximum entre sources
    assert "longer abstract" in merged.abstract               # abstract le plus complet
    assert merged.published == datetime(2026, 10, 8, tzinfo=timezone.utc)   # date la plus récente
    assert set(merged.issn) == {"13618415", "13618423"}


def test_dedup_counts():
    raw = _all_fixture_papers()
    papers = deduplicate(raw)
    assert len(raw) == 9
    # 1 article × 4 sources fusionné ; les 5 autres sont distincts.
    assert len(papers) == 6


def test_title_match_requires_long_title():
    base = dict(abstract="", authors=[], published=NOW, url="u", source="arxiv")
    short = [Paper(title="Short title", **base), Paper(title="Short title", **{**base, "source": "pubmed"})]
    assert len(deduplicate(short)) == 2


# --- Agrégation --------------------------------------------------------------------

class _OkSource:
    name = "ok"

    def search(self, request):
        p = Paper(title="Only one paper from a working source here", abstract="", authors=[],
                  published=NOW, url="u", source="arxiv")
        return SourceResult(self.name, [p], 1, "q")


class _BrokenSource:
    name = "broken"

    def search(self, request):
        raise RuntimeError("quota dépassé")


def test_search_all_isolates_errors():
    result = search_all([_OkSource(), _BrokenSource()], REQUEST)
    assert len(result.papers) == 1
    assert result.errors == {"broken": "quota dépassé"}
    assert list(result.by_source) == ["ok"]


# --- Classements ---------------------------------------------------------------------

def _rankings() -> Rankings:
    return Rankings.load(FIXTURES / "sjr_sample.csv", FIXTURES / "core_sample.csv")


def test_parse_sjr():
    mapping, journals = parse_sjr((FIXTURES / "sjr_sample.csv").read_text())
    assert journals == 3
    assert mapping["13618415"] == "Q1" and mapping["1558254X"] == "Q1"
    assert mapping["12345678"] == "Q3"
    assert "87654321" not in mapping                    # quartile « - » ignoré


def test_parse_core():
    acronyms, titles = parse_core((FIXTURES / "core_sample.csv").read_text())
    assert acronyms["NEURIPS"] == "A*" and acronyms["MICCAI"] == "A"
    assert "IV" not in acronyms                         # acronyme trop court, risque de faux positif
    assert "SUW" not in acronyms                        # non classé


def test_levels_on_merged_fixtures():
    rankings = _rankings()
    papers = deduplicate(_all_fixture_papers())
    rankings.apply(papers)
    levels = {p.title[:40]: p.level for p in papers}

    assert levels["Personalized Federated Learning for Ches"] == "Q1"   # ISSN SJR
    assert levels["Federated Foundation Models at MICCAI"] == "A"       # « MICCAI 2026 »
    assert levels["Federated LLM Fine-Tuning with Different"] == "A*"   # titre CORE
    assert levels["A Preprint Only Indexed Through OpenAlex"] == "Préprint"
    assert levels["A medRxiv preprint on federated radiolog"] == "Préprint"


def test_core_title_containment_and_lowercase_word_not_acronym():
    rankings = _rankings()
    base = dict(abstract="", authors=[], published=NOW, url="u", source="openalex",
                venue_type="conference")
    neurips = Paper(title="t", venue="Advances in Neural Information Processing Systems 39", **base)
    assert rankings.classify(neurips) == "A*"
    unknown = Paper(title="t", venue="Workshop on miccai-like ideas", **base)
    assert rankings.classify(unknown) == "Non classé"


def test_unranked_journal_and_empty_rankings():
    paper = Paper(title="t", abstract="", authors=[], published=NOW, url="u", source="pubmed",
                  venue="Unknown Journal", venue_type="journal", issn=["0000-0000"])
    assert _rankings().classify(paper) == "Non classé"
    assert Rankings().classify(paper) == "Non classé"
    assert Rankings().is_empty
