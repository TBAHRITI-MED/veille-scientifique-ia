import type { Level, SearchResult } from "../api";
import {
  type AnalysisMap,
  countBy,
  type HBasis,
  H_BASIS_LABELS,
  type HIndexMap,
  paperH,
  paperScore,
  plural,
  spineClass,
} from "../lib/papers";

const H_BUCKETS: [string, number, number][] = [
  ["moins de 10", 0, 9],
  ["10 à 19", 10, 19],
  ["20 à 39", 20, 39],
  ["40 à 79", 40, 79],
  ["80 et plus", 80, Infinity],
];

interface Bar {
  label: string;
  value: number;
  className?: string; // remplissage (tranche de niveau) ; gris par défaut
  hint?: string;
}

/** Barres horizontales fines, valeur imprimée au bout, sans axe (les valeurs suffisent). */
function BarList({ bars, unit }: { bars: Bar[]; unit: [string, string] }) {
  const max = Math.max(1, ...bars.map((b) => b.value));
  return (
    <ul className="space-y-2.5">
      {bars.map((b) => (
        <li key={b.label} className="grid grid-cols-[9rem_1fr] items-center gap-3 text-sm" title={`${b.label} : ${plural(b.value, ...unit)}`}>
          <span className="truncate text-ink">{b.label}</span>
          <span className="flex items-center gap-2.5">
            <span
              className={`block h-3 rounded-r-[4px] ${b.className ?? "bg-ink-muted/45"}`}
              style={{ width: b.value ? `${Math.max(2, (b.value / max) * 100)}%` : 0 }}
            />
            <span className="shrink-0 tabular-nums text-ink-muted">{b.value}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function Panel({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 border-t border-rule pt-5">
      <div>
        <h2 className="font-serif text-lg font-semibold text-ink">{title}</h2>
        {note && <p className="mt-0.5 max-w-[70ch] text-sm text-ink-muted">{note}</p>}
      </div>
      {children}
    </section>
  );
}

export function StatsView({
  result,
  levels,
  hindex,
  hBasis,
  analyses,
}: {
  result: SearchResult;
  levels: Level[];
  hindex: HIndexMap | null;
  hBasis: HBasis;
  analyses: AnalysisMap | null;
}) {
  const scores = analyses ? result.papers.map((p) => paperScore(p, analyses)) : [];
  const hValues = hindex ? result.papers.map((p) => paperH(p, hindex, hBasis)) : [];
  const hUnknown = hValues.filter((v) => v === null).length;
  const levelCounts = countBy(result.papers, (p) => [p.level ?? "Non classé"]);
  const sources = Object.entries(result.by_source).sort((a, b) => b[1].count - a[1].count);
  const overlap = Object.entries(result.stats.overlap);
  const reviewed = result.papers.filter((p) => p.level && p.level !== "Préprint" && p.level !== "Non classé").length;

  return (
    <div className="results-arrive space-y-8">
      <p className="max-w-[70ch] text-[0.95rem] leading-relaxed text-ink-muted">
        Sur {plural(result.stats.unique_count, "article unique", "articles uniques")},{" "}
        <span className="font-semibold text-ink">{reviewed}</span> sont publiés dans une revue ou une conférence classée.{" "}
        {result.stats.raw_count} fiches ont été reçues avant la fusion des doublons.
      </p>

      <div className="grid gap-x-12 gap-y-8 lg:grid-cols-2">
        <Panel title="Niveau des articles" note="Même encre que la tranche des articles : plus elle est dense, mieux la revue ou la conférence est classée.">
          <BarList
            unit={["article", "articles"]}
            bars={levels
              .filter((l) => levelCounts.get(l))
              .map((l) => ({ label: l, value: levelCounts.get(l) ?? 0, className: spineClass(l) }))}
          />
        </Panel>

        <Panel title="Articles reçus par source" note="Avant fusion. Une source peut plafonner au nombre maximum demandé.">
          <BarList unit={["article", "articles"]} bars={sources.map(([, s]) => ({ label: s.label, value: s.count }))} />
        </Panel>

        <Panel title="Recouvrement entre sources" note="Un article trouvé par plusieurs sources est souvent plus visible, ou déjà publié.">
          <BarList
            unit={["article", "articles"]}
            bars={overlap.map(([n, count]) => ({
              label: n === "1" ? "Une seule source" : `${n} sources`,
              value: count,
              className: n === "1" ? undefined : "bg-accent",
            }))}
          />
        </Panel>
        {analyses && (
          <Panel
            title="Pertinence (IA)"
            note={`Score de 1 à 5 donné par le LLM. ${scores.filter((v) => v === null).length} article(s) non analysé(s) ne sont pas comptés.`}
          >
            <BarList
              unit={["article", "articles"]}
              bars={[5, 4, 3, 2, 1].map((n) => ({
                label: `${n} sur 5`,
                value: scores.filter((v) => v === n).length,
                className: "bg-accent",
              }))}
            />
          </Panel>
        )}

        {hindex && (
          <Panel
            title="h-index des auteurs"
            note={`h-index retenu : ${H_BASIS_LABELS[hBasis].toLowerCase()}. ${hUnknown} article${hUnknown > 1 ? "s" : ""} sans h-index connu ne sont pas comptés.`}
          >
            <BarList
              unit={["article", "articles"]}
              bars={H_BUCKETS.map(([label, lo, hi]) => ({
                label,
                value: hValues.filter((v) => v !== null && v >= lo && v <= hi).length,
                className: "bg-accent",
              }))}
            />
          </Panel>
        )}
      </div>

      <Panel title="Requêtes envoyées" note="La traduction exacte de ton sujet dans la syntaxe de chaque source.">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-ink-muted">
              <tr className="border-b border-rule">
                <th className="py-2 pr-4 font-medium">Source</th>
                <th className="py-2 pr-4 text-right font-medium">Correspondances</th>
                <th className="py-2 pr-4 text-right font-medium">Reçus</th>
                <th className="py-2 pr-4 text-right font-medium">Temps</th>
                <th className="py-2 font-medium">Requête</th>
              </tr>
            </thead>
            <tbody>
              {sources.map(([name, s]) => (
                <tr key={name} className="border-b border-rule align-top">
                  <td className="py-2.5 pr-4 text-ink">{s.label}</td>
                  <td className="py-2.5 pr-4 text-right tabular-nums text-ink-muted">{s.total?.toLocaleString("fr-FR") ?? "inconnu"}</td>
                  <td className="py-2.5 pr-4 text-right tabular-nums text-ink-muted">{s.count}</td>
                  <td className="py-2.5 pr-4 text-right tabular-nums text-ink-muted">{s.seconds.toLocaleString("fr-FR")} s</td>
                  <td className="py-2.5 font-mono text-xs break-all text-ink-muted">{s.query}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
