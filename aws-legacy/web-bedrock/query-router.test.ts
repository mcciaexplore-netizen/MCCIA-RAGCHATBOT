import { describe, expect, it, vi } from "vitest";
import {
  buildRetrievalFilter,
  classifyQuery,
  parseClassification,
} from "../query-router";

function toolUseContent(input: Record<string, unknown>) {
  return [
    { text: "some preamble the model might add" },
    { toolUse: { name: "classify_query", input } },
  ];
}

describe("parseClassification", () => {
  it("returns issue scope with a well-formed issue_month", () => {
    const route = parseClassification(
      toolUseContent({ scope: "issue", issue_month: "2021-06" })
    );
    expect(route).toEqual({ scope: "issue", issueMonth: "2021-06" });
  });

  it("falls back to open when scope is issue but issue_month is missing", () => {
    const route = parseClassification(toolUseContent({ scope: "issue" }));
    expect(route).toEqual({ scope: "open" });
  });

  it("falls back to open when issue_month is malformed", () => {
    const route = parseClassification(
      toolUseContent({ scope: "issue", issue_month: "June 2021" })
    );
    expect(route).toEqual({ scope: "open" });
  });

  it("falls back to open when the tool payload doesn't match the schema at all", () => {
    const route = parseClassification(
      toolUseContent({ nonsense: true } as unknown as Record<string, unknown>)
    );
    expect(route).toEqual({ scope: "open" });
  });

  it("returns open scope as-is", () => {
    const route = parseClassification(toolUseContent({ scope: "open" }));
    expect(route).toEqual({ scope: "open" });
  });

  it("throws if the model never calls classify_query", () => {
    expect(() => parseClassification([{ text: "no tool call here" }])).toThrow(
      /classify_query/
    );
  });
});

describe("buildRetrievalFilter", () => {
  it("returns undefined (no filter) for open scope", () => {
    expect(buildRetrievalFilter({ scope: "open" })).toBeUndefined();
  });

  it("builds an equals filter on issue_month for issue scope", () => {
    expect(
      buildRetrievalFilter({ scope: "issue", issueMonth: "2021-06" })
    ).toEqual({ equals: { key: "issue_month", value: "2021-06" } });
  });
});

describe("classifyQuery", () => {
  it("sends the question + today's date and parses the tool response", async () => {
    const send = vi.fn().mockResolvedValue({
      output: {
        message: {
          content: toolUseContent({ scope: "issue", issue_month: "2021-06" }),
        },
      },
    });
    const fakeClient = { send } as unknown as import("@aws-sdk/client-bedrock-runtime").BedrockRuntimeClient;

    process.env.BEDROCK_MODEL_ARN = "global.anthropic.claude-test";

    const route = await classifyQuery("What was in the June 2021 issue?", {
      today: "2026-08-25",
      client: fakeClient,
    });

    expect(route).toEqual({ scope: "issue", issueMonth: "2021-06" });
    expect(send).toHaveBeenCalledTimes(1);
    const command = send.mock.calls[0][0];
    expect(command.input.toolConfig.toolChoice).toEqual({
      tool: { name: "classify_query" },
    });
    expect(command.input.system[0].text).toContain("2026-08-25");
    expect(command.input.messages[0].content[0].text).toBe(
      "What was in the June 2021 issue?"
    );
  });

  it("throws a clear error when Bedrock returns no message content", async () => {
    const send = vi.fn().mockResolvedValue({ output: {} });
    const fakeClient = { send } as unknown as import("@aws-sdk/client-bedrock-runtime").BedrockRuntimeClient;
    process.env.BEDROCK_MODEL_ARN = "global.anthropic.claude-test";

    await expect(
      classifyQuery("anything", { client: fakeClient })
    ).rejects.toThrow(/no message content/);
  });
});
