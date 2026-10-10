"""Calcule les notes d'une campagne et écrit rapport.md.

Usage :
    python -m evaluation.score evaluation/campagnes/<dossier>
    python -m evaluation.score evaluation/campagnes/<dossier> --languagetool
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from evaluation.config import CSV_DELIMITER, CSV_ENCODING, WEIGHTS
from evaluation.grading import (
    MIN_WEIGHT_COVERAGE, CriterionResult, global_note, grade_c1, grade_c2, grade_c3,
    grade_c4, grade_c5, weight_coverage,
)


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding=CSV_ENCODING) as f:
        return list(csv.DictReader(f, delimiter=CSV_DELIMITER))


def languagetool_errors_per_100_words(summaries: list[str]) -> float | None:
    """Erreurs LanguageTool pour 100 mots (optionnel : pip install language-tool-python, Java requis)."""
    texts = [s for s in summaries if s.strip()]
    if not texts:
        return None
    try:
        import language_tool_python
    except ImportError:
        print("language-tool-python non installé : contrôle automatique ignoré.")
        return None
    with language_tool_python.LanguageTool("fr") as tool:
        errors = sum(len(tool.check(t)) for t in texts)
    words = sum(len(t.split()) for t in texts)
    return 100 * errors / words


def build_report(campaign_dir: Path, use_languagetool: bool = False) -> tuple[str, list[CriterionResult]]:
    rows = _read_csv(campaign_dir / "annotations.csv")
    timings = _read_csv(campaign_dir / "temps.csv")

    lt = None
    if use_languagetool:
        lt = languagetool_errors_per_100_words([r.get("resume_fr", "") for r in rows])

    results = [grade_c1(rows), grade_c2(rows), grade_c3(rows, lt), grade_c4(rows), grade_c5(timings)]
    note, partial = global_note(results)

    lines = [
        f"# Rapport d'évaluation — {campaign_dir.name}",
        "",
        "| Critère | Poids | Métrique | Valeur | Note /5 | Détail |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r.code} {r.name} | {WEIGHTS[r.code]:.0%} | {r.metric} | "
            f"{r.value or '—'} | {'—' if r.note is None else f'{r.note:g}'} | {r.detail} |"
        )
    lines.append("")
    if note is None:
        lines.append(
            f"**Note globale N : non significative** — les critères notés ne couvrent que "
            f"{weight_coverage(results):.0%} du poids total (minimum {MIN_WEIGHT_COVERAGE:.0%})."
        )
    else:
        suffix = " — partielle, poids renormalisés sur les critères disponibles" if partial else ""
        lines.append(f"**Note globale N : {note:.2f} / 5**{suffix}".replace(".", ",", 1))
    return "\n".join(lines) + "\n", results


def main() -> None:
    parser = argparse.ArgumentParser(description="Calcule les notes d'une campagne d'évaluation.")
    parser.add_argument("campaign_dir", type=Path)
    parser.add_argument("--languagetool", action="store_true",
                        help="ajoute le contrôle automatique du français (C3)")
    args = parser.parse_args()

    report, _ = build_report(args.campaign_dir, args.languagetool)
    (args.campaign_dir / "rapport.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
