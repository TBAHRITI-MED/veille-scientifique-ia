"""Source OpenAlex — https://developers.openalex.org

Couverture très large (revues, conférences, préprints) et ISSN de la revue,
indispensable pour retrouver le quartile SJR.
Gratuit : clé optionnelle (OPENALEX_API_KEY) qui augmente le budget quotidien.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import settings
from models import CONFERENCE, JOURNAL, OTHER, PREPRINT, Paper
from sources import http
from sources.base import SourceResult
from sources.http import SourceError
from sources.query import SearchRequest, boolean_query

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
MAX_PER_PAGE = 100
THROTTLE = http.Throttle(0.2)

SOURCE_TYPES = {
    "journal": JOURNAL,
    "conference": CONFERENCE,
    "repository": PREPRINT,      # arXiv, medRxiv, HAL…
}


def build_params(request: SearchRequest) -> dict:
    """Filtre booléen sur titre + abstract, fenêtre de dates, tri par date décroissante."""
    query = boolean_query(request.concepts)
    filters = [
        f"title_and_abstract.search:{query}",
        f"from_publication_date:{request.date_from:%Y-%m-%d}",
        f"to_publication_date:{request.date_to:%Y-%m-%d}",
    ]
    params = {
        "filter": ",".join(filters),
        "sort": "publication_date:desc",
        "per_page": min(request.max_results, MAX_PER_PAGE),
    }
    if settings.OPENALEX_API_KEY:
        params["api_key"] = settings.OPENALEX_API_KEY
    if settings.CONTACT_EMAIL:
        params["mailto"] = settings.CONTACT_EMAIL
    return params


def rebuild_abstract(inverted_index: dict | None) -> str:
    """OpenAlex fournit l'abstract sous forme d'index inversé {mot: [positions]}."""
    if not inverted_index:
        return ""
    positions = [(pos, word) for word, poss in inverted_index.items() for pos in poss]
    return " ".join(word for _, word in sorted(positions))


def _strip_prefix(value: str | None, prefix: str) -> str | None:
    if not value:
        return None
    return value.removeprefix(prefix) or None


def _arxiv_id(work: dict) -> str | None:
    """Identifiant arXiv si l'une des versions de l'article est déposée sur arXiv."""
    for location in work.get("locations") or []:
        url = location.get("landing_page_url") or ""
        if "arxiv.org/abs/" in url:
            return re.sub(r"v\d+$", "", url.split("/abs/")[-1])
    return None


def parse_work(work: dict) -> Paper:
    location = work.get("primary_location") or {}
    venue = location.get("source") or {}
    venue_type = SOURCE_TYPES.get(venue.get("type"), OTHER)
    if work.get("type") == "preprint":
        venue_type = PREPRINT

    issn = list(venue.get("issn") or [])
    if venue.get("issn_l") and venue["issn_l"] not in issn:
        issn.insert(0, venue["issn_l"])

    published = datetime.strptime(work["publication_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    best_oa = work.get("best_oa_location") or {}
    ids = work.get("ids") or {}
    doi = work.get("doi")

    return Paper(
        title=work.get("display_name") or work.get("title") or "",
        abstract=rebuild_abstract(work.get("abstract_inverted_index")),
        authors=[
            a["author"]["display_name"]
            for a in work.get("authorships") or []
            if (a.get("author") or {}).get("display_name")
        ],
        published=published,
        url=doi or location.get("landing_page_url") or work.get("id", ""),
        source="openalex",
        pdf_url=best_oa.get("pdf_url") or location.get("pdf_url"),
        doi=doi,
        arxiv_id=_arxiv_id(work),
        pmid=_strip_prefix(ids.get("pmid"), "https://pubmed.ncbi.nlm.nih.gov/"),
        venue=venue.get("display_name"),
        venue_type=venue_type,
        issn=issn,
        citation_count=work.get("cited_by_count"),
    )


class OpenAlexSource:
    name = "openalex"

    def search(self, request: SearchRequest) -> SourceResult:
        params = build_params(request)
        started = time.perf_counter()
        response = http.get(OPENALEX_WORKS_URL, source="OpenAlex", throttle=THROTTLE, params=params)
        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceError(f"Réponse OpenAlex illisible : {exc}") from exc

        papers = []
        for work in payload.get("results", []):
            if work.get("publication_date") and work.get("display_name"):
                papers.append(parse_work(work))
        total = (payload.get("meta") or {}).get("count")
        return SourceResult(self.name, papers, total, params["filter"], time.perf_counter() - started)
