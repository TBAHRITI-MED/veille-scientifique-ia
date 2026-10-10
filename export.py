"""Export des résultats en CSV (Excel FR) et en Markdown (notes, blog)."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from models import Paper

CSV_COLUMNS = [
    "titre", "auteurs", "date", "support", "niveau", "sources", "citations",
    "score_pertinence", "resume_fr", "justification_score",
    "h_index_max", "auteur_h_index_max", "h_index_dernier_auteur",
    "doi", "arxiv", "pmid", "url", "abstract",
]


def _h(hindex: dict | None, paper: Paper, field: str):
    metric = (hindex or {}).get(paper.paper_id)
    value = metric.get(field) if metric else None
    return "" if value is None else value


def _a(analyses: dict | None, paper: Paper, field: str):
    analysis = (analyses or {}).get(paper.paper_id)
    value = analysis.get(field) if analysis else None
    return "" if value is None else value


def to_rows(
    papers: list[Paper],
    hindex: dict[str, dict | None] | None = None,
    analyses: dict[str, dict | None] | None = None,
) -> list[dict]:
    return [
        {
            "titre": p.title,
            "auteurs": ", ".join(p.authors),
            "date": f"{p.published:%Y-%m-%d}",
            "support": p.venue or "",
            "niveau": p.level or "",
            "sources": p.sources_label,
            "citations": "" if p.citation_count is None else p.citation_count,
            "score_pertinence": _a(analyses, p, "score"),
            "resume_fr": _a(analyses, p, "resume_fr"),
            "justification_score": _a(analyses, p, "justification"),
            "h_index_max": _h(hindex, p, "h_max"),
            "auteur_h_index_max": _h(hindex, p, "h_max_author"),
            "h_index_dernier_auteur": _h(hindex, p, "h_last"),
            "doi": p.doi or "",
            "arxiv": p.arxiv_id or "",
            "pmid": p.pmid or "",
            "url": p.url,
            "abstract": p.abstract,
        }
        for p in papers
    ]


def to_csv(
    papers: list[Paper],
    hindex: dict[str, dict | None] | None = None,
    analyses: dict[str, dict | None] | None = None,
) -> bytes:
    """CSV « ; » encodé utf-8-sig : s'ouvre directement dans Excel en français."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, delimiter=";")
    writer.writeheader()
    writer.writerows(to_rows(papers, hindex, analyses))
    return buffer.getvalue().encode("utf-8-sig")


def to_markdown(
    papers: list[Paper], topic: str, generated: datetime | None = None,
    hindex: dict[str, dict | None] | None = None,
    analyses: dict[str, dict | None] | None = None,
) -> str:
    generated = generated or datetime.now()
    lines = [
        f"# Veille : {topic}",
        "",
        f"*{len(papers)} article(s) — généré le {generated:%d/%m/%Y à %H:%M}*",
        "",
    ]
    for p in papers:
        meta = [f"{p.published:%d/%m/%Y}"]
        if p.venue:
            meta.append(p.venue + (f" ({p.level})" if p.level else ""))
        if p.citation_count:
            meta.append(f"{p.citation_count} citation(s)")
        if _a(analyses, p, "score") != "":
            meta.append(f"pertinence {_a(analyses, p, 'score')}/5")
        if _h(hindex, p, "h_max") != "":
            meta.append(f"h-index max {_h(hindex, p, 'h_max')} ({_h(hindex, p, 'h_max_author')})")
        lines += [
            f"## [{p.title}]({p.url})",
            "",
            f"**{p.authors_short or 'Auteurs inconnus'}** — " + " · ".join(meta),
            "",
        ]
        if _a(analyses, p, "resume_fr"):
            lines += [_a(analyses, p, "resume_fr"), ""]
        if p.abstract:
            lines += ["> " + p.abstract.replace("\n", "\n> "), ""]
    return "\n".join(lines)
