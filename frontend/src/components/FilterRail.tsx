import { useId } from "react";
import type { Level, Paper, SourceMeta } from "../api";
import {
  type AnalysisMap,
  countBy,
  emptyFilters,
  type Filters,
  H_BASIS_LABELS,
  type HBasis,
  type HIndexMap,
  paperH,
  paperScore,
  SORT_LABELS,
  type SortKey,
  spineClass,
} from "../lib/papers";
import { Section, Toggle } from "./ui";

interface Props {
  papers: Paper[];
  levels: Level[];
  sources: SourceMeta[];
  filters: Filters;
  onFilters: (f: Filters) => void;
  sort: SortKey;
  onSort: (s: SortKey) => void;
  history: string[];
  onHistory: (topic: string) => void;
  hindex: HIndexMap | null;
  hStatus: HStatus;
  analyses: AnalysisMap | null;
  aStatus: AnalysisStatus;
}

export type HStatus = { state: "idle" | "loading" | "done" } | { state: "error"; message: string };
export type AnalysisStatus =
  | { state: "idle" | "loading" | "disabled" }
  | { state: "done"; errors: number }
  | { state: "error"; message: string };

function toggleIn(set: Set<string>, value: string, on: boolean): Set<string> {
  const next = new Set(set);
  if (on) next.add(value);
  else next.delete(value);
  return next;
}

