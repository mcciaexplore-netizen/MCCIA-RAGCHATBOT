import type { NeonQueryFunction } from "@neondatabase/serverless";
import { describe, expect, it } from "vitest";
import { search, type SearchResult } from "../retrieval";

const SAMPLE_ROW: SearchResult = {
  articleId: 1,
  content: "MCCIA ran robotics workshops across Pune.",
  issueMonth: "2021-06",
  articleTitle: "Robotics for Everyone",
  sourceUrl: "https://www.mcciapunesampada.com/p/sampada-june-2021.html",
  pageNumber: 12,
  pdfPageOffset: 4,
  score: 0.9,
};

function fakeSql(rows: SearchResult[]) {
  const calls: { text: string; values: unknown[] }[] = [];
  const fn = (strings: TemplateStringsArray, ...values: unknown[]) => {
    calls.push({ text: strings.join("?"), values });
    return Promise.resolve(rows);
  };
  return { sql: fn as unknown as NeonQueryFunction<false, false>, calls };
}

describe("search", () => {
  it("returns rows as-is for an open-scope, non-summary query", async () => {
    const { sql } = fakeSql([SAMPLE_ROW]);
    const results = await search("robotics", [0.1, 0.2, 0.3], { scope: "open", intent: "semantic" }, { client: sql });
    expect(results).toEqual([SAMPLE_ROW]);
  });

  it("does not filter by year/month for an open-scope query (all bind params null)", async () => {
    const { sql, calls } = fakeSql([SAMPLE_ROW]);
    await search("robotics", [0.1], { scope: "open", intent: "semantic" }, { client: sql });
    // all four metadata params are null for "open" -- each appears twice
    // (once in the "is null" check, once in the equality/comparison) --
    // the null-coalescing "is null or ..." conditions make every row pass.
    expect(calls[0].values.filter((v) => v === null)).toHaveLength(8);
  });

  it("filters by numeric year and month for an issue-scoped query", async () => {
    const { sql, calls } = fakeSql([SAMPLE_ROW]);
    await search("robotics", [0.1], { scope: "issue", issueMonth: "2021-06", intent: "semantic" }, { client: sql });
    expect(calls[0].values).toContain(2021);
    expect(calls[0].values).toContain(6);
  });

  it("filters by a year range for a range-scoped query", async () => {
    const { sql, calls } = fakeSql([SAMPLE_ROW]);
    await search("Tata", [0.1], { scope: "range", yearFrom: 1955, yearTo: 1965, intent: "semantic" }, { client: sql });
    expect(calls[0].values).toContain(1955);
    expect(calls[0].values).toContain(1965);
    // range scope doesn't set an exact issue year/month -- those two params
    // are null, each appearing twice (is-null check + comparison)
    expect(calls[0].values.filter((v) => v === null)).toHaveLength(4);
  });

  it("passes the raw question text through for full-text ranking when no alias terms were classified", async () => {
    const { sql, calls } = fakeSql([SAMPLE_ROW]);
    await search("exact mentions of Kirloskar", [0.1], { scope: "open", intent: "exact" }, { client: sql });
    expect(calls[0].values).toContainEqual(["exact mentions of Kirloskar"]);
  });

  it("expands full-text search across classified alias/transliteration terms", async () => {
    const { sql, calls } = fakeSql([SAMPLE_ROW]);
    await search(
      "Find Ogale",
      [0.1],
      { scope: "open", intent: "exact", searchTerms: ["Ogale", "Ogle", "ओगले"] },
      { client: sql }
    );
    expect(calls[0].values).toContainEqual(["Ogale", "Ogle", "ओगले"]);
    expect(calls[0].text).toContain("unnest");
  });

  it("formats the embedding as a bracketed vector literal", async () => {
    const { sql, calls } = fakeSql([]);
    await search("q", [0.1, 0.25, -0.5], { scope: "open", intent: "semantic" }, { client: sql });
    expect(calls[0].values).toContain("[0.1,0.25,-0.5]");
  });

  it("joins smaller_chunks, articles, and sampada, selecting page metadata", async () => {
    const { sql, calls } = fakeSql([]);
    await search("q", [0.1], { scope: "open", intent: "semantic" }, { client: sql });
    expect(calls[0].text).toContain("from smaller_chunks c");
    expect(calls[0].text).toContain("join articles a");
    expect(calls[0].text).toContain("join sampada s");
    expect(calls[0].text).toContain("a.year = c.year");
    expect(calls[0].text).toContain("a.month = c.month");
    expect(calls[0].text).toContain("a.article_index = c.article_index");
    expect(calls[0].text).toContain('"articleId"');
    expect(calls[0].text).toContain('"issueMonth"');
    expect(calls[0].text).toContain('"articleTitle"');
    expect(calls[0].text).toContain('"pageNumber"');
    expect(calls[0].text).toContain('"pdfPageOffset"');
  });

  it("blends full-text rank and vector similarity in the score", async () => {
    const { sql, calls } = fakeSql([]);
    await search("q", [0.1], { scope: "open", intent: "semantic" }, { client: sql });
    expect(calls[0].text).toContain("ts_rank_cd");
    expect(calls[0].text).toContain("websearch_to_tsquery");
    expect(calls[0].text).toContain("<=>");
    expect(calls[0].text).toContain("as score");
    expect(calls[0].text).toContain("order by score desc");
  });

  it("weights full-text much more heavily than vector similarity for exact intent", async () => {
    const { sql, calls } = fakeSql([]);
    await search("Kirloskar", [0.1], { scope: "open", intent: "exact" }, { client: sql });
    expect(calls[0].values).toContain(0.8); // fts weight
    expect(calls[0].values).toContain(0.2); // vector weight
  });

  it("weights vector similarity much more heavily than full-text for semantic intent", async () => {
    const { sql, calls } = fakeSql([]);
    await search("what did MCCI think about exports", [0.1], { scope: "open", intent: "semantic" }, { client: sql });
    expect(calls[0].values).toContain(0.8); // vector weight
    expect(calls[0].values).toContain(0.2); // fts weight
  });

  it("defaults to a limit of 10 (within the spec's 8-12 range) for non-summary intents", async () => {
    const { sql, calls } = fakeSql([]);
    await search("q", [0.1], { scope: "open", intent: "semantic" }, { client: sql });
    expect(calls[0].values).toContain(10);
  });

  it("honors a caller-supplied limit for non-summary intents", async () => {
    const { sql, calls } = fakeSql([]);
    await search("q", [0.1], { scope: "open", intent: "semantic" }, { client: sql, limit: 8 });
    expect(calls[0].values).toContain(8);
  });

  it("requests a larger candidate pool for summary intent regardless of caller limit", async () => {
    const { sql, calls } = fakeSql([]);
    await search("summarize the July 1956 issue", [0.1], { scope: "issue", issueMonth: "1956-07", intent: "summary" }, {
      client: sql,
      limit: 8,
    });
    expect(calls[0].values).toContain(30);
    expect(calls[0].values).not.toContain(8);
  });

  it("caps chunks per article and trims to a final limit for summary intent", async () => {
    const manyFromOneArticle: SearchResult[] = Array.from({ length: 10 }, (_, i) => ({
      ...SAMPLE_ROW,
      articleId: 1,
      content: `chunk ${i}`,
    }));
    const fewFromAnother: SearchResult[] = Array.from({ length: 5 }, (_, i) => ({
      ...SAMPLE_ROW,
      articleId: 2,
      content: `other chunk ${i}`,
    }));
    const { sql } = fakeSql([...manyFromOneArticle, ...fewFromAnother]);

    const results = await search(
      "summarize the July 1956 issue",
      [0.1],
      { scope: "issue", issueMonth: "1956-07", intent: "summary" },
      { client: sql }
    );

    const fromArticleOne = results.filter((r) => r.articleId === 1);
    const fromArticleTwo = results.filter((r) => r.articleId === 2);
    expect(fromArticleOne.length).toBeLessThanOrEqual(3);
    expect(fromArticleTwo.length).toBeLessThanOrEqual(3);
    expect(results.length).toBeLessThanOrEqual(20);
  });

  it("does not diversity-cap non-summary intents even if all results share one article", async () => {
    const allSameArticle: SearchResult[] = Array.from({ length: 10 }, (_, i) => ({
      ...SAMPLE_ROW,
      articleId: 1,
      content: `chunk ${i}`,
    }));
    const { sql } = fakeSql(allSameArticle);

    const results = await search("q", [0.1], { scope: "open", intent: "semantic" }, { client: sql });

    expect(results).toHaveLength(10); // untouched -- one article can genuinely be the only relevant evidence
  });

  it("preserves null page metadata rather than fabricating it", async () => {
    const legacyRow: SearchResult = { ...SAMPLE_ROW, pageNumber: null, pdfPageOffset: null };
    const { sql } = fakeSql([legacyRow]);
    const results = await search("q", [0.1], { scope: "open", intent: "semantic" }, { client: sql });
    expect(results[0].pageNumber).toBeNull();
    expect(results[0].pdfPageOffset).toBeNull();
  });
});
