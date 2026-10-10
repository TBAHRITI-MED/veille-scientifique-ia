"""Connecteurs vers les sources d'articles."""

from sources.arxiv_client import ArxivSource
from sources.openalex_client import OpenAlexSource
from sources.pubmed_client import PubMedSource
from sources.semantic_scholar_client import SemanticScholarSource

ALL_SOURCES = {
    s.name: s for s in (ArxivSource(), OpenAlexSource(), SemanticScholarSource(), PubMedSource())
}
