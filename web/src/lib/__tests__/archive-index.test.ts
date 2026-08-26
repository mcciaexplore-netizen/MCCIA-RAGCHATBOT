import type { NeonQueryFunction } from "@neondatabase/serverless";
import { describe, expect, it } from "vitest";
import { getBrowseIndex, groupIntoIssues } from "../archive-index";

function fakeSql(rows: unknown[]) {
  const fn = () => Promise.resolve(rows);
  return fn as unknown as NeonQueryFunction<false, false>;
}

describe("groupIntoIssues", () => {
  it("groups articles by issue_month into issues", () => {
    const issues = groupIntoIssues([
      { id: 1, issueMonth: "2021-06", issueYear: 2021, articleTitle: "Editorial", sourceUrl: "" },
      {
        id: 2,
        issueMonth: "2021-06",
        issueYear: 2021,
        articleTitle: "Women in Robotics",
        sourceUrl: "https://example.com/a",
      },
      { id: 3, issueMonth: "2020-05", issueYear: 2020, articleTitle: "COVID Relief", sourceUrl: null },
    ]);

    expect(issues).toEqual([
      {
        year: 2021,
        month: 6,
        issueMonth: "2021-06",
        label: "June 2021",
        articles: [
          { id: 1, title: "Editorial", sourceUrl: "" },
          { id: 2, title: "Women in Robotics", sourceUrl: "https://example.com/a" },
        ],
      },
      {
        year: 2020,
        month: 5,
        issueMonth: "2020-05",
        label: "May 2020",
        articles: [{ id: 3, title: "COVID Relief", sourceUrl: "" }],
      },
    ]);
  });

  it("preserves row order across issues (newest first, per the SQL's ORDER BY)", () => {
    const issues = groupIntoIssues([
      { id: 1, issueMonth: "2021-07", issueYear: 2021, articleTitle: "July piece", sourceUrl: null },
      { id: 2, issueMonth: "2021-06", issueYear: 2021, articleTitle: "June piece", sourceUrl: null },
    ]);
    expect(issues.map((i) => i.issueMonth)).toEqual(["2021-07", "2021-06"]);
  });

  it("returns an empty array for no rows", () => {
    expect(groupIntoIssues([])).toEqual([]);
  });

  it("defaults a null source_url to an empty string", () => {
    const issues = groupIntoIssues([
      { id: 1, issueMonth: "2021-06", issueYear: 2021, articleTitle: "Editorial", sourceUrl: null },
    ]);
    expect(issues[0].articles[0].sourceUrl).toBe("");
  });
});

describe("getBrowseIndex", () => {
  it("queries articles and groups the result", async () => {
    const sql = fakeSql([
      { id: 1, issueMonth: "2021-06", issueYear: 2021, articleTitle: "Editorial", sourceUrl: "" },
    ]);

    const index = await getBrowseIndex(sql);

    expect(index.issues).toEqual([
      {
        year: 2021,
        month: 6,
        issueMonth: "2021-06",
        label: "June 2021",
        articles: [{ id: 1, title: "Editorial", sourceUrl: "" }],
      },
    ]);
  });

  it("returns an empty index when nothing has been ingested yet", async () => {
    const index = await getBrowseIndex(fakeSql([]));
    expect(index).toEqual({ issues: [] });
  });
});
