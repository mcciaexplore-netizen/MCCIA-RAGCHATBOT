import "server-only";
import {
  BedrockRuntimeClient,
  ConverseCommand,
  type Message,
} from "@aws-sdk/client-bedrock-runtime";
import { z } from "zod";
import { config } from "@/lib/config";

const ISSUE_MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

export type QueryRoute =
  | { scope: "open" }
  | { scope: "issue"; issueMonth: string };

const ClassificationSchema = z.object({
  scope: z.enum(["issue", "open"]),
  issue_month: z.string().optional(),
});

const CLASSIFY_QUERY_TOOL = {
  toolSpec: {
    name: "classify_query",
    description:
      "Classify whether the user's question is about one specific Sampada issue, or an open topic search across the whole archive.",
    inputSchema: {
      json: {
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
            description:
              "Only when scope is 'issue': that issue's date as YYYY-MM.",
          },
        },
        required: ["scope"],
      },
    },
  },
};

export function systemPrompt(today: string): string {
  return `You classify questions about Sampada, MCCIA's monthly industrial magazine archive (issues going back 70+ years). Today's date is ${today}.

Call classify_query exactly once.
- scope="issue" only when the question names or clearly pins down ONE specific issue: an explicit month+year ("June 2021"), or a relative reference resolvable from today's date ("last month's issue", "the latest issue"). Set issue_month to that issue's date as YYYY-MM.
- scope="open" for anything else: topics, themes, people, or spans of time ("during COVID", "in the 2010s", "over the last decade"), or a question that names a year but not a month.
- If you cannot confidently resolve one specific YYYY-MM, use scope="open" rather than guessing.`;
}

/** Pure parsing of a Converse response's message content -- no network
 * access, so this is unit-testable without a live Bedrock call. Falls back
 * to "open" scope whenever the model's answer is malformed rather than
 * risking a broken RetrievalFilter that would silently return zero results.
 */
export function parseClassification(content: unknown[]): QueryRoute {
  for (const block of content as Array<Record<string, unknown>>) {
    const toolUse = block.toolUse as
      | { name?: string; input?: unknown }
      | undefined;
    if (toolUse?.name !== "classify_query") continue;

    const result = ClassificationSchema.safeParse(toolUse.input);
    if (!result.success) return { scope: "open" };

    const { scope, issue_month } = result.data;
    if (scope === "issue" && issue_month && ISSUE_MONTH_RE.test(issue_month)) {
      return { scope: "issue", issueMonth: issue_month };
    }
    return { scope: "open" };
  }
  throw new Error("Model response did not include a classify_query tool call");
}

function buildClient(): BedrockRuntimeClient {
  return new BedrockRuntimeClient({ region: config.awsRegion });
}

export async function classifyQuery(
  question: string,
  opts?: { today?: string; client?: BedrockRuntimeClient }
): Promise<QueryRoute> {
  const today = opts?.today ?? new Date().toISOString().slice(0, 10);
  const client = opts?.client ?? buildClient();

  const messages: Message[] = [
    { role: "user", content: [{ text: question }] },
  ];

  const response = await client.send(
    new ConverseCommand({
      modelId: config.bedrockModelArn,
      system: [{ text: systemPrompt(today) }],
      messages,
      toolConfig: {
        tools: [CLASSIFY_QUERY_TOOL],
        toolChoice: { tool: { name: "classify_query" } },
      },
    })
  );

  const content = response.output?.message?.content;
  if (!content) throw new Error("Bedrock response had no message content");
  return parseClassification(content);
}

/** Spec: { "equals": { "key": "issue_month", "value": "2021-06" } }, or no
 * filter at all for an open search.
 */
export function buildRetrievalFilter(route: QueryRoute) {
  if (route.scope === "open") return undefined;
  return { equals: { key: "issue_month", value: route.issueMonth } };
}
