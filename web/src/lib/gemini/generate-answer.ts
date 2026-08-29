import "server-only";
import type { GoogleGenAI } from "@google/genai";
import type { NeonQueryFunction } from "@neondatabase/serverless";
import { z } from "zod";
import { buildGeminiClient } from "@/lib/gemini/client";
import { embedQuery } from "@/lib/gemini/embed";
import { GEMINI_ANSWER_MODEL } from "@/lib/gemini/models";
import type { QueryRoute } from "@/lib/gemini/query-router";
import { formatIssueMonth } from "@/lib/format";
import { search, type SearchResult } from "@/lib/retrieval";
import type { ParsedCitation } from "@/lib/types";

export type AnswerResult = {
  answerEnglish: string;
  answerMarathi: string;
  citations: ParsedCitation[];
};

const NOT_FOUND_ANSWER_EN =
  "I could not find sufficient information about this in the currently indexed MCCI archive.";
const NOT_FOUND_ANSWER_MR =
  "सध्या अनुक्रमित केलेल्या MCCI संग्रहात याबद्दल पुरेशी माहिती मला सापडली नाही.";

// Below this blended relevance score (see retrieval.ts's INTENT_WEIGHTS),
// the best available evidence is judged too weak to answer from -- return
// the not-found message instead of letting Gemini's own judgment be the
// only thing standing between weak evidence and a confident-looking
// answer. This is a starting heuristic, not an empirically-tuned constant:
// picked from live-testing against the current ~1,500 indexed chunks (see
// the Phase 3 report), not derived from a large labeled evaluation set --
// revisit once more of the archive is indexed and real usage data exists.
const LOW_CONFIDENCE_SCORE_THRESHOLD = 0.35;

export const SYSTEM_PROMPT = `You are Sampada's research assistant. Sampada is MCCIA's monthly industrial magazine archive, spanning 70+ years of issues written in English, Marathi, and Hindi.

GROUNDING -- NON-NEGOTIABLE:
The excerpts below are the ONLY source of truth for historical facts. Never fill a gap from general or outside knowledge, even if you're confident about the answer.
- Never invent a date, person, company, article title, Sampada edition, page number, or citation that isn't shown in the excerpts below.
- PAGE NUMBERS ARE STRICT: an excerpt's label ends with ", Page N" only when that excerpt actually has a known page. If an excerpt's label has NO ", Page N" part, you MUST NOT include any page number for it anywhere in your answer -- not a guess, not one inferred from surrounding excerpts, not one assigned by assuming the articles run in page order. Omitting the page entirely is always correct when the label doesn't show one; inventing one is never acceptable.
- Use exactly the issue and article title labeled on each excerpt -- never guess or reconstruct one that isn't printed there.
- If different excerpts report different or conflicting information, do not silently pick one version -- say so explicitly and cite both.
- If the excerpts don't contain enough information to answer the question, say so plainly in both answer_en and answer_mr instead of guessing, and leave cited_excerpt_numbers empty.
- SEARCH USES SPELLING/SCRIPT VARIANTS, NOT FACTS: retrieval may have searched for alternate spellings or transliterations of a named entity (e.g. a Latin name alongside a Devanagari one) to find it regardless of which script the archive printed it in. That is a search mechanism only -- never state or imply that two differently-spelled or differently-scripted names refer to the same real person or company unless an excerpt itself says so.

Respond with JSON matching the given schema:
- answer_en: the answer in English.
- answer_mr: the same answer, independently written in Marathi (मराठी) -- not a literal word-for-word translation, but the same facts and citations.
- cited_excerpt_numbers: the numbers (from the "Excerpt N" labels below) of every excerpt actually used to answer -- leave empty if none were relevant.

CITATIONS: after every factual claim, cite it inline using exactly the excerpt's own label: (Sampada, <Month Year>, "<Article Title>"), or (Sampada, <Month Year>, "<Article Title>", Page <N>) only when that excerpt's label itself shows a page.

FORMAT: a simple, narrow factual question gets a direct answer -- 2-4 sentences, one flowing paragraph, no headers or bullets. A question asking for a summary, overview, or research synthesized across multiple excerpts/editions gets a structured answer instead: short headers "Direct Answer", "Key Findings" (a few bullet points), "Details" (only if genuinely useful), "Sources". Never force the structured format onto a narrow question, and never pad a direct answer with unnecessary length just because many excerpts were retrieved.`;

