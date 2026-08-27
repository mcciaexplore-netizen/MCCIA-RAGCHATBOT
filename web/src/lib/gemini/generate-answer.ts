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
  "I couldn't find anything in the Sampada archive about that.";
const NOT_FOUND_ANSWER_MR =
  "मला संपदाच्या संग्रहात याबाबत काहीही सापडले नाही.";

export const SYSTEM_PROMPT = `You are Sampada's research assistant. Sampada is MCCIA's monthly industrial magazine archive, spanning 70+ years of issues written in English, Marathi, and Hindi.

Answer strictly from the excerpts below. Never fill gaps from general or outside knowledge, even if you're confident about the answer.

Respond with JSON matching the given schema:
- answer_en: the answer in English.
- answer_mr: the same answer, independently written in Marathi (मराठी) -- not a literal word-for-word translation, but the same facts and citations.
- cited_excerpt_numbers: the numbers (from the "Excerpt N" labels below) of every excerpt actually used to answer -- leave empty if none were relevant.

Rules:
- If the excerpts span multiple issues, synthesize across them and say which issue each fact comes from.
- After every factual claim, cite it inline as: (Sampada, <Month Year>, "<Article Title>") -- in answer_mr, keep the "Sampada" label and article title as printed, but the surrounding sentence in Marathi. Use exactly the issue and title labeled on each excerpt below -- never invent a date or title that isn't shown there.
- If the excerpts don't contain enough information to answer the question, say so plainly in both answer_en and answer_mr instead of guessing, and leave cited_excerpt_numbers empty.
- Keep your answer concise. Only go into more depth if the user explicitly asks for it.`;

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

/** Labels each chunk with its issue/article (Phase 4 step 2) so the model
 * can attribute correctly -- pure string building, no network access.
 */
export function formatContext(chunks: SearchResult[]): string {
  return chunks
    .map((chunk, i) => {
      const label = `Sampada, ${formatIssueMonth(chunk.issueMonth)}, "${chunk.articleTitle}"`;
      return `[Excerpt ${i + 1} -- ${label}]\n${chunk.content}`;
    })
    .join("\n\n");
}

/** Built from the SQL rows for the excerpts Gemini says it actually used
 * (`citedExcerptNumbers`, 1-indexed to match `formatContext`'s labels) --
 * never from every retrieved chunk, since pgvector always returns its
 * nearest neighbors even when none of them are actually relevant. Deduped,
 * since several chunks from the same article commonly land in one result
 * set.
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
    answerEnglish: parsed.answer_en,
    answerMarathi: parsed.answer_mr,
    citations: buildCitations(chunks, parsed.cited_excerpt_numbers ?? []),
  };
}

export async function generateAnswer(
  question: string,
  route: QueryRoute,
  opts?: {
    client?: GoogleGenAI;
    limit?: number;
    dbClient?: NeonQueryFunction<false, false>;
  }
): Promise<AnswerResult> {
  const client = opts?.client ?? buildGeminiClient();

  const embedding = await embedQuery(question, { client });
  const chunks = await search(embedding, route, { limit: opts?.limit, client: opts?.dbClient });

  if (chunks.length === 0) {
    return { answerEnglish: NOT_FOUND_ANSWER_EN, answerMarathi: NOT_FOUND_ANSWER_MR, citations: [] };
  }

  const interaction = await client.interactions.create({
    model: GEMINI_ANSWER_MODEL,
    system_instruction: SYSTEM_PROMPT,
    input: `${formatContext(chunks)}\n\nQuestion: ${question}`,
    response_format: {
      type: "text",
      mime_type: "application/json",
      schema: ANSWER_JSON_SCHEMA,
    },
  });

  return parseAnswer(interaction.output_text, chunks);
}
