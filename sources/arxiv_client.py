"""Source arXiv — API publique Atom (https://info.arxiv.org/help/api/).

Préprints uniquement : pas de revue, donc pas de quartile.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime

from models import PREPRINT, Paper
from sources import http
from sources.base import SourceResult
from sources.http import SourceError
from sources.query import SearchRequest, parse_topic

ARXIV_API_URL = "https://export.arxiv.org/api/query"
MAX_RESULTS_LIMIT = 200
THROTTLE = http.Throttle(3.1)          # arXiv demande au moins 3 s entre deux requêtes

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

ArxivError = SourceError   # alias historique


def build_query(
    topic: str, date_from: datetime, date_to: datetime, categories: list[str] | None = None
) -> str:
    """Construit la chaîne `search_query` de l'API arXiv."""
    concepts = parse_topic(topic)
    if not concepts:
        raise ValueError("Le sujet est vide.")

    clauses = []
    for synonyms in concepts:
        parts = []
        for term in synonyms:
            parts.append(f'ti:"{term}"')
            parts.append(f'abs:"{term}"')
        clauses.append("(" + " OR ".join(parts) + ")")
    if categories:
        clauses.append("(" + " OR ".join(f"cat:{c}" for c in categories) + ")")
    clauses.append(f"submittedDate:[{date_from:%Y%m%d}0000 TO {date_to:%Y%m%d}2359]")
    return " AND ".join(clauses)


def _text(element: ET.Element, path: str) -> str:
    found = element.find(path, NS)
    if found is None or found.text is None:
        return ""
    return re.sub(r"\s+", " ", found.text).strip()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _extract_arxiv_id(entry_id: str) -> str:
    """'http://arxiv.org/abs/2410.01234v2' → '2410.01234' (gère aussi 'hep-th/9901001v1')."""
    return re.sub(r"v\d+$", "", entry_id.split("/abs/")[-1])


def parse_feed(xml_text: str) -> tuple[list[Paper], int]:
    """Transforme la réponse Atom d'arXiv en liste de `Paper`."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceError(f"Réponse arXiv illisible : {exc}") from exc

    total_text = _text(root, "opensearch:totalResults")
    total = int(total_text) if total_text.isdigit() else 0

    papers: list[Paper] = []
    for entry in root.findall("atom:entry", NS):
        entry_id = _text(entry, "atom:id")
        if "arxiv.org/api/errors" in entry_id:
            raise SourceError(f"Requête refusée par arXiv : {_text(entry, 'atom:summary')}")

        arxiv_id = _extract_arxiv_id(entry_id)
        pdf_url = next(
            (l.get("href") for l in entry.findall("atom:link", NS) if l.get("title") == "pdf"), None
        )
        primary = entry.find("arxiv:primary_category", NS)
        papers.append(Paper(
            title=_text(entry, "atom:title"),
            abstract=_text(entry, "atom:summary"),
            authors=[_text(a, "atom:name") for a in entry.findall("atom:author", NS)],
            published=_parse_datetime(_text(entry, "atom:published")),
            url=f"https://arxiv.org/abs/{arxiv_id}",
            source="arxiv",
            pdf_url=pdf_url,
            doi=_text(entry, "arxiv:doi") or None,     # DOI de la version publiée, si connue
            arxiv_id=arxiv_id,
            venue="arXiv",
            venue_type=PREPRINT,
            primary_category=primary.get("term") if primary is not None else None,
            categories=[c.get("term") for c in entry.findall("atom:category", NS)],
        ))
    return papers, total


def _fetch_feed(params: dict) -> str:
    return http.get(ARXIV_API_URL, source="arXiv", throttle=THROTTLE, params=params).text


class ArxivSource:
    name = "arxiv"

    def search(self, request: SearchRequest) -> SourceResult:
        query = build_query(
            request.topic, request.date_from, request.date_to, list(request.arxiv_categories)
        )
        params = {
            "search_query": query,
            "start": 0,
            "max_results": min(request.max_results, MAX_RESULTS_LIMIT),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        started = time.perf_counter()
        papers, total = parse_feed(_fetch_feed(params))
        papers = [p for p in papers if p.published >= request.date_from]
        return SourceResult(self.name, papers, total, query, time.perf_counter() - started)
