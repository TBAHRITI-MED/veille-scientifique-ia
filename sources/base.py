"""Interface commune des sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from models import Paper
from sources.query import SearchRequest


@dataclass
class SourceResult:
    source: str
    papers: list[Paper]
    total_results: int | None   # correspondances annoncées par la source (si connu)
    query: str                  # requête réellement envoyée, pour le débogage
    seconds: float = 0.0


class Source(Protocol):
    name: str                   # clé interne (voir models.SOURCE_LABELS)

    def search(self, request: SearchRequest) -> SourceResult: ...