const ANSWER_JSON_SCHEMA = {
  type: "object",
  properties: {
    answer_en: { type: "string", description: "The answer in English." },
    answer_mr: { type: "string", description: "The same answer in Marathi." },
    cited_excerpt_numbers: {
      type: "array",
      items: { type: "integer" },
      description:
        "Excerpt numbers actually used to answer the question. Empty if none were relevant.",
    },
  },
  required: ["answer_en", "answer_mr", "cited_excerpt_numbers"],
};

const AnswerSchema = z.object({
  answer_en: z.string(),
  answer_mr: z.string(),
  cited_excerpt_numbers: z.array(z.number().int()).optional(),
});

/** Labels each chunk with its issue/article/page (if known) so the model
 * can attribute correctly -- pure string building, no network access. Page
 * is included only when the chunk actually has one; never fabricated for a
 * chunk indexed before page tracking existed (null issue_page_number).
 */
export function formatContext(chunks: SearchResult[]): string {
  return chunks
    .map((chunk, i) => {
      const pageSuffix = chunk.pageNumber != null ? `, Page ${chunk.pageNumber}` : "";
      const label = `Sampada, ${formatIssueMonth(chunk.issueMonth)}, "${chunk.articleTitle}"${pageSuffix}`;
      return `[Excerpt ${i + 1} -- ${label}]\n${chunk.content}`;
    })
    .join("\n\n");
}

/** A short, human-readable description of what kind of question this is,
 * appended to the model's input alongside the actual question -- reuses
 * the classification query-router.ts already did instead of asking Gemini
 * to re-infer "is this a summary question" a second time from phrasing
 * alone, so the two stay consistent with each other.
 */
export function describeQuestionType(route: QueryRoute): string {
  const scopeNote =
    route.scope === "issue"
      ? ` about the ${formatIssueMonth(route.issueMonth)} issue`
      : route.scope === "range"
        ? ` spanning ${route.yearFrom}-${route.yearTo}`
        : "";
  return `Classified as a ${route.intent} question${scopeNote}.`;
}

// Matches one citation's "Sampada, <Month Year>, "<Article Title>"" core,
// with an optional trailing page clause -- deliberately NOT anchored to a
// fully self-contained "(...)" wrapper, and deliberately broad about what
// counts as a page clause. Live testing surfaced three distinct ways the
// model fabricated a page despite the prompt saying not to: a single
// number ("Page 17"), a range ("Page 17-18"), several citations combined
// into one parenthetical joined by "; " (invisible to a per-parenthetical
// regex), and finally a bare trailing number with the word "Page" dropped
// entirely (`"...", 16)`). The trailing group below makes the word "Page"
// itself optional so all four are caught by one pattern; the title match
// is deliberately permissive (anything but a quote, including Devanagari)
// since it's only used to look up whether that specific excerpt has a
// real page -- never re-interpreted as a regex.
const CITATION_RE = /Sampada, ([^,]+), (“[^”]+”|"[^"]+")(,\s*(?:Page\s*)?\d[\d\s–—-]*)?/g;

/** Deterministic safety net, not a substitute for the prompt instruction:
 * live testing showed the prompt's "never invent a page number" rule is
 * NOT reliably followed -- a strengthened prompt reduced but did not
 * eliminate fabricated page numbers (including page *ranges*, e.g.
 * "Page 17-18") in free-text answers, even though buildCitations()'s
 * structured output was always correct. This strips any "Page ..." clause
 * from an inline citation whose (month/year, title) pair corresponds to a
 * retrieved excerpt with no real page number, regardless of what the model
 * wrote -- ground truth comes from `chunks`, never from re-trusting the
 * model's own text.
 */
export function stripFabricatedPageNumbers(answerText: string, chunks: SearchResult[]): string {
  const noPageKeys = new Set(
    chunks
      .filter((c) => c.pageNumber == null)
      .map((c) => `${formatIssueMonth(c.issueMonth)}|${c.articleTitle}`)
  );

  return answerText.replace(CITATION_RE, (match, monthYear, quotedTitle, pageClause) => {
    if (!pageClause) return match; // no page mentioned at all -- nothing to strip
    const title = quotedTitle.slice(1, -1); // strip the surrounding quote marks
    const key = `${monthYear.trim()}|${title}`;
    if (!noPageKeys.has(key)) return match; // this excerpt genuinely has a page -- leave it
    return `Sampada, ${monthYear}, ${quotedTitle}`;
  });
}

