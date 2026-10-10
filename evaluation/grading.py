"""Calcul des métriques et conversion en notes /5, selon la grille d'évaluation.

Chaque fonction `grade_cX` renvoie un `CriterionResult` ; `value` et `note` valent
None quand les annotations nécessaires ne sont pas encore remplies.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass

from evaluation.config import CRITERIA_NAMES, WEIGHTS


@dataclass
class CriterionResult:
    code: str
    metric: str                 # description de la métrique chiffrée
    value: str | None           # valeur affichable
    note: float | None          # note /5
    detail: str = ""            # précisions (par sujet, hallucinations…)

    @property
    def name(self) -> str:
        return CRITERIA_NAMES[self.code]


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------

def to_number(value) -> float | None:
    """'4', '4,5', 4.5 → float ; '', None → None."""
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def note_from_thresholds(value: float, thresholds: list[float], higher_is_better: bool = True) -> int:
    """Convertit une métrique en note 5→2 selon 4 seuils, 1 sinon.

    thresholds = [seuil pour 5, pour 4, pour 3, pour 2].
    """
    for note, threshold in zip((5, 4, 3, 2), thresholds):
        if (value >= threshold) if higher_is_better else (value <= threshold):
            return note
    return 1


def _fmt(x: float, digits: int = 2) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


# ---------------------------------------------------------------------------
# Critères
# ---------------------------------------------------------------------------

def grade_c1(rows: list[dict]) -> CriterionResult:
    """P@10 pondérée : pertinent (≥ 4) = 1, connexe (3) = 0,5, hors sujet (≤ 2) = 0."""
    metric = "P@10 pondérée, moyenne des sujets"
    by_subject: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        score = to_number(row.get("pertinence_humaine"))
        if score is not None:
            by_subject[row["sujet_id"]].append(score)
    if not by_subject:
        return CriterionResult("C1", metric, None, None, "pertinence_humaine non remplie")

    precisions = {}
    for subject, scores in sorted(by_subject.items()):
        gain = sum(1.0 if s >= 4 else 0.5 if s == 3 else 0.0 for s in scores)
        precisions[subject] = gain / len(scores)
    value = statistics.mean(precisions.values())
    detail = " · ".join(
        f"{s} : {_fmt(p)} ({len(by_subject[s])} art.)" for s, p in precisions.items()
    )
    note = note_from_thresholds(value, [0.90, 0.75, 0.60, 0.40])
    return CriterionResult("C1", metric, _fmt(value), note, detail)


def grade_c2(rows: list[dict]) -> CriterionResult:
    """Taux de fidélité = somme des notes 0/1/2 / (2 × n). Plafonné à 2/5 si hallucination."""
    metric = "Taux de fidélité + nb d'hallucinations"
    scores = [s for s in (to_number(r.get("fidelite")) for r in rows) if s is not None]
    if not scores:
        return CriterionResult("C2", metric, None, None, "fidelite non remplie (étape 2)")

    rate = sum(scores) / (2 * len(scores))
    hallucinations = sum(1 for s in scores if s == 0)
    note = note_from_thresholds(rate, [0.95, 0.85, 0.70, 0.50])
    detail = f"{hallucinations} hallucination(s) sur {len(scores)} résumés"
    if hallucinations:
        note = min(note, 2)
        detail += " → note plafonnée à 2"
    return CriterionResult("C2", metric, _fmt(rate), note, detail)


def grade_c3(rows: list[dict], lt_errors_per_100_words: float | None = None) -> CriterionResult:
    """Moyenne des notes de français, arrondie au 0,5 ; −1 si LanguageTool > 2 erreurs / 100 mots."""
    metric = "Note moyenne /5 (+ LanguageTool)"
    scores = [s for s in (to_number(r.get("note_francais")) for r in rows) if s is not None]
    if not scores:
        return CriterionResult("C3", metric, None, None, "note_francais non remplie (étape 2)")

    mean = statistics.mean(scores)
    note = round(mean * 2) / 2
    detail = f"{len(scores)} résumés notés"
    if lt_errors_per_100_words is not None:
        detail += f" · LanguageTool : {_fmt(lt_errors_per_100_words)} erreurs / 100 mots"
        if lt_errors_per_100_words > 2:
            note = max(1.0, note - 1)
            detail += " → −1 point"
    return CriterionResult("C3", metric, _fmt(mean), note, detail)


def grade_c4(rows: list[dict]) -> CriterionResult:
    """Erreur absolue moyenne entre score LLM et note humaine (même rubrique 1-5)."""
    metric = "MAE score LLM / note humaine"
    pairs = []
    for row in rows:
        human, llm = to_number(row.get("pertinence_humaine")), to_number(row.get("score_llm"))
        if human is not None and llm is not None:
            pairs.append((human, llm))
    if not pairs:
        return CriterionResult("C4", metric, None, None, "score_llm absent (étape 2)")

    errors = [abs(h - l) for h, l in pairs]
    mae = statistics.mean(errors)
    within_one = sum(1 for e in errors if e <= 1) / len(errors)
    note = note_from_thresholds(mae, [0.5, 0.75, 1.0, 1.5], higher_is_better=False)
    detail = f"{len(pairs)} paires · {within_one:.0%} à ±1 point"
    return CriterionResult("C4", metric, _fmt(mae), note, detail)


def grade_c5(timings: list[dict]) -> CriterionResult:
    """Médiane des temps à froid (s), tous sujets confondus."""
    metric = "Médiane à froid (s), 1er essai par sujet"
    cold = [to_number(t["secondes"]) for t in timings if t.get("mode") == "froid"]
    cold = [c for c in cold if c is not None]
    if not cold:
        return CriterionResult("C5", metric, None, None, "aucun temps mesuré")

    median = statistics.median(cold)
    note = note_from_thresholds(median, [10, 20, 30, 60], higher_is_better=False)
    detail = f"{len(cold)} essais à froid, max {_fmt(max(cold), 2)} s"
    for mode, label in (("repete", "requête répétée"), ("chaud", "à chaud")):
        values = [to_number(t["secondes"]) for t in timings if t.get("mode") == mode]
        values = [v for v in values if v is not None]
        if values:
            detail += f" · {label} : {_fmt(statistics.median(values), 2)} s"
    return CriterionResult("C5", metric, _fmt(median, 2), note, detail)


# ---------------------------------------------------------------------------
# Note globale
# ---------------------------------------------------------------------------

MIN_WEIGHT_COVERAGE = 0.5


def weight_coverage(results: list[CriterionResult]) -> float:
    """Part du poids total couverte par les critères effectivement notés."""
    return sum(WEIGHTS[r.code] for r in results if r.note is not None)


def global_note(results: list[CriterionResult]) -> tuple[float | None, bool]:
    """Moyenne pondérée des critères notés. Renvoie (note, partielle ?).

    Si des critères manquent, les poids des critères disponibles sont renormalisés
    et la note est signalée comme partielle. En dessous de 50 % du poids total
    couvert, la note n'est pas calculée : elle refléterait un seul critère mineur.
    """
    graded = [r for r in results if r.note is not None]
    total_weight = weight_coverage(results)
    if not graded or total_weight < MIN_WEIGHT_COVERAGE:
        return None, True
    note = sum(WEIGHTS[r.code] * r.note for r in graded) / total_weight
    return note, len(graded) < len(WEIGHTS)
