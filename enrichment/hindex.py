"""h-index des auteurs d'un article.

arXiv ne fournit aucune métrique d'auteur : on la récupère ailleurs, en deux temps.
1. Semantic Scholar, endpoint /paper/batch : jusqu'à 500 articles par appel, identifiés
   par leur ID arXiv, DOI ou PMID ; chaque auteur y porte son `hIndex`.
2. OpenAlex, pour les articles que Semantic Scholar ne connaît pas encore (indexation
   récente) : works (par DOI) → identifiants d'auteurs → authors.summary_stats.h_index.

Les valeurs diffèrent d'une base à l'autre (et de Google Scholar) : la source est gardée
avec chaque résultat. Un auteur mal désambiguïsé peut aussi fausser son h-index.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import settings
from models import Paper, normalize_doi
from enrichment.cache import JsonCache
from sources import http

S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_BATCH_SIZE = 500
S2_THROTTLE = http.Throttle(1.1)

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
OPENALEX_AUTHORS_URL = "https://api.openalex.org/authors"
OPENALEX_FILTER_SIZE = 50          # valeurs par filtre « a|b|c », pour garder des URL courtes
OPENALEX_THROTTLE = http.Throttle(0.2)

CACHE_NAMESPACE = "hindex"
TTL_FOUND = 7 * 24 * 3600          # un h-index trouvé reste valable une semaine
TTL_MISSING = 24 * 3600            # article pas encore indexé : on réessaie le lendemain


@dataclass
class AuthorH:
    name: str
    h_index: int | None


@dataclass
class PaperHIndex:
    authors: list[AuthorH]
    source: str                    # "semantic_scholar" ou "openalex"

    @property
    def known(self) -> list[AuthorH]:
        return [a for a in self.authors if a.h_index is not None]

    @property
    def h_max(self) -> int | None:
        return max((a.h_index for a in self.known), default=None)

    @property
    def h_max_author(self) -> str | None:
        known = self.known
        return max(known, key=lambda a: a.h_index).name if known else None

    @property
    def h_first(self) -> int | None:
        return self.authors[0].h_index if self.authors else None

    @property
    def h_last(self) -> int | None:
        """Dernier auteur : en général le responsable de l'équipe."""
        return self.authors[-1].h_index if self.authors else None

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "authors": [{"name": a.name, "h_index": a.h_index} for a in self.authors],
            "h_max": self.h_max,
            "h_max_author": self.h_max_author,
            "h_first": self.h_first,
            "h_last": self.h_last,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PaperHIndex":
        return cls([AuthorH(a["name"], a["h_index"]) for a in data["authors"]], data["source"])


@dataclass
class EnrichResult:
    metrics: dict[str, PaperHIndex | None]           # clé d'article → h-index (None = introuvable)
    from_cache: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0


# ---------------------------------------------------------------------- Semantic Scholar

def s2_identifier(paper: Paper) -> str | None:
    if paper.arxiv_id:
        return f"ARXIV:{paper.arxiv_id}"
    if paper.doi:
        return f"DOI:{paper.doi}"
    if paper.pmid:
        return f"PMID:{paper.pmid}"
    return None


def parse_s2_paper(item: dict | None) -> PaperHIndex | None:
    if not item or not item.get("authors"):
        return None
    authors = [AuthorH(a.get("name") or "?", a.get("hIndex")) for a in item["authors"]]
    return PaperHIndex(authors, "semantic_scholar") if any(a.h_index is not None for a in authors) else None


def fetch_semantic_scholar(papers: list[Paper]) -> dict[str, PaperHIndex]:
    targets = [(p.paper_id, s2_identifier(p)) for p in papers]
    targets = [(key, ident) for key, ident in targets if ident]
    headers = {"x-api-key": settings.SEMANTIC_SCHOLAR_API_KEY} if settings.SEMANTIC_SCHOLAR_API_KEY else {}
    found: dict[str, PaperHIndex] = {}
    for start in range(0, len(targets), S2_BATCH_SIZE):
        chunk = targets[start:start + S2_BATCH_SIZE]
        response = http.post(
            S2_BATCH_URL, source="Semantic Scholar", throttle=S2_THROTTLE, headers=headers,
            params={"fields": "authors.name,authors.hIndex"}, json={"ids": [ident for _, ident in chunk]},
        )
        items = response.json()
        if not isinstance(items, list):
            raise http.SourceError(f"Réponse Semantic Scholar inattendue : {str(items)[:200]}")
        # La réponse est alignée sur la liste d'identifiants envoyée (null si inconnu).
        for (key, _), item in zip(chunk, items):
            metric = parse_s2_paper(item)
            if metric:
                found[key] = metric
    return found


