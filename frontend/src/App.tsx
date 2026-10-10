import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { api, type Meta, type RankingsStatus, type SearchOptions, type SearchResult } from "./api";
import { type AnalysisStatus, FilterRail, type HStatus } from "./components/FilterRail";
import { LoadingRows, ResultsView, Welcome } from "./components/ResultsView";
import { SearchPanel } from "./components/SearchPanel";
import { SettingsView } from "./components/SettingsView";
import { StatsView } from "./components/StatsView";
import { Notice } from "./components/ui";
import {
  type AnalysisMap,
  emptyFilters,
  type Filters,
  filterPapers,
  type HIndexMap,
  orderLevels,
  type SortKey,
  sortPapers,
} from "./lib/papers";
import { load, save } from "./lib/storage";

type View = "articles" | "stats" | "settings";
type Theme = "light" | "dark" | null;

const VIEWS: { id: View; label: string }[] = [
  { id: "articles", label: "Articles" },
  { id: "stats", label: "Statistiques" },
  { id: "settings", label: "Réglages" },
];
const HISTORY_SIZE = 8;

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [rankings, setRankings] = useState<RankingsStatus | null>(null);

  const [topic, setTopic] = useState("");
  const [options, setOptions] = useState<SearchOptions>(() =>
    load("options", { sources: ["arxiv", "openalex", "semantic_scholar", "pubmed"], days: 30, maxResults: 30, categories: [] }),
  );
  const [result, setResult] = useState<SearchResult | null>(null);
  const [searchedDays, setSearchedDays] = useState(30);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [hindex, setHindex] = useState<HIndexMap | null>(null);
  const [hStatus, setHStatus] = useState<HStatus>({ state: "idle" });
  const [analyses, setAnalyses] = useState<AnalysisMap | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [aStatus, setAStatus] = useState<AnalysisStatus>({ state: "idle" });
  const latestSearch = useRef<string | null>(null);
  const searchCounter = useRef(0);
  const [sort, setSort] = useState<SortKey>(() => load("sort", "recent"));
  const [view, setView] = useState<View>("articles");
  const [history, setHistory] = useState<string[]>(() => load("history", []));
  const [theme, setTheme] = useState<Theme>(() => load("theme", null));
  const inputRef = useRef<HTMLInputElement>(null);

  // --- chargement initial
  const refreshRankings = useCallback(() => {
    api.rankings().then(setRankings).catch(() => setRankings(null));
  }, []);
  useEffect(() => {
    api
      .meta()
      .then((m) => {
        setMeta(m);
        // Options mémorisées par une ancienne version : on ne garde que les sources connues.
        const known = new Set(m.sources.map((s) => s.name));
        setOptions((o) => {
          const sources = o.sources.filter((s) => known.has(s));
          return { ...o, sources: sources.length ? sources : [...known] };
        });
      })
      .catch((e: Error) => setMetaError(e.message));
    refreshRankings();
  }, [refreshRankings]);

  // --- préférences
  useEffect(() => save("options", options), [options]);
  useEffect(() => save("sort", sort), [sort]);
  useEffect(() => {
    save("theme", theme);
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
  }, [theme]);

  // --- « / » place le curseur dans la recherche
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // h-index des auteurs : chargé en arrière-plan, la liste s'affiche sans l'attendre.
  const loadHIndex = (searchId: string) => {
    latestSearch.current = searchId;
    setHindex(null);
    setHStatus({ state: "loading" });
    api
      .enrichHIndex(searchId)
      .then((res) => {
        if (latestSearch.current !== searchId) return; // une recherche plus récente a pris le relais
        setHindex(res.metrics);
        const errors = Object.entries(res.stats.errors ?? {});
        const found = Object.values(res.metrics).some(Boolean);
        setHStatus(
          !found && errors.length
            ? { state: "error", message: errors.map(([s, m]) => `${s} : ${m}`).join(" ; ") }
            : { state: "done" },
        );
      })
      .catch((e: Error) => {
        if (latestSearch.current === searchId) setHStatus({ state: "error", message: e.message });
      });
  };

  // Résumés et score par LLM : en arrière-plan aussi, sur les articles dans l'ordre affiché.
  const loadAnalysis = (searchId: string, keys: string[], llmConfigured: boolean) => {
    setAnalyses(null);
    setReasons({});
    if (!llmConfigured) {
      setAStatus({ state: "disabled" });
      return;
    }
    setAStatus({ state: "loading" });
    api
      .enrichAnalysis(searchId, keys)
      .then((res) => {
        if (latestSearch.current !== searchId) return;
        setAnalyses(res.analyses);
        setReasons(res.reasons);
        const analyzed = Object.values(res.analyses).filter(Boolean).length;
        setAStatus(
          analyzed === 0 && res.stats.first_error
            ? { state: "error", message: res.stats.first_error }
            : { state: "done", errors: res.stats.errors ?? 0 },
        );
      })
      .catch((e: Error) => {
        if (latestSearch.current === searchId) setAStatus({ state: "error", message: e.message });
      });
  };

  const runSearch = async (query = topic) => {
    const q = query.trim();
    if (!q) return;
    if (!options.sources.length) {
      setError("Active au moins une source sous la barre de recherche.");
      return;
    }
    setTopic(q);
    setLoading(true);
    setError(null);
    setView("articles");
    const ticket = ++searchCounter.current; // seule la dernière recherche lancée s'affiche
    try {
      const data = await api.search(q, options);
      if (ticket !== searchCounter.current) return;
      setResult(data);
      setSearchedDays(options.days);
      setFilters((f) => ({ ...emptyFilters(), hBasis: f.hBasis }));
      loadHIndex(data.search_id);
      if (meta) {
        const order = sortPapers(data.papers, sort === "score" ? "recent" : sort, meta.level_order).map((p) => p.key);
        loadAnalysis(data.search_id, order, meta.llm.configured);
      }
      const next = [q, ...history.filter((h) => h !== q)].slice(0, HISTORY_SIZE);
      setHistory(next);
      save("history", next);
    } catch (e) {
      if (ticket === searchCounter.current) setError((e as Error).message);
    } finally {
      if (ticket === searchCounter.current) setLoading(false);
    }
  };

  const visible = useMemo(
    () =>
      result && meta
        ? sortPapers(filterPapers(result.papers, filters, { hindex, analyses }), sort, meta.level_order, {
            hindex,
            analyses,
            basis: filters.hBasis,
          })
        : [],
    [result, meta, filters, sort, hindex, analyses],
  );
  const sourceLabels = useMemo(
    () => Object.fromEntries((meta?.sources ?? []).map((s) => [s.name, s.label])),
    [meta],
  );
  const levels = useMemo(() => (meta ? orderLevels(meta.levels, meta.level_order) : []), [meta]);
  const isDark =
    theme === "dark" || (theme === null && typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches);

  const rail = meta && (
    <FilterRail
      papers={result?.papers ?? []}
      levels={levels}
      sources={meta.sources}
      filters={filters}
      onFilters={setFilters}
      sort={sort}
      onSort={setSort}
      history={history}
      onHistory={(t) => runSearch(t)}
      hindex={hindex}
      hStatus={hStatus}
      analyses={analyses}
      aStatus={aStatus}
    />
  );

  if (metaError) {
    return (
      <main className="mx-auto max-w-xl px-5 py-24">
        <Notice>{metaError}</Notice>
      </main>
    );
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-rule">
        <div className="mx-auto flex max-w-[1180px] items-center gap-2 px-5 py-3 sm:gap-6">
          <a href="/" className="flex items-center gap-2.5" aria-label="Veille scientifique, accueil">
            <span className="flex h-6 items-stretch gap-[3px]" aria-hidden>
              <span className="spine spine-1" />
              <span className="spine spine-3" />
              <span className="spine spine-preprint" />
            </span>
            <span className="hidden font-serif text-lg font-semibold text-ink sm:inline">Veille</span>
          </a>
          <nav className="ml-auto flex items-center gap-1" aria-label="Vues">
            {VIEWS.map((v) => (
              <button
                key={v.id}
                type="button"
                onClick={() => setView(v.id)}
                aria-current={view === v.id ? "page" : undefined}
                className={`rounded-md px-2.5 py-1.5 text-sm sm:px-3 ${
                  view === v.id ? "bg-accent-soft font-semibold text-ink" : "text-ink-muted hover:text-ink"
                }`}
              >
                {v.label}
              </button>
            ))}
          </nav>
          <button
            type="button"
            onClick={() => setTheme(isDark ? "light" : "dark")}
            className="rounded-md p-2 text-ink-muted hover:text-ink"
            aria-label={isDark ? "Passer en thème clair" : "Passer en thème sombre"}
          >
            {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </button>
        </div>
      </header>

      <div className="border-b border-rule bg-surface/60">
        <div className="mx-auto max-w-[1180px] px-5 py-5">
          {meta && (
            <SearchPanel
              ref={inputRef}
              topic={topic}
              onTopic={setTopic}
              options={options}
              onOptions={setOptions}
              sources={meta.sources}
              loading={loading}
              onSubmit={() => runSearch()}
            />
          )}
        </div>
      </div>

      <main className="mx-auto max-w-[1180px] px-5 py-8">
        {error && (
          <div className="mb-6">
            <Notice>{error}</Notice>
          </div>
        )}

        {view === "settings" && meta ? (
          <SettingsView meta={meta} rankings={rankings} onRankingsChanged={refreshRankings} />
        ) : view === "stats" ? (
          result && meta ? (
            <StatsView result={result} levels={levels} hindex={hindex} hBasis={filters.hBasis} analyses={analyses} />
          ) : (
            <p className="py-10 text-ink-muted">Les statistiques apparaissent après une recherche.</p>
          )
        ) : (
          <div className="grid gap-10 lg:grid-cols-[220px_minmax(0,1fr)]">
            {meta && (
              <>
                <details className="rounded-lg border border-rule bg-surface px-4 py-3 lg:hidden">
                  <summary className="cursor-pointer text-sm font-semibold text-ink">Filtres, tri et historique</summary>
                  <div className="pt-4">{rail}</div>
                </details>
                <div className="hidden lg:sticky lg:top-6 lg:block lg:self-start">{rail}</div>
              </>
            )}
            <div className="min-w-0 max-w-[820px]">
              {loading ? (
                <LoadingRows sources={options.sources.length} />
              ) : result ? (
                <ResultsView
                  result={result}
                  visible={visible}
                  days={searchedDays}
                  filters={filters}
                  onFilters={setFilters}
                  sourceLabels={sourceLabels}
                  hindex={hindex}
                  analyses={analyses}
                  reasons={reasons}
                  aStatus={aStatus}
                  rankingsMissing={rankings !== null && rankings.journals === 0 && rankings.conferences === 0}
                  onOpenSettings={() => setView("settings")}
                />
              ) : (
                meta && <Welcome examples={meta.examples} onExample={(t) => runSearch(t)} />
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
