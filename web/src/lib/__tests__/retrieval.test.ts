import type { NeonQueryFunction } from "@neondatabase/serverless";
import { describe, expect, it } from "vitest";
import { search, type SearchResult } from "../retrieval";

const SAMPLE_ROW: SearchResult = {
  articleId: 1,
  content: "MCCIA ran robotics workshops across Pune.",
  issueMonth: "2021-06",
  articleTitle: "Robotics for Everyone",
  sourceUrl: "https://www.mcciapunesampada.com/p/sampada-june-2021.html",
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
  it("returns rows as-is for an open-scope query", async () => {
    const { sql } = fakeSql([SAMPLE_ROW]);
    const results = await search([0.1, 0.2, 0.3], { scope: "open" }, { client: sql });
    expect(results).toEqual([SAMPLE_ROW]);
  });

  it("does not filter by year/month for an open-scope query", async () => {
    const { sql, calls } = fakeSql([SAMPLE_ROW]);
    await search([0.1], { scope: "open" }, { client: sql });
    expect(calls[0].text).not.toContain("where c.year");
  });

  it("filters by numeric year and month for an issue-scoped query", async () => {
    const { sql, calls } = fakeSql([SAMPLE_ROW]);
    await search([0.1], { scope: "issue", issueMonth: "2021-06" }, { client: sql });
    expect(calls[0].text).toContain("where c.year = ? and c.month = ?");
    expect(calls[0].values).toContain(2021);
    expect(calls[0].values).toContain(6);
  });

  it("formats the embedding as a bracketed vector literal", async () => {
    const { sql, calls } = fakeSql([]);
    await search([0.1, 0.25, -0.5], { scope: "open" }, { client: sql });
    expect(calls[0].values).toContain("[0.1,0.25,-0.5]");
  });

  it("joins smaller chunks by the complete article coordinate", async () => {
    const { sql, calls } = fakeSql([]);
    await search([0.1], { scope: "open" }, { client: sql });
    expect(calls[0].text).toContain("from smaller_chunks c");
    expect(calls[0].text).toContain("a.year = c.year");
    expect(calls[0].text).toContain("a.month = c.month");
    expect(calls[0].text).toContain("a.article_index = c.article_index");
    expect(calls[0].text).toContain('"articleId"');
    expect(calls[0].text).toContain('"issueMonth"');
    expect(calls[0].text).toContain('"articleTitle"');
  });

  it("defaults to a limit of 10 (within the spec's 8-12 range)", async () => {
    const { sql, calls } = fakeSql([]);
    await search([0.1], { scope: "open" }, { client: sql });
    expect(calls[0].values).toContain(10);
  });

  it("honors a caller-supplied limit", async () => {
    const { sql, calls } = fakeSql([]);
    await search([0.1], { scope: "open" }, { client: sql, limit: 8 });
    expect(calls[0].values).toContain(8);
  });
});
