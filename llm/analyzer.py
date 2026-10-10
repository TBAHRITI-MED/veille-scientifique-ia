"""Résumé en français + score de pertinence de chaque article, par un LLM (API Claude).

Un appel par article, en parallèle (LLM_CONCURRENCY), avec cache SQLite : un article déjà
analysé pour le même sujet, le même profil, le même modèle et la même version de prompt
n'est jamais renvoyé au LLM.
"""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

import settings
from enrichment.cache import JsonCache
from llm.prompts import ANALYSIS_TOOL, PROMPT_VERSION, SYSTEM_PROMPT, user_message

__all__ = ["PROMPT_VERSION", "Analysis", "AnalysisResult", "LLMNotConfigured", "analyze", "load_profile",
           "save_profile", "context_hash"]
from models import Paper

CACHE_NAMESPACE = "llm"
CACHE_TTL = 30 * 24 * 3600
MAX_OUTPUT_TOKENS = 600


class LLMNotConfigured(RuntimeError):
    """Aucune clé ANTHROPIC_API_KEY : l'analyse est désactivée."""


@dataclass
class Analysis:
    resume_fr: str
    score: int
    justification: str


@dataclass
class AnalysisResult:
    analyses: dict[str, Analysis | None]       # clé d'article → analyse (None = non analysé)
    reasons: dict[str, str] = field(default_factory=dict)   # pourquoi un article n'est pas analysé
    from_cache: int = 0
    errors: dict[str, str] = field(default_factory=dict)    # clé d'article → erreur
    seconds: float = 0.0
    model: str = ""


def make_client():
    if not settings.ANTHROPIC_API_KEY:
        raise LLMNotConfigured(
            "Ajoute ANTHROPIC_API_KEY dans le fichier .env pour activer les résumés et le score."
        )
    import anthropic  # importé ici : l'application tourne aussi sans le SDK ni la clé

    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=3, timeout=60)


def context_hash(topic: str, profile: str, model: str) -> str:
    raw = "\x1f".join([PROMPT_VERSION, model, topic.strip().lower(), profile.strip()])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def parse_response(response) -> Analysis:
    """Extrait l'appel d'outil de la réponse et valide les champs."""
    block = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
    if block is None:
        raise ValueError("le modèle n'a pas renvoyé d'analyse structurée")
    data = block.input
    summary = str(data.get("resume_fr", "")).strip()
    if not summary:
        raise ValueError("résumé vide")
    try:
        score = int(data.get("score"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"score invalide : {data.get('score')!r}") from exc
    return Analysis(summary, min(5, max(1, score)), str(data.get("justification", "")).strip())


def analyze_one(client, paper: Paper, topic: str, profile: str, model: str) -> Analysis:
    response = client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": ANALYSIS_TOOL["name"]},
        messages=[{"role": "user", "content": user_message(profile, topic, paper.title, paper.abstract)}],
    )
    return parse_response(response)


def analyze(
    papers: list[Paper],
    topic: str,
    profile: str,
    cache: JsonCache | None = None,
    client=None,
    model: str | None = None,
    max_papers: int | None = None,
    concurrency: int | None = None,
) -> AnalysisResult:
    """Analyse les `max_papers` premiers articles (dans l'ordre reçu) qui ont un abstract."""
    started = time.perf_counter()
    model = model or settings.LLM_MODEL
    max_papers = settings.LLM_MAX_PAPERS if max_papers is None else max_papers
    result = AnalysisResult(analyses={p.paper_id: None for p in papers}, model=model)

    candidates: list[Paper] = []
    for paper in papers:
        if not paper.abstract.strip():
            result.reasons[paper.paper_id] = "Pas d'abstract à résumer"
        elif len(candidates) >= max_papers:
            result.reasons[paper.paper_id] = f"Au-delà des {max_papers} articles analysés par recherche"
        else:
            candidates.append(paper)

    ctx = context_hash(topic, profile, model)
    key_of = {p.paper_id: f"{p.paper_id}|{ctx}" for p in candidates}
    if cache is not None and candidates:
        cached = cache.get_many(CACHE_NAMESPACE, list(key_of.values()))
        for paper in list(candidates):
            hit = cached.get(key_of[paper.paper_id])
            if hit:
                result.analyses[paper.paper_id] = Analysis(**hit)
                result.from_cache += 1
                candidates.remove(paper)

    if candidates:
        client = client or make_client()

        def run(paper: Paper):
            try:
                return paper, analyze_one(client, paper, topic, profile, model), None
            except Exception as exc:          # un article en échec n'arrête pas les autres
                return paper, None, str(exc)[:300] or exc.__class__.__name__

        with ThreadPoolExecutor(max_workers=concurrency or settings.LLM_CONCURRENCY) as pool:
            outcomes = list(pool.map(run, candidates))

        fresh = {}
        for paper, analysis, error in outcomes:
            if analysis:
                result.analyses[paper.paper_id] = analysis
                fresh[key_of[paper.paper_id]] = asdict(analysis)
            else:
                result.errors[paper.paper_id] = error
                result.reasons[paper.paper_id] = f"Erreur du LLM : {error}"
        if cache is not None and fresh:
            cache.set_many(CACHE_NAMESPACE, fresh, CACHE_TTL)

    result.seconds = time.perf_counter() - started
    return result


def load_profile() -> str:
    try:
        text = settings.PROFILE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    return text or settings.DEFAULT_PROFILE


def save_profile(text: str) -> str:
    settings.PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    settings.PROFILE_FILE.write_text(text.strip(), encoding="utf-8")
    return load_profile()