export function FilterRail({
  papers,
  levels,
  sources,
  filters,
  onFilters,
  sort,
  onSort,
  history,
  onHistory,
  hindex,
  hStatus,
  analyses,
  aStatus,
}: Props) {
  const sortGroup = useId(); // un groupe radio par exemplaire du rail (mobile et bureau)
  const levelCounts = countBy(papers, (p) => [p.level ?? "Non classé"]);
  const sourceCounts = countBy(papers, (p) => p.sources);
  const presentLevels = levels.filter((l) => levelCounts.get(l));
  const presentSources = sources.filter((s) => sourceCounts.get(s.name));
  const isActive =
    filters.levels.size > 0 ||
    filters.sources.size > 0 ||
    filters.day !== null ||
    filters.text !== "" ||
    filters.hMin > 0 ||
    filters.scoreMin > 0;

  return (
    <aside className="space-y-7">
      {papers.length > 0 && (
        <>
          <ScoreSection papers={papers} analyses={analyses} status={aStatus} filters={filters} onFilters={onFilters} />

          <Section
            title="Niveau"
            aside={
              isActive && (
                <button
                  type="button"
                  className="text-xs text-accent hover:underline"
                  onClick={() => onFilters({ ...emptyFilters(), hBasis: filters.hBasis })}
                  title="Réinitialise tous les filtres"
                >
                  Tout afficher
                </button>
              )
            }
          >
            <div>
              {presentLevels.map((level) => (
                <Toggle
                  key={level}
                  checked={filters.levels.has(level)}
                  onChange={(on) => onFilters({ ...filters, levels: toggleIn(filters.levels, level, on) })}
                  count={levelCounts.get(level)}
                  swatch={<span className={`spine h-4 ${spineClass(level)}`} aria-hidden />}
                >
                  {level}
                </Toggle>
              ))}
            </div>
            <p className="text-xs leading-relaxed text-ink-muted">
              Encre pleine pour Q1 et A*, plus claire en descendant, hachurée pour les préprints.
            </p>
          </Section>

          <Section title="Trouvé par">
            <div>
              {presentSources.map((s) => (
                <Toggle
                  key={s.name}
                  checked={filters.sources.has(s.name)}
                  onChange={(on) => onFilters({ ...filters, sources: toggleIn(filters.sources, s.name, on) })}
                  count={sourceCounts.get(s.name)}
                >
                  {s.label}
                </Toggle>
              ))}
            </div>
          </Section>

          <HIndexSection papers={papers} hindex={hindex} status={hStatus} filters={filters} onFilters={onFilters} />

          <Section title="Trier">
            <div className="space-y-0.5">
              {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
                <label
                  key={key}
                  className={`flex items-center gap-2.5 py-1 text-sm ${
                    (key === "hindex" && !hindex) || (key === "score" && !analyses)
                      ? "cursor-not-allowed opacity-50"
                      : "cursor-pointer"
                  }`}
                >
                  <input
                    type="radio"
                    name={sortGroup}
                    checked={sort === key}
                    disabled={(key === "hindex" && !hindex) || (key === "score" && !analyses)}
                    onChange={() => onSort(key)}
                    className="accent-[var(--accent)]"
                  />
                  <span className={sort === key ? "text-ink" : "text-ink-muted"}>{SORT_LABELS[key]}</span>
                </label>
              ))}
            </div>
          </Section>
        </>
      )}

      {history.length > 0 && (
        <Section title="Recherches récentes">
          <ul className="space-y-1">
            {history.map((topic) => (
              <li key={topic}>
                <button
                  type="button"
                  onClick={() => onHistory(topic)}
                  className="w-full truncate text-left text-sm text-ink-muted hover:text-accent"
                  title={topic}
                >
                  {topic}
                </button>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </aside>
  );
}

function HIndexSection({
  papers,
  hindex,
  status,
  filters,
  onFilters,
}: {
  papers: Paper[];
  hindex: HIndexMap | null;
  status: HStatus;
  filters: Filters;
  onFilters: (f: Filters) => void;
}) {
  const sliderId = useId();
  const basisGroup = useId();
  const values = hindex ? papers.map((p) => paperH(p, hindex, filters.hBasis)) : [];
  const known = values.filter((v): v is number => v !== null);
  const unknown = values.length - known.length;
  const maxH = Math.max(0, ...known);

  return (
    <Section title="h-index des auteurs">
      {status.state === "loading" && (
        <p className="flex items-center gap-2 text-sm text-ink-muted" aria-live="polite">
          <span className="skeleton inline-block size-2.5 rounded-full" aria-hidden /> Récupération en cours…
        </p>
      )}
      {status.state === "error" && <p className="text-sm text-warn">h-index indisponible : {status.message}</p>}
      {hindex && (
        <div className="space-y-3">
          <p className="text-xs leading-relaxed text-ink-muted">
            Connu pour {known.length} article{known.length > 1 ? "s" : ""} sur {values.length}, d'après Semantic Scholar
            ou, à défaut, OpenAlex.
          </p>

          <fieldset className="space-y-0.5">
            <legend className="pb-1 text-sm text-ink-muted">h-index retenu par article</legend>
            {(Object.keys(H_BASIS_LABELS) as HBasis[]).map((b) => (
              <label key={b} className="flex cursor-pointer items-center gap-2.5 py-0.5 text-sm">
                <input
                  type="radio"
                  name={basisGroup}
                  checked={filters.hBasis === b}
                  onChange={() => onFilters({ ...filters, hBasis: b })}
                  className="accent-[var(--accent)]"
                />
                <span className={filters.hBasis === b ? "text-ink" : "text-ink-muted"}>{H_BASIS_LABELS[b]}</span>
              </label>
            ))}
            <p className="pt-1 text-xs leading-relaxed text-ink-muted">
              Le dernier auteur est souvent le responsable de l'équipe.
            </p>
          </fieldset>

          <div className="space-y-1">
            <label htmlFor={sliderId} className="flex items-baseline justify-between text-sm">
              <span className="text-ink-muted">Minimum</span>
              <span className="tabular-nums text-ink">{filters.hMin === 0 ? "aucun" : `h ≥ ${filters.hMin}`}</span>
            </label>
            <input
              id={sliderId}
              type="range"
              min={0}
              max={Math.max(1, maxH)}
              step={1}
              value={Math.min(filters.hMin, Math.max(1, maxH))}
              disabled={known.length === 0}
              onChange={(e) => onFilters({ ...filters, hMin: Number(e.target.value) })}
              className="w-full accent-[var(--accent)]"
            />
          </div>

          <Toggle
            checked={filters.keepUnknownH}
            onChange={(on) => onFilters({ ...filters, keepUnknownH: on })}
            count={unknown}
          >
            Garder les h-index inconnus
          </Toggle>
        </div>
      )}
    </Section>
  );
}

const SCORE_STEPS: { value: number; label: string }[] = [
  { value: 0, label: "Tous" },
  { value: 3, label: "3 et +" },
  { value: 4, label: "4 et +" },
  { value: 5, label: "5" },
];

function ScoreSection({
  papers,
  analyses,
  status,
  filters,
  onFilters,
}: {
  papers: Paper[];
  analyses: AnalysisMap | null;
  status: AnalysisStatus;
  filters: Filters;
  onFilters: (f: Filters) => void;
}) {
  const scores = analyses ? papers.map((p) => paperScore(p, analyses)) : [];
  const analyzed = scores.filter((s) => s !== null).length;

  return (
    <Section title="Pertinence (IA)">
      {status.state === "loading" && (
        <p className="flex items-center gap-2 text-sm text-ink-muted" aria-live="polite">
          <span className="skeleton inline-block size-2.5 rounded-full" aria-hidden /> Résumés en cours de rédaction…
        </p>
      )}
      {status.state === "disabled" && (
        <p className="text-xs leading-relaxed text-ink-muted">
          Désactivée : ajoute ANTHROPIC_API_KEY dans le fichier .env pour obtenir un résumé en français et une note de
          pertinence par article.
        </p>
      )}
      {status.state === "error" && <p className="text-sm text-warn">Analyse indisponible : {status.message}</p>}
      {analyses && (
        <div className="space-y-3">
          <p className="text-xs leading-relaxed text-ink-muted">
            {analyzed} article{analyzed > 1 ? "s" : ""} sur {papers.length} résumé{analyzed > 1 ? "s" : ""} et noté
            {analyzed > 1 ? "s" : ""} de 1 à 5.
            {status.state === "done" && status.errors > 0 && ` ${status.errors} en erreur.`}
          </p>
          <div className="flex rounded-md border border-rule bg-surface p-0.5" role="radiogroup" aria-label="Score minimum">
            {SCORE_STEPS.map((step) => (
              <button
                key={step.value}
                type="button"
                role="radio"
                aria-checked={filters.scoreMin === step.value}
                onClick={() => onFilters({ ...filters, scoreMin: step.value })}
                className={`flex-1 rounded px-1.5 py-1 text-xs ${
                  filters.scoreMin === step.value ? "bg-accent font-semibold text-accent-ink" : "text-ink-muted hover:text-ink"
                }`}
              >
                {step.label}
              </button>
            ))}
          </div>
          <Toggle
            checked={filters.keepUnscored}
            onChange={(on) => onFilters({ ...filters, keepUnscored: on })}
            count={papers.length - analyzed}
          >
            Garder les non analysés
          </Toggle>
        </div>
      )}
    </Section>
  );
}
