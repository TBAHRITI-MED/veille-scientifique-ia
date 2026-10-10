"""Interroge plusieurs sources en parallèle, isole leurs erreurs et fusionne les doublons."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from models import CONFERENCE, JOURNAL, OTHER, PREPRINT, Paper, normalize_title
from sources.base import Source, SourceResult
from sources.query import SearchRequest

# Quand deux sources décrivent le même article, on garde le support le plus informatif.
VENUE_PRIORITY = {JOURNAL: 0, CONFERENCE: 1, OTHER: 2, PREPRINT: 3}
MIN_TITLE_LENGTH_FOR_MATCH = 25


@dataclass
class AggregatedResult:
    papers: list[Paper]
    by_source: dict[str, SourceResult] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    raw_count: int = 0                 # articles avant dédoublonnage
    seconds: float = 0.0

    @property
    def duplicates_merged(self) -> int:
        return self.raw_count - len(self.papers)


def dedup_keys(paper: Paper) -> list[str]:
    keys = []
    if paper.doi:
        keys.append(f"doi:{paper.doi}")
    if paper.arxiv_id:
        keys.append(f"arxiv:{paper.arxiv_id.lower()}")
    if paper.pmid:
        keys.append(f"pmid:{paper.pmid}")
    title = normalize_title(paper.title)
    if len(title) >= MIN_TITLE_LENGTH_FOR_MATCH:
        keys.append(f"title:{title}")
    return keys


def merge(target: Paper, other: Paper) -> None:
    """Complète `target` avec les informations de `other` (même article, autre source)."""
    for source in other.sources:
        if source not in target.sources:
            target.sources.append(source)

    if VENUE_PRIORITY[other.venue_type] < VENUE_PRIORITY[target.venue_type]:
        target.venue, target.venue_type = other.venue, other.venue_type
        target.venue_aliases, target.issn = other.venue_aliases, other.issn
        target.url = other.url            # on pointe vers la version publiée, pas le préprint
    else:
        if not target.venue and other.venue:
            target.venue = other.venue
        for alias in other.venue_aliases:
            if alias not in target.venue_aliases:
                target.venue_aliases.append(alias)
        if other.venue_type == target.venue_type:
            target.issn += [i for i in other.issn if i not in target.issn]

    target.doi = target.doi or other.doi
    target.arxiv_id = target.arxiv_id or other.arxiv_id
    target.pmid = target.pmid or other.pmid
    target.pdf_url = target.pdf_url or other.pdf_url
    if len(other.abstract) > len(target.abstract):
        target.abstract = other.abstract
    if len(other.authors) > len(target.authors):
        target.authors = other.authors
    if other.citation_count is not None:
        target.citation_count = max(target.citation_count or 0, other.citation_count)
    # On garde la date la plus récente : c'est elle qui fait entrer l'article dans la fenêtre.
    target.published = max(target.published, other.published)
    target.categories = target.categories or other.categories
    target.primary_category = target.primary_category or other.primary_category


def deduplicate(papers: list[Paper]) -> list[Paper]:
    merged: list[Paper] = []
    index: dict[str, int] = {}
    for paper in papers:
        keys = dedup_keys(paper)
        position = next((index[k] for k in keys if k in index), None)
        if position is None:
            position = len(merged)
            merged.append(paper)
        else:
            merge(merged[position], paper)
        for key in dedup_keys(merged[position]):
            index[key] = position
    return merged


def _run(source: Source, request: SearchRequest) -> SourceResult:
    return source.search(request)


def search_all(sources: list[Source], request: SearchRequest) -> AggregatedResult:
    """Lance toutes les sources en parallèle ; une source en erreur n'empêche pas les autres."""
    started = time.perf_counter()
    result = AggregatedResult(papers=[])
    with ThreadPoolExecutor(max_workers=max(1, len(sources))) as pool:
        futures = {source.name: pool.submit(_run, source, request) for source in sources}
        collected: list[Paper] = []
        for name, future in futures.items():
            try:
                source_result = future.result()
            except Exception as exc:          # erreur réseau, quota, format inattendu…
                result.errors[name] = str(exc) or exc.__class__.__name__
                continue
            result.by_source[name] = source_result
            collected.extend(source_result.papers)

    result.raw_count = len(collected)
    result.papers = sorted(deduplicate(collected), key=lambda p: p.published, reverse=True)
    result.seconds = time.perf_counter() - started
    return result
