"""Modèles de données partagés par toute l'application."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

# Types de support de publication, normalisés entre les sources.
JOURNAL, CONFERENCE, PREPRINT, OTHER = "journal", "conference", "preprint", "other"

SOURCE_LABELS = {
    "arxiv": "arXiv",
    "openalex": "OpenAlex",
    "semantic_scholar": "Semantic Scholar",
    "pubmed": "PubMed",
}


def normalize_doi(doi: str | None) -> str | None:
    """'https://doi.org/10.1/ABC' → '10.1/abc'."""
    if not doi:
        return None
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi.strip(), flags=re.I)
    return doi.lower() or None


def arxiv_id_from_doi(doi: str | None) -> str | None:
    """Les DOI arXiv (10.48550/arXiv.2410.01234) portent l'identifiant arXiv."""
    match = re.match(r"10\.48550/arxiv\.(.+)$", doi or "", flags=re.I)
    return match.group(1) if match else None


def normalize_issn(issn: str) -> str:
    """'1542-4863' ou '15424863' → '15424863'."""
    return re.sub(r"[^0-9Xx]", "", issn).upper()


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", title.lower())).strip()


@dataclass
class Paper:
    """Un article scientifique, quelle que soit sa source."""

    title: str
    abstract: str
    authors: list[str]
    published: datetime                     # date de publication (UTC)
    url: str                                # page de l'article
    source: str                             # source qui l'a fourni (clé de SOURCE_LABELS)
    pdf_url: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    pmid: str | None = None
    venue: str | None = None                # revue ou conférence
    venue_type: str = OTHER                 # JOURNAL, CONFERENCE, PREPRINT ou OTHER
    venue_aliases: list[str] = field(default_factory=list)   # acronymes, autres noms
    issn: list[str] = field(default_factory=list)
    citation_count: int | None = None
    primary_category: str | None = None
    categories: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)          # toutes les sources après fusion
    level: str | None = None                # niveau calculé : Q1…Q4, A*…C, Préprint, Non classé

    def __post_init__(self) -> None:
        self.doi = normalize_doi(self.doi)
        if not self.arxiv_id:
            self.arxiv_id = arxiv_id_from_doi(self.doi)
        self.issn = [normalize_issn(i) for i in self.issn if i]
        if not self.sources:
            self.sources = [self.source]

    @property
    def paper_id(self) -> str:
        """Identifiant lisible et stable, du plus au moins spécifique."""
        if self.arxiv_id:
            return f"arXiv:{self.arxiv_id}"
        if self.doi:
            return f"doi:{self.doi}"
        if self.pmid:
            return f"PMID:{self.pmid}"
        return f"titre:{normalize_title(self.title)[:60]}"

    @property
    def doi_url(self) -> str | None:
        return f"https://doi.org/{self.doi}" if self.doi else None

    @property
    def authors_short(self) -> str:
        """Auteurs tronqués pour l'affichage : 'A, B, C et al.'."""
        if len(self.authors) <= 3:
            return ", ".join(self.authors)
        return ", ".join(self.authors[:3]) + " et al."

    @property
    def sources_label(self) -> str:
        return ", ".join(SOURCE_LABELS.get(s, s) for s in self.sources)
