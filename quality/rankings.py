"""Niveau de la publication : quartile SJR pour les revues, rang CORE pour les conférences.

Les deux classements sont des fichiers CSV locaux dans data/ :
- data/sjr.csv  : export SCImago Journal Rank (séparateur « ; »)
- data/core.csv : export du portail CORE (sans ligne d'en-tête)
Voir quality/update_rankings.py pour les télécharger.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from models import CONFERENCE, JOURNAL, PREPRINT, Paper, normalize_issn, normalize_title

QUARTILES = ["Q1", "Q2", "Q3", "Q4"]
CORE_RANKS = ["A*", "A", "B", "C"]
PREPRINT_LEVEL = "Préprint"
UNRANKED_LEVEL = "Non classé"
ALL_LEVELS = QUARTILES + CORE_RANKS + [PREPRINT_LEVEL, UNRANKED_LEVEL]

# Pour trier par niveau : Q1 et A* en tête, préprints en dernier.
LEVEL_ORDER = {"Q1": 0, "A*": 0, "Q2": 1, "A": 1, "Q3": 2, "B": 2, "Q4": 3, "C": 3,
               UNRANKED_LEVEL: 4, PREPRINT_LEVEL: 5}

MIN_ACRONYM_LENGTH = 3


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


@dataclass
class Rankings:
    sjr: dict[str, str] = field(default_factory=dict)          # ISSN → quartile
    sjr_journals: int = 0                                        # revues classées (≠ nb d'ISSN)
    core_acronyms: dict[str, str] = field(default_factory=dict)  # ACRONYME → rang
    core_titles: dict[str, str] = field(default_factory=dict)    # titre normalisé → rang

    # ------------------------------------------------------------------ chargement

    @classmethod
    def load(cls, sjr_path: Path | None, core_path: Path | None) -> "Rankings":
        rankings = cls()
        if sjr_path and sjr_path.exists():
            rankings.sjr, rankings.sjr_journals = parse_sjr(_read_text(sjr_path))
        if core_path and core_path.exists():
            rankings.core_acronyms, rankings.core_titles = parse_core(_read_text(core_path))
        return rankings

    @property
    def is_empty(self) -> bool:
        return not self.sjr and not self.core_acronyms

    # ------------------------------------------------------------------ classement

    def quartile(self, paper: Paper) -> str | None:
        for issn in paper.issn:
            quartile = self.sjr.get(issn)
            if quartile:
                return quartile
        return None

    def core_rank(self, paper: Paper) -> str | None:
        names = [n for n in [paper.venue, *paper.venue_aliases] if n]
        normalized = [normalize_title(n) for n in names]
        # 1. Titre exact, puis titre CORE contenu dans le nom du support
        #    (« Advances in Neural Information Processing Systems » ⊃ « Neural Information … »).
        for name in normalized:
            if name in self.core_titles:
                return self.core_titles[name]
        for name in normalized:
            for title, rank in self.core_titles.items():
                if len(title.split()) >= 4 and title in name:
                    return rank
        # 2. Acronyme seul (« MICCAI ») ou dans le nom (« MICCAI 2026 », « Proc. NeurIPS »).
        #    On exige ≥ 2 majuscules pour ne pas confondre un acronyme avec un mot courant.
        for name in names:
            for token in re.findall(r"[A-Za-z][A-Za-z0-9*]+", name):
                rank = self.core_acronyms.get(token.upper())
                looks_like_acronym = sum(c.isupper() for c in token) >= 2
                if rank and (looks_like_acronym or name.strip().upper() == token.upper()):
                    return rank
        return None

    def classify(self, paper: Paper) -> str:
        if paper.venue_type == PREPRINT:
            return PREPRINT_LEVEL
        if paper.venue_type == JOURNAL:
            return self.quartile(paper) or UNRANKED_LEVEL
        if paper.venue_type == CONFERENCE:
            return self.core_rank(paper) or self.quartile(paper) or UNRANKED_LEVEL
        return self.quartile(paper) or self.core_rank(paper) or UNRANKED_LEVEL

    def apply(self, papers: list[Paper]) -> None:
        for paper in papers:
            paper.level = self.classify(paper)


# ---------------------------------------------------------------------- parsing


def parse_sjr(text: str) -> tuple[dict[str, str], int]:
    """Export SCImago : colonnes « Issn » ('15424863, 00079235') et « SJR Best Quartile ».

    Renvoie (ISSN → quartile, nombre de revues classées).
    """
    delimiter = ";" if text.count(";") > text.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    columns = {c.strip().lower(): c for c in reader.fieldnames or []}
    issn_col = columns.get("issn")
    quartile_col = columns.get("sjr best quartile") or columns.get("quartile")
    if not issn_col or not quartile_col:
        raise ValueError("Fichier SJR invalide : colonnes « Issn » et « SJR Best Quartile » introuvables.")

    mapping: dict[str, str] = {}
    journals = 0
    for row in reader:
        quartile = (row.get(quartile_col) or "").strip().upper()
        if quartile not in QUARTILES:
            continue
        journals += 1
        for issn in (row.get(issn_col) or "").split(","):
            issn = normalize_issn(issn)
            if len(issn) == 8:
                mapping.setdefault(issn, quartile)
    return mapping, journals


def parse_core(text: str) -> tuple[dict[str, str], dict[str, str]]:
    """Export CORE : id, titre, acronyme, édition (CORE2023…), rang, … — sans en-tête.

    Le rang est repéré par sa valeur (A*, A, B, C) pour résister aux variations de colonnes.
    """
    acronyms: dict[str, str] = {}
    titles: dict[str, str] = {}
    for row in csv.reader(io.StringIO(text)):
        cells = [c.strip() for c in row]
        if len(cells) < 4 or cells[1].lower() == "title":
            continue
        rank = next((c for c in cells[3:] if c in CORE_RANKS), None)
        if not rank:
            continue
        title, acronym = cells[1], cells[2]
        if title:
            titles.setdefault(normalize_title(title), rank)
        if len(acronym) >= MIN_ACRONYM_LENGTH:
            acronyms.setdefault(acronym.upper(), rank)
    return acronyms, titles
