"""Paramètres figés de la campagne d'évaluation (voir la grille d'évaluation)."""

SUBJECTS = {
    "S1": "federated learning, medical imaging | radiology",   # ciblé, cœur du domaine
    "S2": "large language model | LLM, fine-tuning",            # large, gros volume
    "S3": "federated learning, large language model | LLM",    # croisé, niche
}

DAYS = 30
N_ARTICLES = 10
COLD_RUNS = 3

# Pondération de la note globale N.
WEIGHTS = {"C1": 0.25, "C2": 0.30, "C3": 0.15, "C4": 0.20, "C5": 0.10}

CRITERIA_NAMES = {
    "C1": "Pertinence de la collecte",
    "C2": "Fidélité des résumés",
    "C3": "Qualité du français",
    "C4": "Fiabilité du score",
    "C5": "Temps de réponse",
}

# Colonnes du fichier d'annotation. Les 5 dernières sont remplies à la main
# (ou par l'app à partir de l'étape 2 pour score_llm et resume_fr).
ANNOTATION_COLUMNS = [
    "sujet_id", "sujet", "rang", "identifiant", "date", "titre", "support", "niveau", "sources",
    "abstract", "url",
    "resume_fr", "score_llm",
    "pertinence_humaine", "fidelite", "note_francais", "commentaire",
]

CSV_DELIMITER = ";"          # ouvre directement dans Excel en français
CSV_ENCODING = "utf-8-sig"
