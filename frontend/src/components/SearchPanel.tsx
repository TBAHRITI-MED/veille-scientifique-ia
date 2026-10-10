import { forwardRef, useState } from "react";
import { Search } from "lucide-react";
import type { SearchOptions, SourceMeta } from "../api";
import { Button } from "./ui";

export const ARXIV_CATEGORIES: Record<string, string> = {
  "cs.LG": "Machine Learning",
  "cs.CV": "Computer Vision",
  "cs.CL": "NLP",
  "cs.AI": "Artificial Intelligence",
  "eess.IV": "Image and Video Processing",
  "cs.CR": "Cryptography and Security",
  "cs.DC": "Distributed Computing",
  "stat.ML": "Statistics, Machine Learning",
};

const PERIODS = [7, 14, 30, 60, 90];
const PER_SOURCE = [10, 20, 30, 50, 100];

interface Props {
  topic: string;
  onTopic: (t: string) => void;
  options: SearchOptions;
  onOptions: (o: SearchOptions) => void;
  sources: SourceMeta[];
  loading: boolean;
  onSubmit: () => void;
}

export const SearchPanel = forwardRef<HTMLInputElement, Props>(function SearchPanel(
  { topic, onTopic, options, onOptions, sources, loading, onSubmit },
  inputRef,
) {
  const [showSyntax, setShowSyntax] = useState(false);
  const toggleSource = (name: string) =>
    onOptions({
      ...options,
      sources: options.sources.includes(name) ? options.sources.filter((s) => s !== name) : [...options.sources, name],
    });
  const toggleCategory = (cat: string) =>
    onOptions({
      ...options,
      categories: options.categories.includes(cat)
        ? options.categories.filter((c) => c !== cat)
        : [...options.categories, cat],
    });

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <div className="flex gap-2">
        <label className="relative flex-1">
          <span className="sr-only">Sujet de veille</span>
          <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4.5 -translate-y-1/2 text-ink-muted" aria-hidden />
          <input
            ref={inputRef}
            value={topic}
            onChange={(e) => onTopic(e.target.value)}
            placeholder="federated learning, medical imaging | radiology"
            className="w-full rounded-lg border border-rule bg-surface py-3 pr-10 pl-10 text-[1.05rem] text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="absolute top-1/2 right-3 hidden -translate-y-1/2 rounded border border-rule px-1.5 text-xs text-ink-muted sm:block">
            /
          </kbd>
        </label>
        <Button type="submit" variant="primary" className="px-5 text-[0.95rem]" disabled={loading || !topic.trim()}>
          {loading ? "Recherche…" : "Rechercher"}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
        <fieldset className="flex flex-wrap items-center gap-1.5">
          <legend className="sr-only">Sources</legend>
          {sources.map((s) => {
            const on = options.sources.includes(s.name);
            return (
              <button
                key={s.name}
                type="button"
                aria-pressed={on}
                onClick={() => toggleSource(s.name)}
                className={`rounded-full border px-3 py-1 transition-colors ${
                  on ? "border-accent bg-accent-soft text-ink" : "border-rule text-ink-muted hover:text-ink"
                }`}
              >
                {s.label}
              </button>
            );
          })}
        </fieldset>

        <label className="flex items-center gap-2 text-ink-muted">
          Période
          <select
            value={options.days}
            onChange={(e) => onOptions({ ...options, days: Number(e.target.value) })}
            className="rounded-md border border-rule bg-surface px-2 py-1 text-ink"
          >
            {PERIODS.map((d) => (
              <option key={d} value={d}>
                {d} derniers jours
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-2 text-ink-muted">
          Par source
          <select
            value={options.maxResults}
            onChange={(e) => onOptions({ ...options, maxResults: Number(e.target.value) })}
            className="rounded-md border border-rule bg-surface px-2 py-1 text-ink"
          >
            {PER_SOURCE.map((n) => (
              <option key={n} value={n}>
                {n} articles max
              </option>
            ))}
          </select>
        </label>

        <details className="relative">
          <summary className="cursor-pointer list-none text-ink-muted hover:text-ink">
            Catégories arXiv{options.categories.length ? ` (${options.categories.length})` : ""}
          </summary>
          <div className="absolute z-20 mt-2 w-72 space-y-1 rounded-lg border border-rule bg-surface p-3 shadow-[0_8px_24px_-12px_rgb(0_0_0/0.35)]">
            <p className="pb-1 text-xs text-ink-muted">Aucune cochée : toutes les catégories.</p>
            {Object.entries(ARXIV_CATEGORIES).map(([code, label]) => (
              <label key={code} className="flex cursor-pointer items-center gap-2 py-0.5">
                <input type="checkbox" checked={options.categories.includes(code)} onChange={() => toggleCategory(code)} className="accent-[var(--accent)]" />
                <span className="text-ink">{code}</span>
                <span className="text-ink-muted">{label}</span>
              </label>
            ))}
          </div>
        </details>

        <button type="button" className="text-ink-muted hover:text-ink" onClick={() => setShowSyntax(!showSyntax)} aria-expanded={showSyntax}>
          Syntaxe
        </button>
      </div>

      {showSyntax && (
        <p className="max-w-[70ch] text-sm leading-relaxed text-ink-muted">
          La virgule sépare des concepts qui doivent tous apparaître, la barre verticale des synonymes.{" "}
          <span className="text-ink">federated learning, medical imaging | radiology</span> cherche les articles qui parlent
          d'apprentissage fédéré et d'imagerie médicale ou de radiologie, dans le titre ou l'abstract.
        </p>
      )}
    </form>
  );
});
