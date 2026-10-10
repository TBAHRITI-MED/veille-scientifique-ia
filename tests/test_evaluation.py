import csv
from datetime import datetime, timezone

import pytest

from aggregator import AggregatedResult
from evaluation import run_campaign
from evaluation.config import ANNOTATION_COLUMNS, CSV_DELIMITER, CSV_ENCODING, SUBJECTS
from evaluation.grading import (
    CriterionResult, global_note, grade_c1, grade_c2, grade_c3, grade_c4, grade_c5,
    note_from_thresholds, to_number,
)
from evaluation.score import build_report
from models import Paper


def test_to_number():
    assert to_number("4,5") == 4.5
    assert to_number(" 3 ") == 3.0
    assert to_number("") is None
    assert to_number("abc") is None


@pytest.mark.parametrize("value,expected", [(0.95, 5), (0.90, 5), (0.80, 4), (0.60, 3), (0.45, 2), (0.1, 1)])
def test_thresholds_higher_is_better(value, expected):
    assert note_from_thresholds(value, [0.90, 0.75, 0.60, 0.40]) == expected


@pytest.mark.parametrize("value,expected", [(8, 5), (10, 5), (15, 4), (45, 2), (90, 1)])
def test_thresholds_lower_is_better(value, expected):
    assert note_from_thresholds(value, [10, 20, 30, 60], higher_is_better=False) == expected


def test_c1_weighted_precision_per_subject():
    rows = (
        [{"sujet_id": "S1", "pertinence_humaine": s} for s in ["5", "4", "3", "2"]]   # (2 + 0,5) / 4
        + [{"sujet_id": "S2", "pertinence_humaine": s} for s in ["5", "5"]]           # 1
    )
    result = grade_c1(rows)
    assert result.value == "0,81"          # moyenne de 0,625 et 1
    assert result.note == 4


def test_c1_empty():
    assert grade_c1([{"sujet_id": "S1", "pertinence_humaine": ""}]).note is None


def test_c2_hallucination_caps_note():
    rows = [{"fidelite": "2"}] * 19 + [{"fidelite": "0"}]   # taux 0,95 mais 1 hallucination
    result = grade_c2(rows)
    assert result.value == "0,95"
    assert result.note == 2


def test_c2_no_hallucination():
    assert grade_c2([{"fidelite": "2"}] * 10).note == 5


def test_c3_rounding_and_languagetool_penalty():
    rows = [{"note_francais": n} for n in ["5", "4", "4"]]   # moyenne 4,33 → 4,5
    assert grade_c3(rows).note == 4.5
    assert grade_c3(rows, lt_errors_per_100_words=3.0).note == 3.5


def test_c4_mae():
    rows = [
        {"pertinence_humaine": "5", "score_llm": "4"},
        {"pertinence_humaine": "3", "score_llm": "3"},
        {"pertinence_humaine": "2", "score_llm": "5"},
        {"pertinence_humaine": "4", "score_llm": ""},   # ignorée
    ]
    result = grade_c4(rows)
    assert result.value == "1,33"
    assert result.note == 2
    assert "67% à ±1" in result.detail


def test_c5_median_cold_only():
    timings = [{"mode": "froid", "secondes": s} for s in ["2.0", "3.0", "40.0"]] + [
        {"mode": "repete", "secondes": "0.1"},
        {"mode": "chaud", "secondes": "0.05"},
    ]
    result = grade_c5(timings)
    assert result.value == "3,00"
    assert result.note == 5
    assert "requête répétée : 0,10 s" in result.detail


def test_campaign_marks_only_first_run_as_cold(tmp_path, monkeypatch):
    monkeypatch.setattr(run_campaign, "CAMPAIGNS_DIR", tmp_path)
    monkeypatch.setattr(run_campaign, "run_pipeline",
                        lambda topic, sources: AggregatedResult(papers=[], errors={"pubmed": "quota"}))
    monkeypatch.setattr(run_campaign.time, "sleep", lambda s: None)
    out_dir = run_campaign.main()
    with open(out_dir / "temps.csv", encoding=CSV_ENCODING) as f:
        rows = list(csv.DictReader(f, delimiter=CSV_DELIMITER))
    assert [r["mode"] for r in rows] == ["froid", "repete", "repete"] * len(SUBJECTS)
    assert rows[0]["erreurs"] == "pubmed: quota"          # erreurs de source tracées


def test_global_note_partial_renormalised():
    results = [
        CriterionResult("C1", "", "", 4),
        CriterionResult("C2", "", "", 3),
        CriterionResult("C4", "", None, None),
        CriterionResult("C5", "", "", 5),
    ]
    note, partial = global_note(results)
    assert partial
    assert note == pytest.approx((0.25 * 4 + 0.30 * 3 + 0.10 * 5) / 0.65)


def test_global_note_not_significant_below_half_weight():
    results = [CriterionResult("C5", "", "", 5), CriterionResult("C1", "", "", 4)]  # 35 %
    note, partial = global_note(results)
    assert note is None and partial


def test_campaign_end_to_end(tmp_path, monkeypatch):
    """Campagne simulée → CSV → annotation → rapport."""
    papers = [
        Paper(title=f"T{i}", abstract="A", authors=["X"], arxiv_id=f"2610.0000{i}",
              published=datetime(2026, 10, 1, tzinfo=timezone.utc),
              url=f"https://arxiv.org/abs/2610.0000{i}", source="arxiv", venue_type="preprint")
        for i in range(12)
    ]
    monkeypatch.setattr(run_campaign, "CAMPAIGNS_DIR", tmp_path)
    monkeypatch.setattr(run_campaign, "run_pipeline",
                        lambda topic, sources: AggregatedResult(papers=list(papers)))
    monkeypatch.setattr(run_campaign.time, "sleep", lambda s: None)

    out_dir = run_campaign.main()

    with open(out_dir / "annotations.csv", encoding=CSV_ENCODING) as f:
        rows = list(csv.DictReader(f, delimiter=CSV_DELIMITER))
    assert len(rows) == 10 * len(SUBJECTS)                 # tronqué à 10 par sujet
    assert list(rows[0]) == ANNOTATION_COLUMNS
    assert rows[0]["identifiant"] == "arXiv:2610.00000" and rows[0]["niveau"] == "Préprint"

    for row in rows:                                        # annotation simulée
        row["pertinence_humaine"] = "4"
    with open(out_dir / "annotations.csv", "w", newline="", encoding=CSV_ENCODING) as f:
        writer = csv.DictWriter(f, fieldnames=ANNOTATION_COLUMNS, delimiter=CSV_DELIMITER)
        writer.writeheader()
        writer.writerows(rows)

    report, results = build_report(out_dir)
    notes = {r.code: r.note for r in results}
    assert notes["C1"] == 5 and notes["C5"] == 5
    assert notes["C2"] is None and notes["C4"] is None
    assert "non significative" in report and "35%" in report
