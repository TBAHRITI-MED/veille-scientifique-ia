import { describe, expect, it } from "vitest";
import type { Paper } from "../api";
import { type AnalysisMap, authorsShort, dayCounts, emptyFilters, filterPapers, type HIndexMap, sortPapers, spineClass } from "./papers";

const paper = (over: Partial<Paper>): Paper => ({
  key: over.title ?? "k",
  title: "T",
  abstract: "",
  authors: [],
  published: "2026-10-01",
  url: "u",
  pdf_url: null,
  doi: null,
  doi_url: null,
  arxiv_id: null,
  pmid: null,
  venue: null,
  venue_type: "other",
  citation_count: null,
  sources: ["arxiv"],
  level: "Préprint",
  primary_category: null,
  ...over,
});

const ORDER = { Q1: 0, "A*": 0, Q2: 1, A: 1, Q3: 2, B: 2, Q4: 3, C: 3, "Non classé": 4, "Préprint": 5 };

const papers = [
  paper({ title: "Federated chest X-ray", level: "Q1", sources: ["openalex", "pubmed"], published: "2026-10-03", citation_count: 2 }),
  paper({ title: "LLM fine-tuning", abstract: "parameter-efficient", level: "Préprint", published: "2026-10-08" }),
  paper({ title: "MICCAI paper", level: "A", sources: ["semantic_scholar"], published: "2026-10-01", citation_count: 9 }),
];

describe("filterPapers", () => {
  it("garde tout sans filtre", () => {
    expect(filterPapers(papers, emptyFilters())).toHaveLength(3);
  });
  it("filtre par niveau, source, texte et jour", () => {
    expect(filterPapers(papers, { ...emptyFilters(), levels: new Set(["Q1", "A"]) })).toHaveLength(2);
    expect(filterPapers(papers, { ...emptyFilters(), sources: new Set(["pubmed"]) })[0].title).toBe("Federated chest X-ray");
    expect(filterPapers(papers, { ...emptyFilters(), text: "EFFICIENT" })[0].title).toBe("LLM fine-tuning");
    expect(filterPapers(papers, { ...emptyFilters(), day: "2026-10-01" })[0].title).toBe("MICCAI paper");
  });
});

describe("sortPapers", () => {
  it("trie par date, niveau et citations", () => {
    expect(sortPapers(papers, "recent", ORDER).map((p) => p.title)[0]).toBe("LLM fine-tuning");
    expect(sortPapers(papers, "level", ORDER).map((p) => p.level)).toEqual(["Q1", "A", "Préprint"]);
    expect(sortPapers(papers, "cited", ORDER)[0].title).toBe("MICCAI paper");
  });
  it("ne modifie pas la liste d'origine", () => {
    sortPapers(papers, "cited", ORDER);
    expect(papers[0].title).toBe("Federated chest X-ray");
  });
});

describe("dayCounts", () => {
  it("couvre chaque jour de la fenêtre, jours vides compris", () => {
    const strip = dayCounts(papers, 10, new Date(Date.UTC(2026, 9, 10)));
    expect(strip).toHaveLength(10);
    expect(strip[0].day).toBe("2026-10-01");
    expect(strip.at(-1)?.day).toBe("2026-10-10");
    expect(strip.find((d) => d.day === "2026-10-03")?.count).toBe(1);
    expect(strip.reduce((s, d) => s + d.count, 0)).toBe(3);
  });
});

describe("libellés", () => {
  it("encre selon le niveau", () => {
    expect(spineClass("A*")).toBe("spine-1");
    expect(spineClass("Q4")).toBe("spine-4");
    expect(spineClass("Préprint")).toBe("spine-preprint");
    expect(spineClass(null)).toBe("spine-unranked");
  });
  it("tronque les auteurs", () => {
    expect(authorsShort(["A", "B", "C", "D", "E"])).toBe("A, B, C et 2 autres");
    expect(authorsShort([])).toBe("Auteurs inconnus");
  });
});

describe("h-index", () => {
  const metric = (h_max: number, h_last: number) => ({
    source: "semantic_scholar" as const,
    authors: [],
    h_max,
    h_max_author: "X",
    h_first: null,
    h_last,
  });
  // papers[0] : max 41 / dernier 5 ; papers[1] : inconnu ; papers[2] : max 12 / dernier 12
  const hindex: HIndexMap = {
    "Federated chest X-ray": metric(41, 5),
    "LLM fine-tuning": null,
    "MICCAI paper": metric(12, 12),
  };

  it("filtre sur le minimum selon la base choisie", () => {
    const f = { ...emptyFilters(), hMin: 10 };
    expect(filterPapers(papers, f, { hindex }).map((p) => p.title)).toEqual([
      "Federated chest X-ray", "LLM fine-tuning", "MICCAI paper",
    ]);
    expect(filterPapers(papers, { ...f, keepUnknownH: false }, { hindex })).toHaveLength(2);
    expect(filterPapers(papers, { ...f, hBasis: "last", keepUnknownH: false }, { hindex }).map((p) => p.title)).toEqual([
      "MICCAI paper",
    ]);
  });

  it("ignore le filtre tant que les h-index ne sont pas chargés", () => {
    expect(filterPapers(papers, { ...emptyFilters(), hMin: 50, keepUnknownH: false }, { hindex: null })).toHaveLength(3);
  });

  it("trie par h-index, inconnus en dernier", () => {
    const byMax = sortPapers(papers, "hindex", ORDER, { hindex, basis: "max" }).map((p) => p.title);
    expect(byMax).toEqual(["Federated chest X-ray", "MICCAI paper", "LLM fine-tuning"]);
    const byLast = sortPapers(papers, "hindex", ORDER, { hindex, basis: "last" }).map((p) => p.title);
    expect(byLast).toEqual(["MICCAI paper", "Federated chest X-ray", "LLM fine-tuning"]);
  });
});

describe("pertinence (IA)", () => {
  const a = (score: number) => ({ resume_fr: "Résumé.", score, justification: "" });
  const analyses: AnalysisMap = { "Federated chest X-ray": a(5), "LLM fine-tuning": a(2), "MICCAI paper": null };

  it("filtre sur le score minimum", () => {
    const f = { ...emptyFilters(), scoreMin: 4 };
    expect(filterPapers(papers, f, { analyses }).map((p) => p.title)).toEqual(["Federated chest X-ray", "MICCAI paper"]);
    expect(filterPapers(papers, { ...f, keepUnscored: false }, { analyses })).toHaveLength(1);
  });

  it("trie par score, non analysés en dernier", () => {
    expect(sortPapers(papers, "score", ORDER, { analyses }).map((p) => p.title)).toEqual([
      "Federated chest X-ray", "LLM fine-tuning", "MICCAI paper",
    ]);
  });
});
