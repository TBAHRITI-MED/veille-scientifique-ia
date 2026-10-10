import { useEffect, useState } from "react";
import { CheckCircle2, CircleSlash, XCircle } from "lucide-react";
import { api, type DiagnosticRow, type Meta, type RankingsStatus } from "../api";
import { Button, Notice } from "./ui";

function Panel({ title, note, children }: { title: string; note?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="space-y-4 border-t border-rule pt-6 first:border-t-0 first:pt-0">
      <div>
        <h2 className="font-serif text-lg font-semibold text-ink">{title}</h2>
        {note && <p className="mt-1 max-w-[70ch] text-sm leading-relaxed text-ink-muted">{note}</p>}
      </div>
      {children}
    </section>
  );
}

export function SettingsView({
  meta,
  rankings,
  onRankingsChanged,
}: {
  meta: Meta;
  rankings: RankingsStatus | null;
  onRankingsChanged: () => void;
}) {
  const [edition, setEdition] = useState(rankings?.default_core_edition ?? "CORE2023");
  const [updating, setUpdating] = useState(false);
  const [messages, setMessages] = useState<{ ok: boolean; text: string }[]>([]);
  const [diag, setDiag] = useState<DiagnosticRow[] | null>(null);
  const [diagRunning, setDiagRunning] = useState(false);
  const [diagError, setDiagError] = useState<string | null>(null);

  const update = async () => {
    setUpdating(true);
    setMessages([]);
    try {
      const report = await api.updateRankings(edition);
      setMessages(
        (["sjr", "core"] as const).map((k) => ({
          ok: report[k].ok,
          text: report[k].ok
            ? `${k === "sjr" ? "SJR" : "CORE"} mis à jour : ${report[k].count} entrées classées.`
            : `${k === "sjr" ? "SJR" : "CORE"} : téléchargement refusé (${report[k].error}). Importe le fichier à la main.`,
        })),
      );
      onRankingsChanged();
    } catch (e) {
      setMessages([{ ok: false, text: (e as Error).message }]);
    } finally {
      setUpdating(false);
    }
  };

  const upload = async (kind: "sjr" | "core", file: File | undefined) => {
    if (!file) return;
    try {
      const { count } = await api.uploadRankings(kind, file);
      setMessages([{ ok: true, text: `${kind === "sjr" ? "SJR" : "CORE"} importé : ${count} entrées classées.` }]);
      onRankingsChanged();
    } catch (e) {
      setMessages([{ ok: false, text: (e as Error).message }]);
    }
  };

  const runDiagnostic = async () => {
    setDiagRunning(true);
    setDiagError(null);
    try {
      setDiag(await api.diagnostic());
    } catch (e) {
      setDiagError((e as Error).message);
    } finally {
      setDiagRunning(false);
    }
  };

  const coreUrl = rankings?.core_url_template.replace("{edition}", edition);

  return (
    <div className="results-arrive max-w-3xl space-y-10">
      <ProfilePanel meta={meta} />

      <Panel
        title="Classements des publications"
        note="Le niveau Q1 à Q4 vient de SCImago (SJR, revues), le rang A* à C du portail CORE (conférences). Les fichiers sont gardés dans le dossier data/ du projet."
      >
        <dl className="grid grid-cols-2 gap-4 sm:max-w-md">
          <div>
            <dt className="text-sm text-ink-muted">Revues classées</dt>
            <dd className="font-serif text-3xl font-semibold tabular-nums text-ink">{rankings?.journals.toLocaleString("fr-FR") ?? "…"}</dd>
          </div>
          <div>
            <dt className="text-sm text-ink-muted">Conférences classées</dt>
            <dd className="font-serif text-3xl font-semibold tabular-nums text-ink">{rankings?.conferences.toLocaleString("fr-FR") ?? "…"}</dd>
          </div>
        </dl>

        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-1 text-sm">
            <span className="block text-ink-muted">Édition CORE</span>
            <input
              value={edition}
              onChange={(e) => setEdition(e.target.value)}
              className="w-36 rounded-md border border-rule bg-surface px-2.5 py-1.5 text-ink focus:border-accent focus:outline-none"
            />
          </label>
          <Button variant="primary" onClick={update} disabled={updating}>
            {updating ? "Téléchargement…" : "Mettre à jour les classements"}
          </Button>
        </div>

        <details className="text-sm">
          <summary className="cursor-pointer text-ink-muted hover:text-ink">Importer les fichiers à la main</summary>
          <div className="mt-3 space-y-3 border-l-2 border-rule pl-4">
            <p className="text-ink-muted">
              Si un site refuse le téléchargement automatique, récupère le fichier dans ton navigateur puis importe-le ici.
            </p>
            {[
              { kind: "sjr" as const, label: "Fichier SJR", href: rankings?.sjr_url },
              { kind: "core" as const, label: "Fichier CORE", href: coreUrl },
            ].map(({ kind, label, href }) => (
              <div key={kind} className="flex flex-wrap items-center gap-3">
                <label className="cursor-pointer rounded-md border border-rule bg-surface px-3 py-1.5 font-medium text-ink hover:border-ink-muted">
                  {label}…
                  <input type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => upload(kind, e.target.files?.[0])} />
                </label>
                {href && (
                  <a href={href} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                    Télécharger depuis {kind === "sjr" ? "scimagojr.com" : "portal.core.edu.au"}
                  </a>
                )}
              </div>
            ))}
          </div>
        </details>

        {messages.map((m) => (
          <Notice key={m.text} tone={m.ok ? "info" : "warn"}>
            {m.text}
          </Notice>
        ))}
      </Panel>

      <Panel
        title="Clés d'API"
        note={
          <>
            Toutes optionnelles : elles augmentent les quotas. Ajoute-les dans le fichier <span className="text-ink">.env</span> à la
            racine du projet (modèle : .env.example), puis relance le serveur.
          </>
        }
      >
        <ul className="divide-y divide-rule border-y border-rule text-sm">
          {meta.sources.map((s) => (
            <li key={s.name} className="flex items-center gap-3 py-2.5">
              <span className="w-40 text-ink">{s.label}</span>
              <span className="flex-1 text-ink-muted">{s.key_env ?? "Aucune clé nécessaire"}</span>
              {s.key_env &&
                (s.key_configured ? (
                  <span className="inline-flex items-center gap-1.5 text-ink">
                    <CheckCircle2 className="size-4 text-accent" aria-hidden /> Configurée
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 text-ink-muted">
                    <CircleSlash className="size-4" aria-hidden /> Absente
                  </span>
                ))}
            </li>
          ))}
        </ul>
        {!meta.contact_email_configured && (
          <p className="text-sm text-ink-muted">Renseigne aussi CONTACT_EMAIL : OpenAlex et NCBI le recommandent.</p>
        )}
      </Panel>

      <Panel title="Diagnostic des sources" note="Envoie une petite requête (« machine learning », 7 jours, 3 articles) à chaque source.">
        <Button onClick={runDiagnostic} disabled={diagRunning}>
          {diagRunning ? "Test en cours…" : "Tester les sources"}
        </Button>
        {diagError && <Notice>{diagError}</Notice>}
        {diag && (
          <ul className="divide-y divide-rule border-y border-rule text-sm">
            {diag.map((d) => (
              <li key={d.source} className="flex items-start gap-3 py-2.5">
                {d.ok ? (
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-accent" aria-label="Fonctionne" />
                ) : (
                  <XCircle className="mt-0.5 size-4 shrink-0 text-danger" aria-label="En erreur" />
                )}
                <span className="w-36 shrink-0 text-ink">{d.label}</span>
                <span className="flex-1 break-words text-ink-muted">{d.detail}</span>
                <span className="shrink-0 tabular-nums text-ink-muted">{d.seconds.toLocaleString("fr-FR")} s</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

function ProfilePanel({ meta }: { meta: Meta }) {
  const [text, setText] = useState("");
  const [saved, setSaved] = useState("");
  const [fallback, setFallback] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    api
      .getProfile()
      .then((p) => {
        setText(p.text);
        setSaved(p.text);
        setFallback(p.default);
      })
      .catch((e: Error) => setMessage({ ok: false, text: e.message }));
  }, []);

  const save = async (value: string) => {
    try {
      const p = await api.saveProfile(value);
      setText(p.text);
      setSaved(p.text);
      setMessage({ ok: true, text: "Profil enregistré. Il s'applique à la prochaine recherche." });
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message });
    }
  };

  return (
    <Panel
      title="Analyse par IA"
      note={
        meta.llm.configured ? (
          <>
            Chaque recherche fait résumer en français et noter de 1 à 5 jusqu'à {meta.llm.max_papers} articles par le
            modèle <span className="text-ink">{meta.llm.model}</span>. Un article déjà analysé pour le même sujet et le
            même profil n'est pas renvoyé au modèle.
          </>
        ) : (
          <>
            Désactivée : ajoute <span className="text-ink">ANTHROPIC_API_KEY</span> dans le fichier .env puis relance le
            serveur. L'application fonctionne sans, mais sans résumé ni score.
          </>
        )
      }
    >
      <label className="block space-y-1.5 text-sm">
        <span className="block font-medium text-ink">Profil de recherche</span>
        <span className="block text-ink-muted">
          Tes sujets et ton niveau, en quelques phrases. Le modèle s'en sert pour orienter les résumés et lever les
          ambiguïtés du sujet.
        </span>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          maxLength={2000}
          className="w-full rounded-md border border-rule bg-surface px-3 py-2 leading-relaxed text-ink focus:border-accent focus:outline-none"
        />
      </label>
      <div className="flex flex-wrap gap-3">
        <Button variant="primary" onClick={() => save(text)} disabled={text.trim().length < 10 || text === saved}>
          Enregistrer le profil
        </Button>
        {fallback && text !== fallback && (
          <Button variant="quiet" onClick={() => save(fallback)}>
            Revenir au profil par défaut
          </Button>
        )}
      </div>
      {message && <Notice tone={message.ok ? "info" : "warn"}>{message.text}</Notice>}
    </Panel>
  );
}
