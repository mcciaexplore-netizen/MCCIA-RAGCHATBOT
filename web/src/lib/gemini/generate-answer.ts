import "server-only";
import type { GoogleGenAI } from "@google/genai";
import type { NeonQueryFunction } from "@neondatabase/serverless";
import { buildGeminiClient } from "@/lib/gemini/client";
import { embedQuery } from "@/lib/gemini/embed";
import { GEMINI_ANSWER_MODEL } from "@/lib/gemini/models";
import type { QueryRoute } from "@/lib/gemini/query-router";
import { formatIssueMonth } from "@/lib/format";
import { search, type SearchResult } from "@/lib/retrieval";
import type { ParsedCitation } from "@/lib/types";

export type AnswerResult = {
  answer: string;
  citations: ParsedCitation[];
};

const NOT_FOUND_ANSWER =
  "I couldn't find anything in the Sampada archive about that.";

export const SYSTEM_PROMPT = `You are Sampada's research assistant. Sampada is MCCIA's monthly industrial magazine archive, spanning 70+ years of issues.

Answer strictly from the excerpts below. Never fill gaps from general or outside knowledge, even if you're confident about the answer.

Rules:
- If the excerpts span multiple issues, synthesize across them and say which issue each fact comes from.
- After every factual claim, cite it inline as: (Sampada, <Month Year>, "<Article Title>"). Use exactly the issue and title labeled on each excerpt below -- never invent a date or title that isn't shown there.
- If the excerpts don't contain enough information to answer the question, say so plainly instead of guessing.
- Keep your answer concise. Only go into more depth if the user explicitly asks for it.`;

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

/** Built from the SQL rows, not trusted from the model's own output (Phase 4
 * step 3) -- deduped, since several chunks from the same article commonly
 * land in one result set.
 */
export function buildCitations(chunks: SearchResult[]): ParsedCitation[] {
  const seen = new Set<string>();
  const citations: ParsedCitation[] = [];

  for (const chunk of chunks) {
    const key = `${chunk.issueMonth}::${chunk.articleTitle}`;
    if (seen.has(key)) continue;
    seen.add(key);
    citations.push({
      articleTitle: chunk.articleTitle,
      issueMonth: chunk.issueMonth,
      sourceUrl: chunk.sourceUrl ?? "",
    });
  }

  return citations;
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
    return { answer: NOT_FOUND_ANSWER, citations: [] };
  }

  const interaction = await client.interactions.create({
    model: GEMINI_ANSWER_MODEL,
    system_instruction: SYSTEM_PROMPT,
    input: `${formatContext(chunks)}\n\nQuestion: ${question}`,
  });

  return {
    answer: interaction.output_text ?? "",
    citations: buildCitations(chunks),
  };
}
