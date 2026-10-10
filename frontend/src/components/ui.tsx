import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "quiet" | "outline";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-ink hover:brightness-110 disabled:opacity-50",
  outline: "border border-rule text-ink hover:border-ink-muted bg-surface disabled:opacity-50",
  quiet: "text-ink-muted hover:text-ink disabled:opacity-50",
};

export function Button({
  variant = "outline",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-[filter,border-color,color] disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}

/** Interrupteur à cocher, utilisé pour les sources et les filtres. */
export function Toggle({
  checked,
  onChange,
  children,
  count,
  swatch,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
  count?: number;
  swatch?: ReactNode;
}) {
  return (
    <label className="group flex cursor-pointer items-center gap-2.5 rounded-md py-1 text-sm select-none">
      <input
        type="checkbox"
        className="peer sr-only"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span
        aria-hidden
        className="grid size-4 place-items-center rounded-[4px] border border-rule bg-surface text-accent-ink peer-checked:border-accent peer-checked:bg-accent peer-focus-visible:outline-2 peer-focus-visible:outline-accent peer-focus-visible:outline-offset-2"
      >
        {checked && (
          <svg viewBox="0 0 12 12" className="size-3" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M2.5 6.2 5 8.5l4.5-5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </span>
      {swatch}
      <span className={checked ? "text-ink" : "text-ink-muted"}>{children}</span>
      {count !== undefined && <span className="ml-auto tabular-nums text-ink-muted">{count}</span>}
    </label>
  );
}

export function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Notice({ tone = "warn", children }: { tone?: "warn" | "info"; children: ReactNode }) {
  const styles = tone === "warn" ? "bg-warn-soft text-warn" : "bg-accent-soft text-ink";
  return <div className={`rounded-md px-3.5 py-2.5 text-sm leading-relaxed ${styles}`}>{children}</div>;
}
