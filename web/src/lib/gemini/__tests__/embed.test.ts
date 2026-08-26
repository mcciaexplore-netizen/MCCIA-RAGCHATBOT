import { describe, expect, it, vi } from "vitest";
import { embedQuery } from "../embed";

function fakeClient(values: number[] | undefined) {
  const embedContent = vi.fn().mockResolvedValue({ embeddings: values ? [{ values }] : [] });
  return {
    client: { models: { embedContent } } as unknown as import("@google/genai").GoogleGenAI,
    embedContent,
  };
}

describe("embedQuery", () => {
  it("requests RETRIEVAL_QUERY task type and 1536 dimensions", async () => {
    const { client, embedContent } = fakeClient([3, 4]);
    process.env.GEMINI_API_KEY = "test-key";

    await embedQuery("what happened in June 2021?", { client });

    const params = embedContent.mock.calls[0][0];
    expect(params.config.taskType).toBe("RETRIEVAL_QUERY");
    expect(params.config.outputDimensionality).toBe(1536);
    expect(params.contents).toEqual(["what happened in June 2021?"]);
  });

  it("L2-normalizes the returned vector", async () => {
    const { client } = fakeClient([3, 4]); // magnitude 5
    process.env.GEMINI_API_KEY = "test-key";

    const result = await embedQuery("question", { client });

    expect(result).toEqual([0.6, 0.8]);
  });

  it("leaves a zero vector as-is rather than dividing by zero", async () => {
    const { client } = fakeClient([0, 0]);
    process.env.GEMINI_API_KEY = "test-key";

    const result = await embedQuery("question", { client });

    expect(result).toEqual([0, 0]);
  });

  it("throws a clear error when Gemini returns no embedding", async () => {
    const { client } = fakeClient(undefined);
    process.env.GEMINI_API_KEY = "test-key";

    await expect(embedQuery("question", { client })).rejects.toThrow(/no values/);
  });
});
