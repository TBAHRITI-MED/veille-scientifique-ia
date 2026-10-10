"""API HTTP de l'application de veille (FastAPI).

Réutilise tel quel le cœur Python : sources, fusion des doublons, classements, export.
En production, sert aussi le frontend compilé (frontend/dist) à la racine.

Lancement : python -m api   (ou : uvicorn api.main:app --reload)
"""

from __future__ import annotations

import base64
import re
import secrets
import threading
import time
import uuid
from collections import Counter, OrderedDict

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import settings
from aggregator import AggregatedResult, search_all
from enrichment import hindex as hindex_module
from enrichment.cache import JsonCache
from export import to_csv, to_markdown
from llm import analyzer
from models import SOURCE_LABELS, Paper
from quality import update_rankings
from quality.rankings import ALL_LEVELS, LEVEL_ORDER, Rankings
from sources import ALL_SOURCES
from sources.query import SearchRequest

app = FastAPI(title="Veille scientifique IA", version="1.0.0")

CACHE_TTL_SECONDS = 3600
MAX_UPLOAD_BYTES = 30 * 1024 * 1024          # un export SJR complet pèse ~10 Mo
ARXIV_CATEGORY = re.compile(r"^[a-z-]+(\.[A-Za-z-]+)?$")
CACHE_SIZE = 30
FRONTEND_DIST = settings.ROOT_DIR / "frontend" / "dist"

API_KEY_ENV = {
    "openalex": ("OPENALEX_API_KEY", lambda: settings.OPENALEX_API_KEY),
    "semantic_scholar": ("SEMANTIC_SCHOLAR_API_KEY", lambda: settings.SEMANTIC_SCHOLAR_API_KEY),
    "pubmed": ("NCBI_API_KEY", lambda: settings.NCBI_API_KEY),
}
EXAMPLES = [
    "federated learning, medical imaging | medical image | radiology",
    "large language model | LLM, fine-tuning",
    "federated learning, large language model | LLM",
]


# ---------------------------------------------------------------------------
# Protection par mot de passe (APP_PASSWORD), indispensable une fois en ligne :
# sans elle, n'importe qui pourrait consommer les crédits de la clé LLM.
# ---------------------------------------------------------------------------

PUBLIC_PATHS = {"/api/health"}


@app.middleware("http")
async def password_guard(request: Request, call_next):
    password = settings.APP_PASSWORD
    if not password or request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            _, _, given = base64.b64decode(header[6:]).decode("utf-8").partition(":")
        except (ValueError, UnicodeDecodeError):
            given = ""
        if secrets.compare_digest(given.encode(), password.encode()):
            return await call_next(request)
    return JSONResponse(
        {"detail": "Mot de passe requis."}, status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Veille scientifique", charset="UTF-8"'},
    )


# ---------------------------------------------------------------------------
# Classements (rechargés quand un fichier change) et cache des recherches
# ---------------------------------------------------------------------------

_rankings_lock = threading.Lock()
_rankings: tuple[tuple[float, float], Rankings] | None = None


def _mtime(path) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


def get_rankings() -> Rankings:
    global _rankings
    stamp = (_mtime(settings.SJR_FILE), _mtime(settings.CORE_FILE))
    with _rankings_lock:
        if _rankings is None or _rankings[0] != stamp:
            _rankings = (stamp, Rankings.load(settings.SJR_FILE, settings.CORE_FILE))
        return _rankings[1]


