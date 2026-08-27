import "server-only";
import type { NeonQueryFunction } from "@neondatabase/serverless";
import { getDb } from "@/lib/db";

// The third piece of the migration note's "embed, search, fetch article"
// interface (embed lives in gemini/embed.ts, search in retrieval.ts).

export type Article = {
  id: number;
  issueMonth: string;
  issueYear: number;
  articleTitle: string;
  author: string | null;
  body: string;
  sourceUrl: string | null;
};

/** Powers the transcription page (archive/[id]) and, indirectly, every
 * citation tag -- every article gets one of these regardless of whether it
 * has an external source_url, which most pre-2021 issues don't.
 */
export async function fetchArticle(
  id: number,
  client?: NeonQueryFunction<false, false>
): Promise<Article | null> {
  const sql = client ?? getDb();

  const rows = (await sql`
    select
      id,
      year::text || '-' || lpad(month::text, 2, '0') as "issueMonth",
      year as "issueYear",
      article_title as "articleTitle",
      author,
      body,
      source_url as "sourceUrl"
    from articles
    where id = ${id}
  `) as Article[];

  return rows[0] ?? null;
}
