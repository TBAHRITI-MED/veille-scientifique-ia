// Client de l'API FastAPI (voir api/main.py).

export type Level = "Q1" | "Q2" | "Q3" | "Q4" | "A*" | "A" | "B" | "C" | "Préprint" | "Non classé";

export interface SourceMeta {
  name: string;
  label: string;
  key_env: string | null;
  key_configured: boolean | null;
}

export interface Meta {
  sources: SourceMeta[];
  levels: Level[];
  level_order: Record<string, number>;
  contact_email_configured: boolean;
  examples: string[];
  llm: { configured: boolean; model: string; max_papers: number };
  password_protected: boolean;
}

export interface Analysis {
  resume_fr: string;
  score: number; // 1 à 5
  justification: string;
}

export interface AnalysisResponse {
  analyses: Record<string, Analysis | null>;
  reasons: Record<string, string>;
  stats: {
    cached: boolean;
    analyzed?: number;
    from_cache?: number;
    errors?: number;
    first_error?: string | null;
    seconds?: number;
    model?: string;
  };
}

export interface Paper {
  key: string;
  title: string;
  abstract: string;
  authors: string[];
  published: string; // AAAA-MM-JJ
  url: string;
  pdf_url: string | null;
  doi: string | null;
  doi_url: string | null;
  arxiv_id: string | null;
  pmid: string | null;
  venue: string | null;
  venue_type: "journal" | "conference" | "preprint" | "other";
  citation_count: number | null;
  sources: string[];
  level: Level | null;
  primary_category: string | null;
}

export interface SourceStats {
  label: string;
  count: number;
  total: number | null;
  seconds: number;
  query: string;
}

export interface SearchResult {
  search_id: string;
  topic: string;
  papers: Paper[];
  stats: {
    raw_count: number;
    unique_count: number;
    duplicates_merged: number;
    seconds: number;
    cached: boolean;
    overlap: Record<string, number>;
  };
  by_source: Record<string, SourceStats>;
  errors: Record<string, { label: string; message: string }>;
}

export interface SearchOptions {
  sources: string[];
  days: number;
  maxResults: number;
  categories: string[];
}

export interface RankingsStatus {
  journals: number;
  conferences: number;
  sjr_url: string;
  core_url_template: string;
  default_core_edition: string;
}

export interface DiagnosticRow {
  source: string;
  label: string;
  ok: boolean;
  seconds: number;
  detail: string;
}

export interface HIndex {
  source: "semantic_scholar" | "openalex";
  authors: { name: string; h_index: number | null }[];
  h_max: number | null;
  h_max_author: string | null;
  h_first: number | null;
  h_last: number | null;
}

export interface HIndexResponse {
  metrics: Record<string, HIndex | null>;
  stats: {
    cached: boolean;
    found?: number;
    missing?: number;
    from_cache?: number;
    by_source?: Record<string, number>;
    errors?: Record<string, string>;
    seconds?: number;
  };
}

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("Le serveur ne répond pas. Vérifie que « python -m api » tourne.");
  }
  if (!response.ok) {
    let detail = `Erreur ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = "Paramètres de recherche invalides.";
    } catch {
      /* corps non JSON */
    }
    throw new ApiError(detail);
  }
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  meta: () => request<Meta>("/api/meta"),

  search: (topic: string, o: SearchOptions) =>
    request<SearchResult>(
      "/api/search",
      json({ topic, days: o.days, max_results: o.maxResults, sources: o.sources, arxiv_categories: o.categories }),
    ),

  enrichHIndex: (searchId: string) =>
    request<HIndexResponse>("/api/enrich/hindex", json({ search_id: searchId })),

  enrichAnalysis: (searchId: string, keys: string[]) =>
    request<AnalysisResponse>("/api/enrich/analysis", json({ search_id: searchId, keys })),

  getProfile: () => request<{ text: string; default: string }>("/api/profile"),

  saveProfile: (text: string) =>
    request<{ text: string; default: string }>("/api/profile", { ...json({ text }), method: "PUT" }),

  rankings: () => request<RankingsStatus>("/api/rankings"),

  updateRankings: (coreEdition: string) =>
    request<Record<"sjr" | "core", { ok: boolean; count?: number; error?: string }>>(
      "/api/rankings/update",
      json({ core_edition: coreEdition }),
    ),

  uploadRankings: (kind: "sjr" | "core", file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ count: number }>(`/api/rankings/upload?kind=${kind}`, { method: "POST", body: form });
  },

  diagnostic: () => request<DiagnosticRow[]>("/api/diagnostic", { method: "POST" }),

  async export(searchId: string, keys: string[], format: "csv" | "markdown"): Promise<void> {
    let response: Response;
    try {
      response = await fetch("/api/export", json({ search_id: searchId, keys, format }));
    } catch {
      throw new ApiError("Le serveur ne répond pas.");
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(typeof body.detail === "string" ? body.detail : `Erreur ${response.status}`);
    }
    const disposition = response.headers.get("Content-Disposition") ?? "";
    const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `veille.${format === "csv" ? "csv" : "md"}`;
    const url = URL.createObjectURL(await response.blob());
    const link = Object.assign(document.createElement("a"), { href: url, download: filename });
    link.click();
    URL.revokeObjectURL(url);
  },
};
