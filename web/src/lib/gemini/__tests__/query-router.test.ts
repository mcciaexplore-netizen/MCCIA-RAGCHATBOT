import { describe, expect, it, vi } from "vitest";
import { classifyQuery, parseClassification } from "../query-router";

describe("parseClassification", () => {
  it("returns issue scope with a well-formed issue_month", () => {
    const route = parseClassification(
      JSON.stringify({ scope: "issue", issue_month: "2021-06" })
    );
    expect(route).toEqual({ scope: "issue", issueMonth: "2021-06" });
  });

  it("falls back to open when scope is issue but issue_month is missing", () => {
    const route = parseClassification(JSON.stringify({ scope: "issue" }));
    expect(route).toEqual({ scope: "open" });
  });

  it("falls back to open when issue_month is malformed", () => {
    const route = parseClassification(
      JSON.stringify({ scope: "issue", issue_month: "June 2021" })
    );
    expect(route).toEqual({ scope: "open" });
  });

  it("falls back to open when the JSON doesn't match the schema at all", () => {
    const route = parseClassification(JSON.stringify({ nonsense: true }));
    expect(route).toEqual({ scope: "open" });
  });

  it("falls back to open when the response isn't valid JSON", () => {
    const route = parseClassification("not json at all");
    expect(route).toEqual({ scope: "open" });
  });

  it("returns open scope as-is", () => {
    const route = parseClassification(JSON.stringify({ scope: "open" }));
    expect(route).toEqual({ scope: "open" });
  });

  it("throws if Gemini returns no output text", () => {
    expect(() => parseClassification(undefined)).toThrow(/no output text/);
  });
});

function fakeClient(outputText: string) {
  const create = vi.fn().mockResolvedValue({ output_text: outputText });
  return {
    client: { interactions: { create } } as unknown as import("@google/genai").GoogleGenAI,
    create,
  };
}

describe("classifyQuery", () => {
  it("sends the question + today's date and parses the JSON response", async () => {
    const { client, create } = fakeClient(
      JSON.stringify({ scope: "issue", issue_month: "2021-06" })
    );
    process.env.GEMINI_API_KEY = "test-key";

    const route = await classifyQuery("What was in the June 2021 issue?", {
      today: "2026-08-26",
      client,
    });

    expect(route).toEqual({ scope: "issue", issueMonth: "2021-06" });
    expect(create).toHaveBeenCalledTimes(1);
    const params = create.mock.calls[0][0];
    expect(params.system_instruction).toContain("2026-08-26");
    expect(params.input).toBe("What was in the June 2021 issue?");
    expect(params.response_format).toEqual({
      type: "text",
      mime_type: "application/json",
      schema: expect.objectContaining({ required: ["scope"] }),
    });
  });

  it("propagates a clear error when Gemini returns no output text", async () => {
    const { client } = fakeClient(undefined as unknown as string);
    process.env.GEMINI_API_KEY = "test-key";

    await expect(classifyQuery("anything", { client })).rejects.toThrow(/no output text/);
  });
});
