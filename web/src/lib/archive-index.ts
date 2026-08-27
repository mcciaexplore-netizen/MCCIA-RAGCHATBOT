import "server-only";
import type { NeonQueryFunction } from "@neondatabase/serverless";
import { getDb } from "@/lib/db";
import { formatIssueMonth } from "@/lib/format";
import type { BrowseIndex, BrowseIssue } from "@/lib/types";

type ArticleRow = {
  id: number;
  issueMonth: string;
  issueYear: number;
  articleTitle: string;
  sourceUrl: string | null;
};

/** Pure grouping of flat article rows into issues -- no network access, so
 * it's unit-testable directly. Rows are expected oldest-issue-first (see
 * the ORDER BY in getBrowseIndex), chronological 1945 onward; a Map
 * preserves that insertion order, so no separate sort is needed here.
 */
export function groupIntoIssues(rows: ArticleRow[]): BrowseIssue[] {
  const byMonth = new Map<string, BrowseIssue>();

  for (const row of rows) {
    let issue = byMonth.get(row.issueMonth);
    if (!issue) {
      issue = {
        year: row.issueYear,
        month: Number(row.issueMonth.split("-")[1]),
        issueMonth: row.issueMonth,
        label: formatIssueMonth(row.issueMonth),
        articles: [],
      };
      byMonth.set(row.issueMonth, issue);
    }
    issue.articles.push({
      id: row.id,
      title: row.articleTitle,
      sourceUrl: row.sourceUrl ?? "",
    });
  }

  return Array.from(byMonth.values());
}

/** Returns an empty index if nothing has been ingested yet, rather than
 * failing the whole browse page -- the archive is genuinely empty before
 * Phase 2 has run against real data.
 */
export async function getBrowseIndex(
  client?: NeonQueryFunction<false, false>
): Promise<BrowseIndex> {
  const sql = client ?? getDb();

  const rows = (await sql`
    select
      a.id,
      a.year::text || '-' || lpad(a.month::text, 2, '0') as "issueMonth",
      a.year as "issueYear",
      a.article_title as "articleTitle",
      a.source_url as "sourceUrl"
    from articles a
    order by a.year asc, a.month asc, a.article_index asc
  `) as ArticleRow[];

  return { issues: groupIntoIssues(rows) };
}
