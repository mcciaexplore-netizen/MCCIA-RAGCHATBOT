import type { NeonQueryFunction } from "@neondatabase/serverless";
import { describe, expect, it } from "vitest";
import { fetchArticle, type Article } from "../article";

function fakeSql(rows: Article[]) {
  const calls: unknown[][] = [];
  const fn = (_strings: TemplateStringsArray, ...values: unknown[]) => {
    calls.push(values);
    return Promise.resolve(rows);
  };
  return { sql: fn as unknown as NeonQueryFunction<false, false>, calls };
}

const EDITORIAL: Article = {
  id: 1,
  issueMonth: "2021-06",
  issueYear: 2021,
  articleTitle: "Editorial",
  author: "The Editor",
  body: "Welcome to this special issue on robotics.",
  sourceUrl: "https://www.mcciapunesampada.com/p/sampada-june-2021.html",
};

describe("fetchArticle", () => {
  it("returns the article when found", async () => {
    const { sql } = fakeSql([EDITORIAL]);
    const article = await fetchArticle(1, sql);
    expect(article).toEqual(EDITORIAL);
  });

  it("returns null when no article matches the id", async () => {
    const { sql } = fakeSql([]);
    const article = await fetchArticle(9999, sql);
    expect(article).toBeNull();
  });

  it("queries by the given id", async () => {
    const { sql, calls } = fakeSql([]);
    await fetchArticle(42, sql);
    expect(calls[0]).toContain(42);
  });
});
