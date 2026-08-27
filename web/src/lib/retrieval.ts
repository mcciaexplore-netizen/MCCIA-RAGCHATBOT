import "server-only";
import type { NeonQueryFunction } from "@neondatabase/serverless";
import { getDb, toVectorLiteral } from "@/lib/db";
import type { QueryRoute } from "@/lib/gemini/query-router";

// The migration note in the build spec asks for the retrieval layer to sit
// behind a single module (embed, search, fetch article) so swapping Neon
// pgvector for Aurora pgvector or a Bedrock Knowledge Base later is
// contained here rather than scattered through the app. `embed()` lives in
// Phase 4 (it's the first step of answer generation); this is `search()`.

export type SearchResult = {
  articleId: number;
  content: string;
  issueMonth: string;
  articleTitle: string;
  sourceUrl: string | null;
};

const DEFAULT_LIMIT = 10; // spec: "top 8 to 12 results"

/** Same SQL query with an optional WHERE clause (Phase 3): issue-scoped
 * questions filter to that numeric year/month, open questions search everything.
 * Both join smaller_chunks to articles so every result carries its issue_month and
 * article_title for citations.
 */
export async function search(
  embedding: number[],
  route: QueryRoute,
  opts?: { limit?: number; client?: NeonQueryFunction<false, false> }
): Promise<SearchResult[]> {
  const limit = opts?.limit ?? DEFAULT_LIMIT;
  const sql = opts?.client ?? getDb();
  const vector = toVectorLiteral(embedding);
  const [issueYear, issueMonth] =
    route.scope === "issue" ? route.issueMonth.split("-").map(Number) : [0, 0];

  const rows =
    route.scope === "issue"
      ? await sql`
          select
            a.id as "articleId",
            c.content,
            a.year::text || '-' || lpad(a.month::text, 2, '0') as "issueMonth",
            a.article_title as "articleTitle",
            a.source_url as "sourceUrl"
          from smaller_chunks c
          join articles a
            on a.year = c.year
           and a.month = c.month
           and a.article_index = c.article_index
          where c.year = ${issueYear} and c.month = ${issueMonth}
          order by c.embedding <=> ${vector}::vector
          limit ${limit}
        `
      : await sql`
          select
            a.id as "articleId",
            c.content,
            a.year::text || '-' || lpad(a.month::text, 2, '0') as "issueMonth",
            a.article_title as "articleTitle",
            a.source_url as "sourceUrl"
          from smaller_chunks c
          join articles a
            on a.year = c.year
           and a.month = c.month
           and a.article_index = c.article_index
          order by c.embedding <=> ${vector}::vector
          limit ${limit}
        `;

  return rows as SearchResult[];
}
