import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { api, type Paper, type SearchResult } from "../api";
import { type AnalysisMap, type Filters, type HIndexMap, plural } from "../lib/papers";
import type { AnalysisStatus } from "./FilterRail";
import { DayStrip } from "./DayStrip";
import { PaperRow } from "./PaperRow";
import { Button, Notice } from "./ui";

const PAGE = 25;

interface Props {
  result: SearchResult;
  visible: Paper[];
  days: number;
  filters: Filters;
  onFilters: (f: Filters) => void;
  sourceLabels: Record<string, string>;
  hindex: HIndexMap | null;
  analyses: AnalysisMap | null;
  reasons: Record<string, string>;
  aStatus: AnalysisStatus;
  rankingsMissing: boolean;
  onOpenSettings: () => void;
}

export function ResultsView({
  result,
  visible,
  days,
  filters,
  onFilters,
  sourceLabels,
  hindex,
  analyses,
  reasons,
  aStatus,
  rankingsMissing,
  onOpenSettings,
}: Props) {
  const [shown, setShown] = useState(PAGE);
  const [exportError, setExportError] = useState<string | null>(null);
  useEffect(() => setShown(PAGE), [result.search_id, filters]);

  const { stats } = result;
  const errors = Object.values(result.errors);
  const askedSources = Object.keys(result.by_source).length + errors.length;

  const download = async (format: "csv" | "markdown") => {
    setExportError(null);
    try {
      await api.export(result.search_id, visible.map((p) => p.key), format);
    } catch (e) {
      setExportError((e as Error).message);
    }
  };

  return (
    <div className="results-arrive space-y-6">
      <p className="text-[0.95rem] leading-relaxed text-ink-muted">
        <span className="font-semibold text-ink">{plural(stats.unique_count, "article", "articles")}</span> pour{" "}
        <span className="text-ink">« {result.topic} »</span>, issus de {askedSources - errors.length} source
        {askedSources - errors.length > 1 ? "s" : ""} sur {askedSources}.{" "}
        {stats.duplicates_merged > 0 && `${plural(stats.duplicates_merged, "doublon fusionné", "doublons fusionnés")}. `}
        {stats.cached ? "Résultat en cache." : `Réponse en ${stats.seconds.toLocaleString("fr-FR")} s.`}
      </p>

      {errors.map((e) => (
        <Notice key={e.label}>
          <strong>{e.label}</strong> n'a pas répondu : {e.message}. Les autres sources sont affichées.
        </Notice>
      ))}
      {rankingsMissing && (
        <Notice tone="info">
          Les classements SJR et CORE ne sont pas chargés : les revues et conférences apparaissent « Non classé ».{" "}
          <button type="button" onClick={onOpenSettings} className="font-medium text-accent hover:underline">
            Charger les classements
          </button>
        </Notice>
      )}

      {result.papers.length > 0 && (
        <DayStrip papers={result.papers} days={days} selected={filters.day} onSelect={(day) => onFilters({ ...filters, day })} />
      )}

      <div className="flex flex-wrap items-center gap-3 border-b border-rule pb-3">
        <input
          value={filters.text}
          onChange={(e) => onFilters({ ...filters, text: e.target.value })}
          placeholder="Filtrer par mot, ex. segmentation"
          aria-label="Filtrer les articles affichés"
          className="min-w-48 flex-1 rounded-md border border-rule bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none"
        />
        <span className="text-sm tabular-nums text-ink-muted">
          {visible.length === result.papers.length
            ? plural(visible.length, "article", "articles")
            : `${visible.length} sur ${result.papers.length}`}
        </span>
        <Button onClick={() => download("csv")} disabled={!visible.length}>
          <Download className="size-3.5" aria-hidden /> CSV
        </Button>
        <Button onClick={() => download("markdown")} disabled={!visible.length}>
          <Download className="size-3.5" aria-hidden /> Markdown
        </Button>
      </div>
      {exportError && <Notice>{exportError}</Notice>}

      {visible.length === 0 ? (
        <div className="space-y-2 py-10 text-center">
          <p className="font-serif text-lg text-ink">Aucun article ne correspond à ces filtres.</p>
          <p className="text-sm text-ink-muted">
            {result.papers.length
              ? "Élargis les niveaux ou les sources cochés, ou efface le filtre par mot."
              : "Ajoute des synonymes avec « | », retire un concept, ou allonge la période."}
          </p>
        </div>
      ) : (
        <div>
          {visible.slice(0, shown).map((p) => (
            <PaperRow
              key={p.key}
              paper={p}
              sourceLabels={sourceLabels}
              metric={hindex ? (hindex[p.key] ?? null) : undefined}
              basis={filters.hBasis}
              analysis={analyses ? (analyses[p.key] ?? null) : undefined}
              analysisPending={aStatus.state === "loading"}
              notAnalyzedReason={reasons[p.key]}
            />
          ))}
          {visible.length > shown && (
            <div className="pt-5 text-center">
              <Button onClick={() => setShown(shown + PAGE)}>
                Afficher {Math.min(PAGE, visible.length - shown)} articles de plus
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function LoadingRows({ sources }: { sources: number }) {
  return (
    <div className="space-y-6" aria-busy="true" aria-live="polite">
      <p className="text-sm text-ink-muted">Interrogation de {sources} source{sources > 1 ? "s" : ""} en parallèle…</p>
      {Array.from({ length: 5 }, (_, i) => (
        <div key={i} className="flex gap-4 border-b border-rule pb-5">
          <div className="skeleton w-1.5 self-stretch" />
          <div className="flex-1 space-y-2.5">
            <div className="skeleton h-5" style={{ width: `${82 - i * 7}%` }} />
            <div className="skeleton h-3.5 w-1/2" />
            <div className="skeleton h-3.5 w-1/3" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function Welcome({ examples, onExample }: { examples: string[]; onExample: (t: string) => void }) {
  return (
    <div className="max-w-[62ch] space-y-8 py-6">
      <div className="space-y-3">
        <h2 className="font-serif text-[1.7rem] leading-tight font-semibold text-ink">
          Ce qui a paru ce mois-ci sur tes sujets, en une liste.
        </h2>
        <p className="leading-relaxed text-ink-muted">
          Une recherche interroge arXiv, OpenAlex, Semantic Scholar et PubMed en même temps, fusionne les doublons et indique
          pour chaque article le niveau de la revue ou de la conférence.
        </p>
      </div>
      <div className="space-y-2.5">
        <p className="text-sm font-semibold text-ink">Essayer avec</p>
        <ul className="space-y-1.5">
          {examples.map((ex) => (
            <li key={ex}>
              <button type="button" onClick={() => onExample(ex)} className="text-left text-accent hover:underline underline-offset-3">
                {ex}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-3 text-sm text-ink-muted">
        {[
          ["spine-1", "Q1 ou A*"],
          ["spine-3", "Q3 ou B"],
          ["spine-preprint", "Préprint"],
          ["spine-unranked", "Non classé"],
        ].map(([cls, label]) => (
          <span key={label} className="flex items-center gap-2">
            <span className={`spine h-5 ${cls}`} aria-hidden /> {label}
          </span>
        ))}
      </div>
    </div>
  );
}
