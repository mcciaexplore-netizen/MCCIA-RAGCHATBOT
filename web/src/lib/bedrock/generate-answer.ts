import "server-only";
import {
  BedrockAgentRuntimeClient,
  RetrieveAndGenerateCommand,
  type Citation,
} from "@aws-sdk/client-bedrock-agent-runtime";
import { config } from "@/lib/config";
import type { ParsedCitation } from "@/lib/types";
import { buildRetrievalFilter, type QueryRoute } from "./query-router";

// Bedrock's RetrieveAndGenerate never exposes metadata attributes to the
// generation model -- it only ever sees chunk text via $search_results$. The
// issue date the spec's citation format needs comes from the "Sampada,
// <Month Year>" line Phase 1 prints at the top of every article file, not
// from metadata. $query$ and $output_format_instructions$ are both
// documented placeholders for this template (the latter is required for
// `citations` to be populated in the response at all) --
// https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-placeholders.html
export const GENERATION_PROMPT_TEMPLATE = `Human: You are Sampada's research assistant. Sampada is MCCIA's monthly industrial magazine archive, spanning 70+ years of issues.

Answer strictly from the search results below. Never fill gaps from general or outside knowledge, even if you're confident about the answer.

Rules:
- If the results span multiple issues, synthesize across them and say which issue each fact comes from.
- After every factual claim, cite it inline as: (Sampada, <Month Year>, "<Article Title>"). Read the month/year and title directly from the "Sampada, <Month Year>" line and headline printed at the top of each excerpt -- never invent a date or title that isn't shown there.
- If the search results don't contain enough information to answer the question, say so plainly instead of guessing.
- Keep your answer concise. Only go into more depth if the user explicitly asks for it.

<search_results>
$search_results$
</search_results>

$output_format_instructions$

Human: $query$

Assistant:`;

export type AnswerResult = {
  answer: string;
  citations: ParsedCitation[];
};

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** Pure parsing of the RetrieveAndGenerate response's citations into a
 * deduplicated, UI-ready list -- no network access, unit-testable directly.
 */
export function parseCitations(citations: Citation[] | undefined): ParsedCitation[] {
  const seen = new Set<string>();
  const result: ParsedCitation[] = [];

  for (const citation of citations ?? []) {
    for (const ref of citation.retrievedReferences ?? []) {
      const metadata = ref.metadata ?? {};
      const articleTitle = asString(metadata.article_title);
      const issueMonth = asString(metadata.issue_month);
      if (!articleTitle || !issueMonth) continue;

      const key = `${issueMonth}::${articleTitle}`;
      if (seen.has(key)) continue;
      seen.add(key);

      result.push({
        articleTitle,
        issueMonth,
        sourceUrl: asString(metadata.source_url),
      });
    }
  }

  return result;
}

function buildClient(): BedrockAgentRuntimeClient {
  return new BedrockAgentRuntimeClient({ region: config.awsRegion });
}

export async function generateAnswer(
  question: string,
  route: QueryRoute,
  opts?: { client?: BedrockAgentRuntimeClient }
): Promise<AnswerResult> {
  const client = opts?.client ?? buildClient();
  const filter = buildRetrievalFilter(route);

  const response = await client.send(
    new RetrieveAndGenerateCommand({
      input: { text: question },
      retrieveAndGenerateConfiguration: {
        type: "KNOWLEDGE_BASE",
        knowledgeBaseConfiguration: {
          knowledgeBaseId: config.knowledgeBaseId,
          modelArn: config.bedrockModelArn,
          generationConfiguration: {
            promptTemplate: { textPromptTemplate: GENERATION_PROMPT_TEMPLATE },
          },
          retrievalConfiguration: filter
            ? { vectorSearchConfiguration: { filter } }
            : undefined,
        },
      },
    })
  );

  return {
    answer: response.output?.text ?? "",
    citations: parseCitations(response.citations),
  };
}
