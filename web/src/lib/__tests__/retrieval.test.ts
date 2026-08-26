import type { NeonQueryFunction } from "@neondatabase/serverless";
import { describe, expect, it } from "vitest";
import { search, type SearchResult } from "../retrieval";

const SAMPLE_ROW: SearchResult = {
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

  it("does not filter by issue_month for an open-scope query", async () => {
    const { sql, calls } = fakeSql([SAMPLE_ROW]);
    await search([0.1], { scope: "open" }, { client: sql });
    expect(calls[0].text).not.toContain("where a.issue_month");
  });

  it("filters by issue_month for an issue-scoped query", async () => {
    const { sql, calls } = fakeSql([SAMPLE_ROW]);
    await search([0.1], { scope: "issue", issueMonth: "2021-06" }, { client: sql });
    expect(calls[0].text).toContain("where a.issue_month");
    expect(calls[0].values).toContain("2021-06");
  });

  it("formats the embedding as a bracketed vector literal", async () => {
    const { sql, calls } = fakeSql([]);
    await search([0.1, 0.25, -0.5], { scope: "open" }, { client: sql });
    expect(calls[0].values).toContain("[0.1,0.25,-0.5]");
  });

  it("joins chunks to articles so every row carries issue_month and article_title", async () => {
    const { sql, calls } = fakeSql([]);
    await search([0.1], { scope: "open" }, { client: sql });
    expect(calls[0].text).toContain("join articles a on a.id = c.article_id");
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
