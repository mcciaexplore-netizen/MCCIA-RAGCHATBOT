import "server-only";
import type { GoogleGenAI } from "@google/genai";
import { z } from "zod";
import { buildGeminiClient } from "@/lib/gemini/client";
import { GEMINI_CLASSIFY_MODEL } from "@/lib/gemini/models";

const ISSUE_MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

export type QueryRoute =
  | { scope: "open" }
  | { scope: "issue"; issueMonth: string };

const ClassificationSchema = z.object({
  scope: z.enum(["issue", "open"]),
  issue_month: z.string().optional(),
});

const CLASSIFICATION_JSON_SCHEMA = {
  type: "object",
  properties: {
    scope: {
      type: "string",
      enum: ["issue", "open"],
      description:
        "'issue' if the question names or clearly pins down one specific issue's month and year, else 'open'.",
    },
    issue_month: {
      type: "string",
      description: "Only when scope is 'issue': that issue's date as YYYY-MM.",
    },
  },
  required: ["scope"],
};

export function systemPrompt(today: string): string {
  return `You classify questions about Sampada, MCCIA's monthly industrial magazine archive (issues going back 70+ years). Today's date is ${today}.

Respond with JSON matching the given schema.
- scope="issue" only when the question names or clearly pins down ONE specific issue: an explicit month+year ("June 2021"), or a relative reference resolvable from today's date ("last month's issue", "the latest issue"). Set issue_month to that issue's date as YYYY-MM.
- scope="open" for anything else: topics, themes, people, or spans of time ("during COVID", "in the 2010s", "over the last decade"), or a question that names a year but not a month.
- If you cannot confidently resolve one specific YYYY-MM, use scope="open" rather than guessing.`;
}

/** Pure parsing of the model's raw JSON text -- no network access, so this
 * is unit-testable without a live Gemini call. Falls back to "open" scope
 * whenever the model's answer is malformed rather than risking a broken SQL
 * filter that would silently return zero results.
 */
export function parseClassification(outputText: string | undefined): QueryRoute {
  if (!outputText) {
    throw new Error("Gemini response had no output text");
  }

  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(outputText);
  } catch {
    return { scope: "open" };
  }

  const result = ClassificationSchema.safeParse(parsedJson);
  if (!result.success) return { scope: "open" };

  const { scope, issue_month } = result.data;
  if (scope === "issue" && issue_month && ISSUE_MONTH_RE.test(issue_month)) {
    return { scope: "issue", issueMonth: issue_month };
  }
  return { scope: "open" };
}

export async function classifyQuery(
  question: string,
  opts?: { today?: string; client?: GoogleGenAI }
): Promise<QueryRoute> {
  const today = opts?.today ?? new Date().toISOString().slice(0, 10);
  const client = opts?.client ?? buildGeminiClient();

  const interaction = await client.interactions.create({
    model: GEMINI_CLASSIFY_MODEL,
    system_instruction: systemPrompt(today),
    input: question,
    response_format: {
      type: "text",
      mime_type: "application/json",
      schema: CLASSIFICATION_JSON_SCHEMA,
    },
  });

  return parseClassification(interaction.output_text);
}
