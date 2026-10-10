import { useId, useState } from "react";
import { ExternalLink, FileText } from "lucide-react";
import type { Analysis, HIndex, Paper } from "../api";
import { authorsShort, formatDate, type HBasis, levelDescription, spineClass } from "../lib/papers";

/** h-index selon la base choisie, avec le détail par auteur au survol. */
function HIndexNote({ metric, basis }: { metric: HIndex | null | undefined; basis: HBasis }) {
  if (metric === undefined) return null; // pas encore chargé
  if (metric === null) return <span title="Introuvable sur Semantic Scholar et OpenAlex">h-index inconnu</span>;
  const value = basis === "max" ? metric.h_max : metric.h_last;
  const who = basis === "max" ? metric.h_max_author : metric.authors.at(-1)?.name;
  const detail = metric.authors.map((a) => `${a.name} : ${a.h_index ?? "?"}`).join("\n");
  const source = metric.source === "openalex" ? "OpenAlex" : "Semantic Scholar";
  return (
    <span title={`h-index par auteur (${source})\n${detail}`} className="cursor-help">
      {value === null ? "h-index du dernier auteur inconnu" : (
        <>
          <span className="font-semibold text-ink">h {value}</span> {who}
        </>
      )}
    </span>
  );
}

const SCORE_WORDS: Record<number, string> = {
  5: "Au cœur du sujet",
  4: "Traite directement du sujet",
  3: "Connexe",
  2: "Mention en passant",
  1: "Hors sujet",
};

/** Note de pertinence : cinq crans, pleins jusqu'au score. */
function ScoreMeter({ analysis }: { analysis: Analysis }) {
  return (
    <span
      className="inline-flex items-center gap-2 text-xs text-ink-muted"
      title={`Pertinence ${analysis.score}/5 : ${analysis.justification}`}
    >
      <span className="flex gap-[3px]" aria-hidden>
        {[1, 2, 3, 4, 5].map((i) => (
          <span key={i} className={`h-2.5 w-1.5 rounded-[1px] ${i <= analysis.score ? "bg-accent" : "bg-rule"}`} />
        ))}
      </span>
      <span>
        <span className="font-semibold text-ink">{analysis.score}/5</span> {SCORE_WORDS[analysis.score]}
      </span>
    </span>
  );
}

export function PaperRow({
  paper,
  sourceLabels,
  metric,
  basis,
  analysis,
  analysisPending = false,
  notAnalyzedReason,
}: {
  paper: Paper;
  sourceLabels: Record<string, string>;
  metric?: HIndex | null;
  basis: HBasis;
  analysis?: Analysis | null;
  analysisPending?: boolean;
  notAnalyzedReason?: string;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  const links: { label: string; href: string }[] = [];
  if (paper.doi_url && paper.doi_url !== paper.url) links.push({ label: "DOI", href: paper.doi_url });
  if (paper.arxiv_id && !paper.url.includes("arxiv.org"))
    links.push({ label: "arXiv", href: `https://arxiv.org/abs/${paper.arxiv_id}` });
  if (paper.pmid && !paper.url.includes("pubmed"))
    links.push({ label: "PubMed", href: `https://pubmed.ncbi.nlm.nih.gov/${paper.pmid}/` });

  const sources = paper.sources.map((s) => sourceLabels[s] ?? s);

  return (
    <article className="flex gap-4 border-b border-rule py-5 first:pt-2">
      <div className={`spine ${spineClass(paper.level)}`} title={levelDescription(paper.level)} />

      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex items-start justify-between gap-4">
          <h3 className="font-serif text-[1.18rem] leading-snug font-semibold text-pretty text-ink">
            <a href={paper.url} target="_blank" rel="noreferrer" className="hover:text-accent hover:underline decoration-1 underline-offset-3">
              {paper.title}
            </a>
          </h3>
          <span
            className="mt-1 shrink-0 rounded-[4px] border border-rule px-1.5 py-0.5 text-xs font-semibold tabular-nums text-ink"
            title={levelDescription(paper.level)}
          >
            {paper.level ?? "Non classé"}
          </span>
        </div>

        <p className="text-sm text-ink-muted">
          <span className="text-ink">{authorsShort(paper.authors)}</span>
          <span className="mx-2 inline-block h-3 w-px translate-y-0.5 bg-rule" aria-hidden />
          <time dateTime={paper.published}>{formatDate(paper.published)}</time>
          {paper.venue && (
            <>
              <span className="mx-2 inline-block h-3 w-px translate-y-0.5 bg-rule" aria-hidden />
              <span className="italic">{paper.venue}</span>
            </>
          )}
        </p>

        {analysis && (
          <div className="space-y-1.5">
            <ScoreMeter analysis={analysis} />
            <p className="max-w-[72ch] font-serif text-[1rem] leading-[1.65] text-pretty text-ink">{analysis.resume_fr}</p>
          </div>
        )}
        {!analysis && analysisPending && paper.abstract && (
          <div className="max-w-[60ch] space-y-1.5" aria-hidden>
            <div className="skeleton h-3 w-11/12" />
            <div className="skeleton h-3 w-3/4" />
          </div>
        )}
        {analysis === null && notAnalyzedReason && (
          <p className="text-xs text-ink-muted">Pas de résumé : {notAnalyzedReason.charAt(0).toLowerCase() + notAnalyzedReason.slice(1)}.</p>
        )}

        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm">
          {paper.abstract ? (
            <button
              type="button"
              aria-expanded={open}
              aria-controls={panelId}
              onClick={() => setOpen(!open)}
              className="font-medium text-accent hover:underline underline-offset-3"
            >
              {open ? "Masquer l'abstract" : analysis ? "Abstract original" : "Lire l'abstract"}
            </button>
          ) : (
            <span className="text-ink-muted">Pas d'abstract fourni</span>
          )}
          {paper.pdf_url && (
            <a href={paper.pdf_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-ink-muted hover:text-ink">
              <FileText className="size-3.5" aria-hidden /> PDF
            </a>
          )}
          {links.map((l) => (
            <a key={l.label} href={l.href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-ink-muted hover:text-ink">
              <ExternalLink className="size-3.5" aria-hidden /> {l.label}
            </a>
          ))}
          <span className="ml-auto flex flex-wrap items-baseline justify-end gap-x-4 text-xs text-ink-muted">
            <HIndexNote metric={metric} basis={basis} />
            <span>
              {paper.citation_count ? `${paper.citation_count} citation${paper.citation_count > 1 ? "s" : ""}, ` : ""}
              trouvé par {sources.join(", ")}
            </span>
          </span>
        </div>

        <div id={panelId} className="abstract-panel" data-open={open}>
          <div>
            <p className="mt-1 max-w-[72ch] border-l-2 border-rule pl-4 font-serif text-[0.98rem] leading-[1.7] whitespace-pre-line text-ink">
              {paper.abstract}
            </p>
          </div>
        </div>
      </div>
    </article>
  );
}
