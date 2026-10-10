"""Requête de recherche commune à toutes les sources.

Syntaxe du sujet saisi par l'utilisateur :
- les virgules séparent des concepts qui doivent TOUS être présents (ET) ;
- le caractère « | » sépare des synonymes au sein d'un concept (OU) ;
- chaque terme est recherché comme expression exacte dans le titre ou l'abstract.

Chaque source traduit ensuite ces concepts dans sa propre syntaxe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def _clean_term(term: str) -> str:
    """Retire les caractères qui casseraient la syntaxe de requête des sources."""
    term = re.sub(r'["()\[\]:+|]', " ", term)
    term = re.sub(r"(^|\s)-+", " ", term)        # un « - » en début de mot = négation
    return re.sub(r"\s+", " ", term).strip()


def parse_topic(topic: str) -> list[list[str]]:
    """Découpe le sujet en concepts (ET), chacun composé de synonymes (OU)."""
    concepts = []
    for raw_concept in topic.split(","):
        synonyms = [_clean_term(s) for s in raw_concept.split("|")]
        synonyms = [s for s in synonyms if s]
        if synonyms:
            concepts.append(synonyms)
    return concepts


@dataclass(frozen=True)
class SearchRequest:
    topic: str
    date_from: datetime
    date_to: datetime
    max_results: int = 30                   # par source
    arxiv_categories: tuple[str, ...] = ()

    @property
    def concepts(self) -> list[list[str]]:
        concepts = parse_topic(self.topic)
        if not concepts:
            raise ValueError("Le sujet est vide.")
        return concepts

    @classmethod
    def last_days(
        cls,
        topic: str,
        days: int = 30,
        max_results: int = 30,
        arxiv_categories: tuple[str, ...] = (),
        now: datetime | None = None,
    ) -> "SearchRequest":
        now = now or datetime.now(timezone.utc)
        date_from = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
        return cls(topic, date_from, now, max_results, tuple(arxiv_categories))


def boolean_query(
    concepts: list[list[str]],
    term_fmt=lambda t: f'"{t}"',
    and_op: str = " AND ",
    or_op: str = " OR ",
) -> str:
    """Construit '(a OR b) AND (c)' avec les opérateurs de la source."""
    clauses = []
    for synonyms in concepts:
        terms = or_op.join(term_fmt(t) for t in synonyms)
        clauses.append(f"({terms})" if len(synonyms) > 1 else terms)
    return and_op.join(clauses)