class SearchCache:
    """Cache LRU en mémoire : même recherche dans l'heure = pas de nouvel appel aux sources."""

    def __init__(self, ttl: float = CACHE_TTL_SECONDS, size: int = CACHE_SIZE):
        self.ttl, self.size = ttl, size
        self._by_params: OrderedDict[tuple, tuple[float, str]] = OrderedDict()
        self._results: dict[str, tuple[str, AggregatedResult]] = {}
        self._hindex: dict[str, dict[str, dict | None]] = {}
        self._analyses: dict[str, tuple[str, dict]] = {}     # search_id → (contexte, analyses)
        self._lock = threading.Lock()

    def get(self, params: tuple) -> str | None:
        with self._lock:
            entry = self._by_params.get(params)
            if entry and time.monotonic() - entry[0] < self.ttl:
                self._by_params.move_to_end(params)
                return entry[1]
            return None

    def put(self, params: tuple, topic: str, result: AggregatedResult) -> str:
        search_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._by_params[params] = (time.monotonic(), search_id)
            self._results[search_id] = (topic, result)
            while len(self._by_params) > self.size:
                _, (_, old_id) = self._by_params.popitem(last=False)
                self._results.pop(old_id, None)
                self._hindex.pop(old_id, None)
                self._analyses.pop(old_id, None)
        return search_id

    def result(self, search_id: str) -> tuple[str, AggregatedResult] | None:
        with self._lock:
            return self._results.get(search_id)

    def set_hindex(self, search_id: str, metrics: dict[str, dict | None]) -> None:
        with self._lock:
            if search_id in self._results:
                self._hindex[search_id] = metrics

    def hindex(self, search_id: str) -> dict[str, dict | None] | None:
        with self._lock:
            return self._hindex.get(search_id)

    def set_analyses(self, search_id: str, context: str, data: dict) -> None:
        with self._lock:
            if search_id in self._results:
                self._analyses[search_id] = (context, data)

    def analyses(self, search_id: str, context: str | None = None) -> dict | None:
        with self._lock:
            entry = self._analyses.get(search_id)
        if entry is None or (context is not None and entry[0] != context):
            return None
        return entry[1]

    def clear(self) -> None:
        with self._lock:
            self._by_params.clear()
            self._results.clear()
            self._hindex.clear()
            self._analyses.clear()


cache = SearchCache()

_json_caches: dict[str, JsonCache] = {}


def get_json_cache() -> JsonCache:
    """Cache SQLite des h-index et des analyses LLM (data/cache.db), ouvert à la première utilisation."""
    path = str(settings.CACHE_FILE)
    if path not in _json_caches:
        _json_caches[path] = JsonCache(path)
    return _json_caches[path]


# ---------------------------------------------------------------------------
# Sérialisation
# ---------------------------------------------------------------------------

def paper_to_dict(p: Paper) -> dict:
    return {
        "key": p.paper_id,
        "title": p.title,
        "abstract": p.abstract,
        "authors": p.authors,
        "published": f"{p.published:%Y-%m-%d}",
        "url": p.url,
        "pdf_url": p.pdf_url,
        "doi": p.doi,
        "doi_url": p.doi_url,
        "arxiv_id": p.arxiv_id,
        "pmid": p.pmid,
        "venue": p.venue,
        "venue_type": p.venue_type,
        "citation_count": p.citation_count,
        "sources": p.sources,
        "level": p.level,
        "primary_category": p.primary_category,
    }


