import type { Paper } from "../api";
import { dayCounts, formatDay, plural } from "../lib/papers";

/** Frise des publications par jour : chaque barre filtre la liste sur ce jour. */
export function DayStrip({
  papers,
  days,
  selected,
  onSelect,
}: {
  papers: Paper[];
  days: number;
  selected: string | null;
  onSelect: (day: string | null) => void;
}) {
  const strip = dayCounts(papers, days, new Date());
  const max = Math.max(1, ...strip.map((d) => d.count));
  const height = 44;

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between text-xs text-ink-muted">
        <span>
          {selected ? (
            <>
              Articles du {formatDay(selected)}{" "}
              <button type="button" className="ml-1 font-medium text-accent hover:underline" onClick={() => onSelect(null)}>
                Voir toutes les dates
              </button>
            </>
          ) : (
            `Publications par jour sur ${days} jours. Clique un jour pour filtrer.`
          )}
        </span>
        <span className="tabular-nums">max {max}</span>
      </div>
      <div className="flex items-end gap-[2px]" style={{ height }} role="group" aria-label="Publications par jour">
        {strip.map(({ day, count }) => {
          const active = selected === day;
          const dimmed = selected !== null && !active;
          return (
            <button
              key={day}
              type="button"
              disabled={count === 0}
              onClick={() => onSelect(active ? null : day)}
              title={`${formatDay(day)} : ${plural(count, "article", "articles")}`}
              aria-label={`${formatDay(day)}, ${plural(count, "article", "articles")}`}
              aria-pressed={active}
              className="group flex h-full min-w-0 flex-1 items-end disabled:cursor-default"
            >
              <span
                className={`block w-full rounded-t-[3px] transition-opacity ${count ? "bg-accent" : "bg-rule"} ${dimmed ? "opacity-30" : "group-hover:opacity-80"}`}
                style={{ height: count ? Math.max(4, (count / max) * height) : 2 }}
              />
            </button>
          );
        })}
      </div>
    </div>
  );
}
