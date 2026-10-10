"""Lance une campagne d'évaluation : 3 sujets × 10 articles.

- mesure le temps de réponse (1 essai à froid + 2 répétés par sujet) → temps.csv
- exporte les 10 articles les plus récents de chaque sujet, après fusion des
  sources et classement → annotations.csv, à compléter à la main

Usage (depuis la racine du projet) :
    python -m evaluation.run_campaign                      # toutes les sources
    python -m evaluation.run_campaign --sources arxiv      # pour comparer à la campagne 1
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import settings
from aggregator import AggregatedResult, search_all
from evaluation.config import (
    ANNOTATION_COLUMNS, COLD_RUNS, CSV_DELIMITER, CSV_ENCODING, DAYS, N_ARTICLES, SUBJECTS,
)
from llm import analyzer
from quality.rankings import Rankings
from sources import ALL_SOURCES, arxiv_client
from sources.query import SearchRequest

CAMPAIGNS_DIR = Path(__file__).parent / "campagnes"
MAX_PER_SOURCE = 30


def run_pipeline(topic: str, source_names: list[str]) -> AggregatedResult:
    """Le traitement complet mesuré par C5 : collecte multi-sources + fusion.

    L'étape 2 y ajoutera le résumé et le score LLM, pour que le chrono couvre toute la chaîne.
    """
    request = SearchRequest.last_days(topic, DAYS, MAX_PER_SOURCE)
    return search_all([ALL_SOURCES[name] for name in source_names], request)


def _timed(topic: str, source_names: list[str]) -> tuple[float, AggregatedResult]:
    # On attend la fin de l'intervalle imposé par arXiv (le plus long) AVANT de lancer
    # le chrono, pour ne pas compter l'attente de politesse entre deux essais.
    time.sleep(arxiv_client.THROTTLE.min_interval + 0.2)
    started = time.perf_counter()
    result = run_pipeline(topic, source_names)
    return time.perf_counter() - started, result


def main(source_names: list[str] | None = None) -> Path:
    source_names = source_names or list(ALL_SOURCES)
    rankings = Rankings.load(settings.SJR_FILE, settings.CORE_FILE)
    out_dir = CAMPAIGNS_DIR / datetime.now().strftime("%Y-%m-%d_%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)

    timings: list[dict] = []
    annotations: list[dict] = []

    for subject_id, topic in SUBJECTS.items():
        print(f"\n[{subject_id}] {topic}")
        result: AggregatedResult | None = None
        for run in range(1, COLD_RUNS + 1):
            seconds, result = _timed(topic, source_names)
            # Les API mettent en cache les requêtes identiques : seul le premier essai
            # est réellement à froid, les suivants mesurent une requête répétée.
            mode = "froid" if run == 1 else "repete"
            timings.append({
                "sujet_id": subject_id, "mode": mode, "essai": run,
                "secondes": f"{seconds:.2f}", "nb_articles": len(result.papers),
                "erreurs": " | ".join(f"{k}: {v}" for k, v in result.errors.items()),
            })
            errors = f", erreurs : {', '.join(result.errors)}" if result.errors else ""
            print(f"  essai {run} ({mode}) : {seconds:.2f} s, {len(result.papers)} articles{errors}")

        rankings.apply(result.papers)
        top = result.papers[:N_ARTICLES]

        # Résumé et score LLM (critères C2, C3, C4) si une clé est configurée. Sans cache,
        # pour mesurer le comportement réel du prompt actuel.
        analyses = {}
        if settings.ANTHROPIC_API_KEY:
            started = time.perf_counter()
            llm = analyzer.analyze(top, topic, analyzer.load_profile(), cache=None, max_papers=N_ARTICLES)
            analyses = llm.analyses
            timings.append({
                "sujet_id": subject_id, "mode": "llm", "essai": 1,
                "secondes": f"{time.perf_counter() - started:.2f}", "nb_articles": len(top),
                "erreurs": " | ".join(llm.errors.values()),
            })
            print(f"  analyse LLM : {sum(1 for a in analyses.values() if a)} / {len(top)} articles")

        for rank, paper in enumerate(top, start=1):
            row = dict.fromkeys(ANNOTATION_COLUMNS, "")
            row.update({
                "sujet_id": subject_id, "sujet": topic, "rang": rank,
                "identifiant": paper.paper_id,
                "date": f"{paper.published:%Y-%m-%d}",
                "titre": paper.title,
                "support": paper.venue or "",
                "niveau": paper.level or "",
                "sources": paper.sources_label,
                "abstract": paper.abstract,
                "url": paper.url,
            })
            if analyses.get(paper.paper_id):
                row["resume_fr"] = analyses[paper.paper_id].resume_fr
                row["score_llm"] = analyses[paper.paper_id].score
            annotations.append(row)

    with open(out_dir / "annotations.csv", "w", newline="", encoding=CSV_ENCODING) as f:
        writer = csv.DictWriter(f, fieldnames=ANNOTATION_COLUMNS, delimiter=CSV_DELIMITER)
        writer.writeheader()
        writer.writerows(annotations)

    with open(out_dir / "temps.csv", "w", newline="", encoding=CSV_ENCODING) as f:
        writer = csv.DictWriter(
            f, fieldnames=["sujet_id", "mode", "essai", "secondes", "nb_articles", "erreurs"],
            delimiter=CSV_DELIMITER,
        )
        writer.writeheader()
        writer.writerows(timings)

    (out_dir / "campagne.json").write_text(json.dumps({
        "date": datetime.now().isoformat(timespec="seconds"),
        "sujets": SUBJECTS, "jours": DAYS, "articles_par_sujet": N_ARTICLES,
        "sources": source_names,
        "classements": {"revues_sjr": rankings.sjr_journals, "conferences_core": len(rankings.core_acronyms)},
        "pipeline": "collecte multi-sources + fusion + niveau de publication"
                    + (f" + analyse LLM ({settings.LLM_MODEL})" if settings.ANTHROPIC_API_KEY else ""),
        "prompt_version": analyzer.PROMPT_VERSION,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    cold = [float(t["secondes"]) for t in timings if t["mode"] == "froid"]
    print(f"\nMédiane à froid : {statistics.median(cold):.2f} s")
    print(f"Campagne enregistrée dans : {out_dir}")
    print("Prochaine étape : remplir la colonne pertinence_humaine d'annotations.csv, puis")
    print(f"    python -m evaluation.score {out_dir}")
    return out_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lance une campagne d'évaluation.")
    parser.add_argument("--sources", nargs="+", choices=list(ALL_SOURCES), default=list(ALL_SOURCES))
    main(parser.parse_args().sources)
