// Logique pure (testée avec Vitest) : filtres, tri, frise des jours, libellés.

import type { Analysis, HIndex, Level, Paper } from "../api";

export type SortKey = "recent" | "score" | "level" | "cited" | "hindex";

export const SORT_LABELS: Record<SortKey, string> = {
  recent: "Plus récents",
  score: "Pertinence (IA)",
  level: "Niveau, Q1 et A* d'abord",
  cited: "Plus cités",
  hindex: "h-index des auteurs",
};

export type AnalysisMap = Record<string, Analysis | null>;

/** Données chargées en arrière-plan après la recherche. */
export interface Enrichment {
  hindex?: HIndexMap | null;
  analyses?: AnalysisMap | null;
  basis?: HBasis;
}

/** Sur quel auteur calculer le h-index d'un article. */
export type HBasis = "max" | "last";

export const H_BASIS_LABELS: Record<HBasis, string> = {
  max: "Le plus élevé des auteurs",
  last: "Le dernier auteur",
};

export type HIndexMap = Record<string, HIndex | null>;

export interface Filters {
  levels: Set<string>; // vide = tous
  sources: Set<string>; // vide = toutes
  text: string;
  day: string | null; // AAAA-MM-JJ
  hMin: number; // 0 = pas de filtre
  hBasis: HBasis;
  keepUnknownH: boolean; // garder les articles dont le h-index est introuvable
  scoreMin: number; // 0 = pas de filtre, sinon 1 à 5
  keepUnscored: boolean; // garder les articles non analysés par le LLM
}

export const emptyFilters = (): Filters => ({
  levels: new Set(),
  sources: new Set(),
  text: "",
  day: null,
  hMin: 0,
  hBasis: "max",
  keepUnknownH: true,
  scoreMin: 0,
  keepUnscored: true,
});

export function paperScore(paper: Paper, analyses: AnalysisMap | null | undefined): number | null {
  return analyses?.[paper.key]?.score ?? null;
}

/** h-index retenu pour un article selon la base choisie ; null si inconnu. */
export function paperH(paper: Paper, hindex: HIndexMap | null, basis: HBasis): number | null {
  const metric = hindex?.[paper.key];
  if (!metric) return null;
  return basis === "max" ? metric.h_max : metric.h_last;
}

export function filterPapers(papers: Paper[], f: Filters, enrich: Enrichment = {}): Paper[] {
  const needle = f.text.trim().toLowerCase();
  const hindex = enrich.hindex ?? null;
  const analyses = enrich.analyses ?? null;
  const hActive = hindex !== null && f.hMin > 0;
  const scoreActive = analyses !== null && f.scoreMin > 0;
  return papers.filter((p) => {
    if (f.levels.size && !f.levels.has(p.level ?? "Non classé")) return false;
    if (f.sources.size && !p.sources.some((s) => f.sources.has(s))) return false;
    if (f.day !== null && p.published !== f.day) return false;
    if (needle && !`${p.title} ${p.abstract} ${p.authors.join(" ")}`.toLowerCase().includes(needle)) return false;
    if (hActive) {
      const h = paperH(p, hindex, f.hBasis);
      if (h === null ? !f.keepUnknownH : h < f.hMin) return false;
    }
    if (scoreActive) {
      const score = paperScore(p, analyses);
      if (score === null ? !f.keepUnscored : score < f.scoreMin) return false;
    }
    return true;
  });
}

export function sortPapers(
  papers: Paper[],
  sort: SortKey,
  levelOrder: Record<string, number>,
  enrich: Enrichment = {},
): Paper[] {
  const byDate = (a: Paper, b: Paper) => b.published.localeCompare(a.published);
  const copy = [...papers];
  if (sort === "recent") return copy.sort(byDate);
  if (sort === "cited") return copy.sort((a, b) => (b.citation_count ?? 0) - (a.citation_count ?? 0) || byDate(a, b));
  if (sort === "hindex") {
    // h-index inconnu : en fin de liste.
    const value = (p: Paper) => paperH(p, enrich.hindex ?? null, enrich.basis ?? "max") ?? -1;
    return copy.sort((a, b) => value(b) - value(a) || byDate(a, b));
  }
  if (sort === "score") {
    // Non analysé : en fin de liste.
    const value = (p: Paper) => paperScore(p, enrich.analyses) ?? 0;
    return copy.sort((a, b) => value(b) - value(a) || byDate(a, b));
  }
  const rank = (p: Paper) => levelOrder[p.level ?? "Non classé"] ?? 9;
  return copy.sort((a, b) => rank(a) - rank(b) || byDate(a, b));
}

/** Compte par valeur (niveau, source…) ; sert aux compteurs du rail de filtres. */
export function countBy(papers: Paper[], pick: (p: Paper) => string[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const p of papers) for (const k of pick(p)) counts.set(k, (counts.get(k) ?? 0) + 1);
  return counts;
}

/** Un compteur par jour sur la fenêtre, du plus ancien au plus récent (jours vides inclus). */
export function dayCounts(papers: Paper[], days: number, today: Date): { day: string; count: number }[] {
  const counts = countBy(papers, (p) => [p.published]);
  const out: { day: string; count: number }[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - i));
    const key = d.toISOString().slice(0, 10);
    out.push({ day: key, count: counts.get(key) ?? 0 });
  }
  return out;
}

/** Classe CSS de la tranche : densité d'encre selon le niveau. */
export function spineClass(level: Level | null): string {
  switch (level) {
    case "Q1":
    case "A*":
      return "spine-1";
    case "Q2":
    case "A":
      return "spine-2";
    case "Q3":
    case "B":
      return "spine-3";
    case "Q4":
    case "C":
      return "spine-4";
    case "Préprint":
      return "spine-preprint";
    default:
      return "spine-unranked";
  }
}

export function levelDescription(level: Level | null): string {
  if (!level || level === "Non classé") return "Support absent des classements";
  if (level === "Préprint") return "Préprint, pas encore relu par des pairs";
  if (level.startsWith("Q")) return `Revue ${level} (SJR)`;
  return `Conférence de rang ${level} (CORE)`;
}

const DATE_FMT = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const DAY_FMT = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });

export const formatDate = (iso: string) => DATE_FMT.format(new Date(`${iso}T00:00:00Z`));
export const formatDay = (iso: string) => DAY_FMT.format(new Date(`${iso}T00:00:00Z`));

export function authorsShort(authors: string[]): string {
  if (authors.length === 0) return "Auteurs inconnus";
  if (authors.length <= 3) return authors.join(", ");
  return `${authors.slice(0, 3).join(", ")} et ${authors.length - 3} autres`;
}

export const plural = (n: number, one: string, many: string) => `${n.toLocaleString("fr-FR")} ${n > 1 ? many : one}`;

/** Niveaux triés par palier : Q1, A*, Q2, A… puis Non classé et Préprint. */
export function orderLevels<T extends string>(levels: T[], levelOrder: Record<string, number>): T[] {
  return [...levels].sort((a, b) => (levelOrder[a] ?? 9) - (levelOrder[b] ?? 9) || levels.indexOf(a) - levels.indexOf(b));
}