/** Built from the SQL rows for the excerpts Gemini says it actually used
 * (`citedExcerptNumbers`, 1-indexed to match `formatContext`'s labels) --
 * never from every retrieved chunk, since pgvector always returns its
 * nearest neighbors even when none of them are actually relevant. Deduped,
 * since several chunks from the same article commonly land in one result
 * set. Page/pdfPageOffset come straight from the retrieved row -- never
 * invented, and null when the underlying chunk predates page tracking.
 */
export function buildCitations(
  chunks: SearchResult[],
  citedExcerptNumbers: number[] = []
): ParsedCitation[] {
  const cited = new Set(citedExcerptNumbers);
  const seen = new Set<number>();
  const citations: ParsedCitation[] = [];

  chunks.forEach((chunk, i) => {
    if (!cited.has(i + 1)) return;
    if (seen.has(chunk.articleId)) return;
    seen.add(chunk.articleId);
    citations.push({
      articleId: chunk.articleId,
      articleTitle: chunk.articleTitle,
      issueMonth: chunk.issueMonth,
      sourceUrl: chunk.sourceUrl ?? "",
      page: chunk.pageNumber,
      pdfPageOffset: chunk.pdfPageOffset,
    });
  });

  return citations;
}

/** Pure parsing of the model's raw JSON text -- no network access, so this
 * is unit-testable without a live Gemini call.
 */
export function parseAnswer(
  outputText: string | undefined,
  chunks: SearchResult[]
): AnswerResult {
  if (!outputText) {
    throw new Error("Gemini response had no output text");
  }

  const parsed = AnswerSchema.parse(JSON.parse(outputText));

  return {
    answerEnglish: stripFabricatedPageNumbers(parsed.answer_en, chunks),
    answerMarathi: stripFabricatedPageNumbers(parsed.answer_mr, chunks),
    citations: buildCitations(chunks, parsed.cited_excerpt_numbers ?? []),
  };
}

/** True when the best retrieved evidence is too weak to answer from --
 * checked before ever calling Gemini, so a low-confidence result can't
 * depend solely on the model choosing to say so in its own prose.
 */
export function isLowConfidence(chunks: SearchResult[]): boolean {
  if (chunks.length === 0) return true;
  const bestScore = Math.max(...chunks.map((c) => c.score));
  return bestScore < LOW_CONFIDENCE_SCORE_THRESHOLD;
}

export async function generateAnswer(
  question: string,
  route: QueryRoute,
  opts?: {
    client?: GoogleGenAI;
    limit?: number;
    dbClient?: NeonQueryFunction<false, false>;
    // Lets the caller compute this concurrently with classifyQuery (they're
    // independent) instead of paying for that round trip serially on top of
    // this one -- see route.ts.
    embedding?: number[];
  }
): Promise<AnswerResult> {
  const client = opts?.client ?? buildGeminiClient();

  const embedding = opts?.embedding ?? (await embedQuery(question, { client }));
  const chunks = await search(question, embedding, route, { limit: opts?.limit, client: opts?.dbClient });

  if (isLowConfidence(chunks)) {
    return { answerEnglish: NOT_FOUND_ANSWER_EN, answerMarathi: NOT_FOUND_ANSWER_MR, citations: [] };
  }

  const interaction = await client.interactions.create({
    model: GEMINI_ANSWER_MODEL,
    system_instruction: SYSTEM_PROMPT,
    input: `${formatContext(chunks)}\n\nQuestion: ${question}\n\n${describeQuestionType(route)}`,
    response_format: {
      type: "text",
      mime_type: "application/json",
      schema: ANSWER_JSON_SCHEMA,
    },
    // gemini-3.7-flash thinks by default, which measurably adds latency on
    // every chat request for little benefit here -- the task is bounded
    // (answer strictly from the given excerpts, cite by excerpt number),
    // not open-ended reasoning. "low" trims that overhead while still
    // leaving some budget for getting excerpt numbers right.
    generation_config: { thinking_level: "low" },
  });

  return parseAnswer(interaction.output_text, chunks);
}
