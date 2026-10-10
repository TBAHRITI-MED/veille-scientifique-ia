"""Source PubMed — NCBI E-utilities (esearch puis efetch).

Indispensable pour l'imagerie médicale : revues cliniques et de radiologie absentes d'arXiv.
Clé optionnelle (NCBI_API_KEY) : 3 requêtes/s sans clé, 10 avec.
La fenêtre de dates porte sur la date d'entrée dans PubMed (« edat ») : c'est ce qui
correspond à « nouveau pour moi » dans une veille.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import settings
from models import JOURNAL, PREPRINT, Paper
from sources import http
from sources.base import SourceResult
from sources.http import SourceError
from sources.query import SearchRequest, boolean_query

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
THROTTLE = http.Throttle(0.11 if settings.NCBI_API_KEY else 0.35)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def build_term(request: SearchRequest) -> str:
    return boolean_query(request.concepts, term_fmt=lambda t: f'"{t}"[tiab]')


def _common_params() -> dict:
    params = {"db": "pubmed", "tool": "veille-scientifique"}
    if settings.NCBI_API_KEY:
        params["api_key"] = settings.NCBI_API_KEY
    if settings.CONTACT_EMAIL:
        params["email"] = settings.CONTACT_EMAIL
    return params


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def _int(value: str | None, default: int = 1) -> int:
    if not value:
        return default
    value = value.strip()
    if value.isdigit():
        return int(value)
    return MONTHS.get(value[:3].lower(), default)


def _date(node: ET.Element | None) -> datetime | None:
    """Lit un nœud <Year>/<Month>/<Day> (ou <MedlineDate> « 2026 Oct-Nov »)."""
    if node is None:
        return None
    year = node.findtext("Year")
    if year and year.strip().isdigit():
        return datetime(int(year), _int(node.findtext("Month")), _int(node.findtext("Day")),
                        tzinfo=timezone.utc)
    medline = (node.findtext("MedlineDate") or "").split()
    if medline and medline[0].isdigit():
        month = _int(medline[1].split("-")[0]) if len(medline) > 1 else 1
        return datetime(int(medline[0]), month, 1, tzinfo=timezone.utc)
    return None


def parse_articles(xml_text: str) -> list[Paper]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceError(f"Réponse PubMed illisible : {exc}") from exc

    papers = []
    for article in root.findall("PubmedArticle"):
        citation = article.find("MedlineCitation")
        art = citation.find("Article") if citation is not None else None
        if art is None:
            continue
        pmid = citation.findtext("PMID")
        journal = art.find("Journal")

        published = (
            _date(art.find("ArticleDate"))
            or _date(journal.find("JournalIssue/PubDate") if journal is not None else None)
            or _date(article.find("PubmedData/History/PubMedPubDate[@PubStatus='entrez']"))
        )
        if published is None:
            continue

        abstract_parts = []
        for part in art.findall("Abstract/AbstractText"):
            label, text = part.get("Label"), _text(part)
            abstract_parts.append(f"{label.capitalize()} : {text}" if label else text)

        authors = []
        for author in art.findall("AuthorList/Author"):
            name = " ".join(filter(None, [author.findtext("ForeName"), author.findtext("LastName")]))
            authors.append(name or _text(author.find("CollectiveName")))

        issn = [i.text for i in (journal.findall("ISSN") if journal is not None else []) if i.text]
        linking = citation.findtext("MedlineJournalInfo/ISSNLinking")
        if linking:
            issn.append(linking)

        ids = {a.get("IdType"): (a.text or "").strip()
               for a in article.findall("PubmedData/ArticleIdList/ArticleId")}
        pub_types = {_text(t).lower() for t in art.findall("PublicationTypeList/PublicationType")}
        abbreviation = journal.findtext("ISOAbbreviation") if journal is not None else None

        papers.append(Paper(
            title=_text(art.find("ArticleTitle")),
            abstract="\n".join(abstract_parts),
            authors=[a for a in authors if a],
            published=published,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            source="pubmed",
            pdf_url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/{ids['pmc']}/" if ids.get("pmc") else None,
            doi=ids.get("doi"),
            pmid=pmid,
            venue=_text(journal.find("Title")) if journal is not None else None,
            venue_type=PREPRINT if "preprint" in pub_types else JOURNAL,
            venue_aliases=[abbreviation] if abbreviation else [],
            issn=issn,
        ))
    return papers


class PubMedSource:
    name = "pubmed"

    def search(self, request: SearchRequest) -> SourceResult:
        term = build_term(request)
        started = time.perf_counter()
        search = http.get(f"{EUTILS}/esearch.fcgi", source="PubMed", throttle=THROTTLE, params={
            **_common_params(),
            "term": term,
            "datetype": "edat",
            "mindate": f"{request.date_from:%Y/%m/%d}",
            "maxdate": f"{request.date_to:%Y/%m/%d}",
            "retmax": request.max_results,
            "retmode": "json",
        })
        try:
            result = search.json()["esearchresult"]
        except (ValueError, KeyError) as exc:
            raise SourceError(f"Réponse PubMed (esearch) illisible : {exc}") from exc
        if "ERROR" in result:
            raise SourceError(f"PubMed : {result['ERROR']}")

        ids = result.get("idlist") or []
        papers: list[Paper] = []
        if ids:
            fetch = http.get(f"{EUTILS}/efetch.fcgi", source="PubMed", throttle=THROTTLE, params={
                **_common_params(), "id": ",".join(ids), "retmode": "xml",
            })
            papers = parse_articles(fetch.text)
        total = int(result.get("count", 0) or 0)
        return SourceResult(self.name, papers, total, term, time.perf_counter() - started)
