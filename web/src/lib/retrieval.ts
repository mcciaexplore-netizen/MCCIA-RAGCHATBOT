import "server-only";
import type { NeonQueryFunction } from "@neondatabase/serverless";
import { getDb, toVectorLiteral } from "@/lib/db";
import type { QueryIntent, QueryRoute } from "@/lib/gemini/query-router";

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
  // Issue-relative page number (smaller_chunks.issue_page_number) -- null
  // for anything indexed before page tracking existed (see db/proposed_01).
  // Never fabricated: a null here must never become a made-up page number
  // downstream, only "no page available for this excerpt."
  pageNumber: number | null;
  // Physical PDF page offset for this excerpt's issue (sampada.pdf_page_offset)
  // -- not shown to users yet (no source viewer this phase), kept so a
  // future "open page N" feature doesn't need another retrieval change.
  pdfPageOffset: number | null;
  // The blended full-text + vector relevance score this row was ranked by
  // (see INTENT_WEIGHTS below) -- exposed so callers (generate-answer.ts's
  // low-confidence check) can judge evidence strength without re-deriving it.
  score: number;
};

const DEFAULT_LIMIT = 10; // spec: "top 8 to 12 results"

// Hybrid scoring weights per intent -- how much a chunk's rank should come
// from full-text/keyword relevance (ts_rank_cd) vs semantic similarity
// (1 - cosine distance). Deliberately simple additive blend, not a
// rigorously tuned formula: "exact" leans hard on keyword match (a name
// search shouldn't be out-ranked by a vaguely-related paraphrase), "semantic"
// leans hard on vector similarity, "summary" balances both since a broad
// question benefits from both keyword and thematic recall.
const INTENT_WEIGHTS: Record<QueryIntent, { vector: number; fts: number }> = {
  exact: { vector: 0.2, fts: 0.8 },
  semantic: { vector: 0.8, fts: 0.2 },
  summary: { vector: 0.6, fts: 0.4 },
};

// A "summary" question (e.g. "summarize Sampada July 1956") needs evidence
// spread across the edition, not just the top-K nearest isolated chunks --
// pull more candidates, then cap how many of them can come from one
// article, then trim back to a final bound so the answer prompt doesn't
// balloon in size.
const SUMMARY_CANDIDATE_LIMIT = 30;
const SUMMARY_MAX_PER_ARTICLE = 3;
const SUMMARY_FINAL_LIMIT = 20;

function capPerArticle(rows: SearchResult[], maxPerArticle: number): SearchResult[] {
  const counts = new Map<number, number>();
  const capped: SearchResult[] = [];
  for (const row of rows) {
    const count = counts.get(row.articleId) ?? 0;
    if (count >= maxPerArticle) continue;
    counts.set(row.articleId, count + 1);
    capped.push(row);
  }
  return capped;
}

/** One query for every scope: the metadata filter is expressed as
 * null-coalescing bind-parameter conditions ("$param is null or ...")
 * rather than three separately-templated queries, so there's exactly one
 * SQL statement to keep correct instead of three that can drift apart.
 * Combines that metadata filter with a weighted blend of PostgreSQL
 * full-text rank (content_tsv, see db/proposed_03) and pgvector cosine
 * similarity -- never vector similarity alone, so an exact name/date match
 * can't be out-ranked by a merely-related paraphrase (see query-router.ts's
 * QueryIntent weights above).
 */
export async function search(
  question: string,
  embedding: number[],
  route: QueryRoute,
  opts?: { limit?: number; client?: NeonQueryFunction<false, false> }
): Promise<SearchResult[]> {
  const sql = opts?.client ?? getDb();
  const vector = toVectorLiteral(embedding);
  const weights = INTENT_WEIGHTS[route.intent];

  const issueYear = route.scope === "issue" ? Number(route.issueMonth.split("-")[0]) : null;
  const issueMonth = route.scope === "issue" ? Number(route.issueMonth.split("-")[1]) : null;
  const yearFrom = route.scope === "range" ? route.yearFrom : null;
  const yearTo = route.scope === "range" ? route.yearTo : null;

  const isSummary = route.intent === "summary";
  const candidateLimit = isSummary ? SUMMARY_CANDIDATE_LIMIT : opts?.limit ?? DEFAULT_LIMIT;

  // Alias/transliteration variants from query-router.ts's classification
  // (e.g. "Ogale" -> ["Ogale", "Ogle", "ओगले"]) -- search expansion only,
  // never a claim that the variants are the same real-world entity (see
  // generate-answer.ts's grounding prompt). Falls back to the raw question
  // alone when no variants were classified, which ranks identically to the
  // single-term behavior this replaces.
  const ftsTerms = route.searchTerms && route.searchTerms.length > 0 ? route.searchTerms : [question];

  const rows = await sql`
    select
      a.id as "articleId",
      c.content,
      a.year::text || '-' || lpad(a.month::text, 2, '0') as "issueMonth",
      a.article_title as "articleTitle",
      a.source_url as "sourceUrl",
      c.issue_page_number as "pageNumber",
      s.pdf_page_offset as "pdfPageOffset",
      (
        ${weights.vector}::float * (1 - (c.embedding <=> ${vector}::vector)) +
        ${weights.fts}::float * coalesce(
          (
            select max(ts_rank_cd(c.content_tsv, websearch_to_tsquery('simple', term)))
            from unnest(${ftsTerms}::text[]) as term
          ),
          0
        )
      ) as score
    from smaller_chunks c
    join articles a
      on a.year = c.year
     and a.month = c.month
     and a.article_index = c.article_index
    join sampada s
      on s.year = a.year
     and s.month = a.month
    where
      (${issueYear}::int is null or a.year = ${issueYear})
      and (${issueMonth}::int is null or a.month = ${issueMonth})
      and (${yearFrom}::int is null or a.year >= ${yearFrom})
      and (${yearTo}::int is null or a.year <= ${yearTo})
    order by score desc
    limit ${candidateLimit}
  `;

  const results = rows as SearchResult[];
  if (!isSummary) return results;

  return capPerArticle(results, SUMMARY_MAX_PER_ARTICLE).slice(0, SUMMARY_FINAL_LIMIT);
}
