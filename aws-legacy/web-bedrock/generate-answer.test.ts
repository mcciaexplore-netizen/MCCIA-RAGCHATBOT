import { describe, expect, it, vi } from "vitest";
import { generateAnswer, parseCitations } from "../generate-answer";
import type { Citation } from "@aws-sdk/client-bedrock-agent-runtime";

function citation(
  text: string,
  refs: Array<{ article_title?: string; issue_month?: string; source_url?: string }>
): Citation {
  return {
    generatedResponsePart: { textResponsePart: { text } },
    retrievedReferences: refs.map((metadata) => ({
      content: { text: "excerpt" },
      metadata,
    })),
  };
}

describe("parseCitations", () => {
  it("extracts article title, issue month, and source url from metadata", () => {
    const result = parseCitations([
      citation("MCCIA ran relief drives.", [
        {
          article_title: "COVID Relief in Pune",
          issue_month: "2020-05",
          source_url: "https://mcciapunesampada.com/2020/05/covid-relief.html",
        },
      ]),
    ]);

    expect(result).toEqual([
      {
        articleTitle: "COVID Relief in Pune",
        issueMonth: "2020-05",
        sourceUrl: "https://mcciapunesampada.com/2020/05/covid-relief.html",
      },
    ]);
  });

  it("defaults sourceUrl to empty string when absent", () => {
    const result = parseCitations([
      citation("Some fact.", [{ article_title: "Editorial", issue_month: "2021-06" }]),
    ]);
    expect(result[0].sourceUrl).toBe("");
  });

  it("skips references missing article_title or issue_month rather than guessing", () => {
    const result = parseCitations([
      citation("Some fact.", [
        { issue_month: "2021-06" },
        { article_title: "No date" },
        { article_title: "Complete", issue_month: "2021-07" },
      ]),
    ]);
    expect(result).toEqual([
      { articleTitle: "Complete", issueMonth: "2021-07", sourceUrl: "" },
    ]);
  });

  it("dedupes the same article cited across multiple generated spans", () => {
    const result = parseCitations([
      citation("First claim.", [{ article_title: "Editorial", issue_month: "2021-06" }]),
      citation("Second claim.", [{ article_title: "Editorial", issue_month: "2021-06" }]),
    ]);
    expect(result).toHaveLength(1);
  });

  it("returns an empty array when there are no citations", () => {
    expect(parseCitations(undefined)).toEqual([]);
  });
});

describe("generateAnswer", () => {
  it("passes the issue filter through and returns the parsed answer + citations", async () => {
    const send = vi.fn().mockResolvedValue({
      output: { text: 'Sampada ran a food drive (Sampada, June 2021, "Editorial").' },
      citations: [citation("food drive", [{ article_title: "Editorial", issue_month: "2021-06" }])],
    });
    const fakeClient = { send } as unknown as import("@aws-sdk/client-bedrock-agent-runtime").BedrockAgentRuntimeClient;

    process.env.BEDROCK_MODEL_ARN = "global.anthropic.claude-test";
    process.env.BEDROCK_KNOWLEDGE_BASE_ID = "kb-test-id";

    const result = await generateAnswer(
      "What was in the June 2021 issue?",
      { scope: "issue", issueMonth: "2021-06" },
      { client: fakeClient }
    );

    expect(result.answer).toContain("food drive");
    expect(result.citations).toEqual([
      { articleTitle: "Editorial", issueMonth: "2021-06", sourceUrl: "" },
    ]);

    const command = send.mock.calls[0][0];
    const kbConfig = command.input.retrieveAndGenerateConfiguration.knowledgeBaseConfiguration;
    expect(kbConfig.knowledgeBaseId).toBe("kb-test-id");
    expect(kbConfig.retrievalConfiguration.vectorSearchConfiguration.filter).toEqual({
      equals: { key: "issue_month", value: "2021-06" },
    });
    expect(kbConfig.generationConfiguration.promptTemplate.textPromptTemplate).toContain(
      "$search_results$"
    );
  });

  it("omits the filter entirely for an open-scope query", async () => {
    const send = vi.fn().mockResolvedValue({ output: { text: "answer" }, citations: [] });
    const fakeClient = { send } as unknown as import("@aws-sdk/client-bedrock-agent-runtime").BedrockAgentRuntimeClient;
    process.env.BEDROCK_MODEL_ARN = "global.anthropic.claude-test";
    process.env.BEDROCK_KNOWLEDGE_BASE_ID = "kb-test-id";

    await generateAnswer("What did MCCIA do during COVID?", { scope: "open" }, { client: fakeClient });

    const command = send.mock.calls[0][0];
    const kbConfig = command.input.retrieveAndGenerateConfiguration.knowledgeBaseConfiguration;
    expect(kbConfig.retrievalConfiguration).toBeUndefined();
  });
});
