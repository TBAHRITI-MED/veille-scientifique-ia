"""Configuration lue depuis l'environnement ou un fichier .env (voir .env.example)."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv est optionnel
    load_dotenv = None

ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"

if load_dotenv is not None:
    load_dotenv(ROOT_DIR / ".env")


def env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


# Toutes les clés sont optionnelles : elles augmentent seulement les quotas.
OPENALEX_API_KEY = env("OPENALEX_API_KEY")
SEMANTIC_SCHOLAR_API_KEY = env("SEMANTIC_SCHOLAR_API_KEY")
NCBI_API_KEY = env("NCBI_API_KEY")          # PubMed
CONTACT_EMAIL = env("CONTACT_EMAIL")         # recommandé par OpenAlex et NCBI

USER_AGENT = "veille-scientifique/0.2 (outil personnel de veille" + (
    f"; mailto:{CONTACT_EMAIL})" if CONTACT_EMAIL else ")"
)

# Résumés et score de pertinence (LLM). Sans clé, l'application fonctionne sans cette analyse.
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
LLM_MODEL = env("LLM_MODEL") or "claude-haiku-5-5"
LLM_MAX_PAPERS = int(env("LLM_MAX_PAPERS") or 40)       # articles analysés par recherche (coût)
LLM_CONCURRENCY = int(env("LLM_CONCURRENCY") or 5)

# Profil de recherche : guide le résumé et l'interprétation du sujet. Modifiable depuis Réglages.
DEFAULT_PROFILE = env("RESEARCH_PROFILE") or (
    "Étudiant en Master IA et apprenti ingénieur IA. Centres d'intérêt : federated learning "
    "(agrégation, hétérogénéité des données, confidentialité), imagerie médicale (radiographie "
    "thoracique, IRM, scanner, segmentation, classification), grands modèles de langage "
    "(fine-tuning efficace, LoRA, évaluation)."
)
PROFILE_FILE = DATA_DIR / "profil.txt"

# Accès protégé par mot de passe (recommandé dès que l'application est en ligne).
APP_PASSWORD = env("APP_PASSWORD")

CACHE_FILE = DATA_DIR / "cache.db"     # h-index et analyses LLM (SQLite)
SJR_FILE = DATA_DIR / "sjr.csv"
CORE_FILE = DATA_DIR / "core.csv"