# ---------------------------------------------------------------------- OpenAlex

def openalex_doi(paper: Paper) -> str | None:
    doi = paper.doi or (f"10.48550/arxiv.{paper.arxiv_id}".lower() if paper.arxiv_id else None)
    # Une virgule ou une barre casserait la syntaxe de filtre d'OpenAlex.
    if doi and not any(c in doi for c in ",|"):
        return doi
    return None


def _short_id(openalex_url: str) -> str:
    return openalex_url.rstrip("/").rsplit("/", 1)[-1]


def _openalex_params(**extra) -> dict:
    params = dict(extra)
    if settings.OPENALEX_API_KEY:
        params["api_key"] = settings.OPENALEX_API_KEY
    if settings.CONTACT_EMAIL:
        params["mailto"] = settings.CONTACT_EMAIL
    return params


def fetch_openalex(papers: list[Paper]) -> dict[str, PaperHIndex]:
    by_doi = {d: p.paper_id for p in papers if (d := openalex_doi(p))}
    if not by_doi:
        return {}

    # 1. Articles → auteurs (ordre de signature conservé).
    work_authors: dict[str, list[tuple[str, str]]] = {}
    dois = list(by_doi)
    for start in range(0, len(dois), OPENALEX_FILTER_SIZE):
        chunk = dois[start:start + OPENALEX_FILTER_SIZE]
        payload = http.get(OPENALEX_WORKS_URL, source="OpenAlex", throttle=OPENALEX_THROTTLE, params=_openalex_params(
            filter="doi:" + "|".join(chunk), select="doi,authorships", per_page=100,
        )).json()
        for work in payload.get("results", []):
            doi = normalize_doi(work.get("doi"))
            if doi in by_doi:
                work_authors[by_doi[doi]] = [
                    (_short_id(a["author"]["id"]), a["author"].get("display_name") or "?")
                    for a in work.get("authorships") or []
                    if (a.get("author") or {}).get("id")
                ]

    # 2. Auteurs → h-index.
    author_ids = sorted({aid for authors in work_authors.values() for aid, _ in authors})
    h_by_author: dict[str, int | None] = {}
    for start in range(0, len(author_ids), OPENALEX_FILTER_SIZE):
        chunk = author_ids[start:start + OPENALEX_FILTER_SIZE]
        payload = http.get(OPENALEX_AUTHORS_URL, source="OpenAlex", throttle=OPENALEX_THROTTLE, params=_openalex_params(
            filter="openalex:" + "|".join(chunk), select="id,summary_stats", per_page=100,
        )).json()
        for author in payload.get("results", []):
            h_by_author[_short_id(author["id"])] = (author.get("summary_stats") or {}).get("h_index")

    found: dict[str, PaperHIndex] = {}
    for key, authors in work_authors.items():
        metric = PaperHIndex([AuthorH(name, h_by_author.get(aid)) for aid, name in authors], "openalex")
        if metric.known:
            found[key] = metric
    return found


# ---------------------------------------------------------------------- orchestration

def enrich(papers: list[Paper], cache: JsonCache | None = None) -> EnrichResult:
    """h-index pour chaque article : cache, puis Semantic Scholar, puis OpenAlex en repli."""
    started = time.perf_counter()
    result = EnrichResult(metrics={})
    pending = {p.paper_id: p for p in papers}

    if cache is not None:
        for key, value in cache.get_many(CACHE_NAMESPACE, list(pending)).items():
            result.metrics[key] = None if value.get("missing") else PaperHIndex.from_dict(value)
            pending.pop(key, None)
        result.from_cache = len(result.metrics)

    fetched: dict[str, PaperHIndex] = {}
    for name, fetch in (("semantic_scholar", fetch_semantic_scholar), ("openalex", fetch_openalex)):
        if not pending:
            break
        try:
            found = fetch(list(pending.values()))
        except Exception as exc:          # quota, réseau… l'autre source peut prendre le relais
            result.errors[name] = str(exc)[:300] or exc.__class__.__name__
            continue
        result.by_source[name] = len(found)
        for key, metric in found.items():
            result.metrics[key] = fetched[key] = metric
            pending.pop(key, None)

    for key in pending:
        result.metrics[key] = None

    if cache is not None:
        cache.set_many(CACHE_NAMESPACE, {k: v.to_dict() for k, v in fetched.items()}, TTL_FOUND)
        # On ne mémorise « introuvable » que si les deux sources ont bien répondu.
        if not result.errors:
            cache.set_many(CACHE_NAMESPACE, {k: {"missing": True} for k in pending}, TTL_MISSING)

    result.seconds = time.perf_counter() - started
    return result