def result_to_dict(search_id: str, topic: str, result: AggregatedResult, cached: bool) -> dict:
    get_rankings().apply(result.papers)
    return {
        "search_id": search_id,
        "topic": topic,
        "papers": [paper_to_dict(p) for p in result.papers],
        "stats": {
            "raw_count": result.raw_count,
            "unique_count": len(result.papers),
            "duplicates_merged": result.duplicates_merged,
            "seconds": round(result.seconds, 2),
            "cached": cached,
            "overlap": {str(k): v for k, v in sorted(Counter(len(p.sources) for p in result.papers).items())},
        },
        "by_source": {
            name: {
                "label": SOURCE_LABELS[name],
                "count": len(r.papers),
                "total": r.total_results,
                "seconds": round(r.seconds, 2),
                "query": r.query,
            }
            for name, r in result.by_source.items()
        },
        "errors": {name: {"label": SOURCE_LABELS.get(name, name), "message": msg}
                   for name, msg in result.errors.items()},
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class SearchBody(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    days: int = Field(30, ge=1, le=365)
    max_results: int = Field(30, ge=5, le=100)
    sources: list[str] = Field(default_factory=lambda: list(ALL_SOURCES))
    arxiv_categories: list[str] = Field(default_factory=list)


class ExportBody(BaseModel):
    search_id: str
    keys: list[str]
    format: str = Field(pattern="^(csv|markdown)$")


class EnrichBody(BaseModel):
    search_id: str


class AnalysisBody(BaseModel):
    search_id: str
    keys: list[str] = Field(default_factory=list)   # ordre d'affichage : les premiers sont analysés


class ProfileBody(BaseModel):
    text: str = Field(min_length=10, max_length=2000)


class RankingsUpdateBody(BaseModel):
    core_edition: str = update_rankings.DEFAULT_CORE_EDITION


@app.get("/api/meta")
def meta() -> dict:
    return {
        "sources": [
            {
                "name": name,
                "label": SOURCE_LABELS[name],
                "key_env": API_KEY_ENV[name][0] if name in API_KEY_ENV else None,
                "key_configured": bool(API_KEY_ENV[name][1]()) if name in API_KEY_ENV else None,
            }
            for name in ALL_SOURCES
        ],
        "levels": ALL_LEVELS,
        "level_order": LEVEL_ORDER,
        "contact_email_configured": bool(settings.CONTACT_EMAIL),
        "examples": EXAMPLES,
        "llm": {
            "configured": bool(settings.ANTHROPIC_API_KEY),
            "model": settings.LLM_MODEL,
            "max_papers": settings.LLM_MAX_PAPERS,
        },
        "password_protected": bool(settings.APP_PASSWORD),
    }


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/search")
def search(body: SearchBody) -> dict:
    unknown = [s for s in body.sources if s not in ALL_SOURCES]
    if unknown:
        raise HTTPException(422, f"Sources inconnues : {', '.join(unknown)}")
    if not body.sources:
        raise HTTPException(422, "Choisis au moins une source.")
    bad_categories = [c for c in body.arxiv_categories if not ARXIV_CATEGORY.match(c)]
    if bad_categories:
        raise HTTPException(422, f"Catégories arXiv invalides : {', '.join(bad_categories)}")
    topic = body.topic.strip()
    params = (topic, body.days, body.max_results, tuple(sorted(body.arxiv_categories)),
              tuple(sorted(body.sources)))

    search_id = cache.get(params)
    if search_id and (hit := cache.result(search_id)):
        return result_to_dict(search_id, hit[0], hit[1], cached=True)

    try:
        request = SearchRequest.last_days(topic, body.days, body.max_results, tuple(body.arxiv_categories))
        request.concepts  # valide la syntaxe du sujet
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    result = search_all([ALL_SOURCES[name] for name in body.sources], request)
    search_id = cache.put(params, topic, result)
    return result_to_dict(search_id, topic, result, cached=False)


@app.post("/api/export")
def export(body: ExportBody) -> Response:
    hit = cache.result(body.search_id)
    if hit is None:
        raise HTTPException(404, "Recherche expirée : relance-la avant d'exporter.")
    topic, result = hit
    get_rankings().apply(result.papers)
    by_key = {p.paper_id: p for p in result.papers}
    papers = [by_key[k] for k in body.keys if k in by_key]
    hindex = cache.hindex(body.search_id)
    analyses = cache.analyses(body.search_id)
    stamp = time.strftime("%Y%m%d")
    if body.format == "csv":
        return Response(to_csv(papers, hindex, analyses), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="veille_{stamp}.csv"'})
    return Response(to_markdown(papers, topic, hindex=hindex, analyses=analyses).encode("utf-8"),
                    media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="veille_{stamp}.md"'})


@app.post("/api/enrich/hindex")
def enrich_hindex(body: EnrichBody) -> dict:
    """h-index des auteurs de chaque article d'une recherche (Semantic Scholar, puis OpenAlex)."""
    hit = cache.result(body.search_id)
    if hit is None:
        raise HTTPException(404, "Recherche expirée : relance-la pour charger les h-index.")
    stored = cache.hindex(body.search_id)
    if stored is not None:
        return {"metrics": stored, "stats": {"cached": True}}

    _, result = hit
    enriched = hindex_module.enrich(result.papers, get_json_cache())
    metrics = {k: (v.to_dict() if v else None) for k, v in enriched.metrics.items()}
    cache.set_hindex(body.search_id, metrics)
    found = sum(1 for v in metrics.values() if v)
    return {
        "metrics": metrics,
        "stats": {
            "cached": False,
            "found": found,
            "missing": len(metrics) - found,
            "from_cache": enriched.from_cache,
            "by_source": {SOURCE_LABELS.get(k, k): n for k, n in enriched.by_source.items()},
            "errors": {SOURCE_LABELS.get(k, k): msg for k, msg in enriched.errors.items()},
            "seconds": round(enriched.seconds, 2),
        },
    }


@app.post("/api/enrich/analysis")
def enrich_analysis(body: AnalysisBody) -> dict:
    """Résumé en français et score de pertinence (LLM) des articles d'une recherche."""
    hit = cache.result(body.search_id)
    if hit is None:
        raise HTTPException(404, "Recherche expirée : relance-la pour lancer l'analyse.")
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(400, "Analyse désactivée : ajoute ANTHROPIC_API_KEY dans le fichier .env.")

    topic, result = hit
    profile = analyzer.load_profile()
    context = analyzer.context_hash(topic, profile, settings.LLM_MODEL)
    stored = cache.analyses(body.search_id, context)
    if stored is not None:
        return {"analyses": stored, "reasons": {}, "stats": {"cached": True}}

    # Les articles dans l'ordre affiché passent en premier (seuls LLM_MAX_PAPERS sont analysés).
    rank = {k: i for i, k in enumerate(body.keys)}
    papers = sorted(result.papers, key=lambda p: rank.get(p.paper_id, len(rank)))
    try:
        analysis = analyzer.analyze(papers, topic, profile, get_json_cache())
    except analyzer.LLMNotConfigured as exc:
        raise HTTPException(400, str(exc)) from exc

    data = {k: (vars(v) if v else None) for k, v in analysis.analyses.items()}
    if not analysis.errors:
        cache.set_analyses(body.search_id, context, data)
    analyzed = sum(1 for v in data.values() if v)
    return {
        "analyses": data,
        "reasons": analysis.reasons,
        "stats": {
            "cached": False,
            "analyzed": analyzed,
            "from_cache": analysis.from_cache,
            "errors": len(analysis.errors),
            "first_error": next(iter(analysis.errors.values()), None),
            "seconds": round(analysis.seconds, 2),
            "model": analysis.model,
        },
    }


@app.get("/api/profile")
def get_profile() -> dict:
    return {"text": analyzer.load_profile(), "default": settings.DEFAULT_PROFILE}


@app.put("/api/profile")
def put_profile(body: ProfileBody) -> dict:
    return {"text": analyzer.save_profile(body.text), "default": settings.DEFAULT_PROFILE}


@app.get("/api/rankings")
def rankings_status() -> dict:
    r = get_rankings()
    return {
        "journals": r.sjr_journals,
        "conferences": len(r.core_acronyms),
        "sjr_url": update_rankings.SJR_URL,
        "core_url_template": update_rankings.CORE_URL,
        "default_core_edition": update_rankings.DEFAULT_CORE_EDITION,
    }


@app.post("/api/rankings/update")
def rankings_update(body: RankingsUpdateBody) -> dict:
    report = {}
    for kind, action in (("sjr", update_rankings.update_sjr),
                         ("core", lambda: update_rankings.update_core(body.core_edition))):
        try:
            report[kind] = {"ok": True, "count": action()}
        except Exception as exc:
            report[kind] = {"ok": False, "error": str(exc)[:300]}
    return report


@app.post("/api/rankings/upload")
async def rankings_upload(kind: str = Query(pattern="^(sjr|core)$"), file: UploadFile = File(...)) -> dict:
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Fichier trop volumineux (30 Mo maximum).")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    saver = update_rankings.save_sjr if kind == "sjr" else update_rankings.save_core
    try:
        return {"count": saver(text)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/diagnostic")
def diagnostic() -> list[dict]:
    request = SearchRequest.last_days("machine learning", days=7, max_results=3)
    report = []
    for name, source in ALL_SOURCES.items():
        started = time.perf_counter()
        try:
            found = len(source.search(request).papers)
            ok, detail = True, f"{found} article(s) reçu(s)"
        except Exception as exc:
            ok, detail = False, str(exc)[:300]
        report.append({"source": name, "label": SOURCE_LABELS[name], "ok": ok,
                       "seconds": round(time.perf_counter() - started, 2), "detail": detail})
    return report


# ---------------------------------------------------------------------------
# Frontend compilé
# ---------------------------------------------------------------------------

if (FRONTEND_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Route d'API inconnue.")
        candidate = (FRONTEND_DIST / path).resolve()
        if path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
