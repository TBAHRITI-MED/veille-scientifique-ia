"""Source Semantic Scholar — Academic Graph API, endpoint /paper/search/bulk.

L'endpoint « bulk » accepte une syntaxe booléenne (+ ET, | OU, "expression")
et un tri par date, contrairement à /paper/search (tri par pertinence uniquement).
Clé optionnelle (SEMANTIC_SCHOLAR_API_KEY) : sans clé, le quota est partagé
entre tous les utilisateurs anonymes et les erreurs 429 sont fréquentes.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import settings
from models import CONFERENCE, JOURNAL, OTHER, PREPRINT, Paper
from sources import http
from sources.base import SourceResult
from sources.http import SourceError
from sources.query import SearchRequest, boolean_query

S2_BULK_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
FIELDS = (
    "title,abstract,authors,venue,publicationVenue,publicationDate,externalIds,"
    "url,openAccessPdf,citationCount,publicationTypes,journal"
)
# Sans clé : ~1 requête/s conseillée ; avec clé : 1 requête/s garantie.
THROTTLE = http.Throttle(1.1)

VENUE_TYPES = {"journal": JOURNAL, "conference": CONFERENCE}


def build_params(request: SearchRequest) -> dict:
    return {
        "query": boolean_query(request.concepts, and_op=" + ", or_op=" | "),
        "fields": FIELDS,
        "publicationDateOrYear": f"{request.date_from:%Y-%m-%d}:{request.date_to:%Y-%m-%d}",
        "sort": "publicationDate:desc",
    }


def _venue_type(paper: dict) -> str:
    venue = paper.get("publicationVenue") or {}
    venue_type = VENUE_TYPES.get((venue.get("type") or "").lower())
    if venue_type:
        return venue_type
    types = [t.lower() for t in paper.get("publicationTypes") or []]
    if "journalarticle" in types:
        return JOURNAL
    if "conference" in types:
        return CONFERENCE
    name = (venue.get("name") or paper.get("venue") or "").lower()
    if "arxiv" in name or "biorxiv" in name or "medrxiv" in name:
        return PREPRINT
    return OTHER


def parse_paper(paper: dict) -> Paper | None:
    if not paper.get("publicationDate") or not paper.get("title"):
        return None
    venue = paper.get("publicationVenue") or {}
    ids = paper.get("externalIds") or {}
    issn = [venue["issn"]] if venue.get("issn") else []
    pdf = (paper.get("openAccessPdf") or {}).get("url") or None
    pmid = ids.get("PubMed")

    return Paper(
        title=paper["title"],
        abstract=paper.get("abstract") or "",
        authors=[a["name"] for a in paper.get("authors") or [] if a.get("name")],
        published=datetime.strptime(paper["publicationDate"], "%Y-%m-%d").replace(tzinfo=timezone.utc),
        url=(paper.get("url")
             or (f"https://doi.org/{ids['DOI']}" if ids.get("DOI") else "")
             or f"https://www.semanticscholar.org/paper/{paper.get('paperId', '')}"),
        source="semantic_scholar",
        pdf_url=pdf,
        doi=ids.get("DOI"),
        arxiv_id=ids.get("ArXiv"),
        pmid=str(pmid) if pmid else None,
        venue=venue.get("name") or paper.get("venue") or (paper.get("journal") or {}).get("name"),
        venue_type=_venue_type(paper),
        venue_aliases=list(venue.get("alternate_names") or []),
        issn=issn,
        citation_count=paper.get("citationCount"),
    )


class SemanticScholarSource:
    name = "semantic_scholar"

    def search(self, request: SearchRequest) -> SourceResult:
        params = build_params(request)
        headers = {"x-api-key": settings.SEMANTIC_SCHOLAR_API_KEY} if settings.SEMANTIC_SCHOLAR_API_KEY else {}
        started = time.perf_counter()
        response = http.get(
            S2_BULK_URL, source="Semantic Scholar", throttle=THROTTLE, params=params, headers=headers
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceError(f"Réponse Semantic Scholar illisible : {exc}") from exc

        papers = [p for p in map(parse_paper, payload.get("data") or []) if p is not None]
        papers = papers[: request.max_results]        # bulk renvoie jusqu'à 1000 résultats
        return SourceResult(
            self.name, papers, payload.get("total"), params["query"], time.perf_counter() - started
        )
