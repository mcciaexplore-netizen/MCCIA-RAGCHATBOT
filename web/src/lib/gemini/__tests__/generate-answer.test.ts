import { describe, expect, it, vi } from "vitest";
import {
  buildCitations,
  formatContext,
  generateAnswer,
  SYSTEM_PROMPT,
} from "../generate-answer";
import type { SearchResult } from "@/lib/retrieval";

const EDITORIAL: SearchResult = {
  articleId: 1,
  content: "MCCIA ran robotics workshops across Pune.",
  issueMonth: "2021-06",
  articleTitle: "Editorial",
  sourceUrl: "https://www.mcciapunesampada.com/p/sampada-june-2021.html",
};

const SECOND_CHUNK_SAME_ARTICLE: SearchResult = {
  ...EDITORIAL,
  content: "Over 200 members attended.",
};

const COVID_RELIEF: SearchResult = {
  articleId: 2,
  content: "MCCIA distributed oxygen concentrators.",
  issueMonth: "2020-05",
  articleTitle: "COVID Relief in Pune",
  sourceUrl: "",
};

describe("formatContext", () => {
  it("labels each excerpt with its issue and article title", () => {
    const context = formatContext([EDITORIAL]);
    expect(context).toContain('Sampada, June 2021, "Editorial"');
    expect(context).toContain("MCCIA ran robotics workshops across Pune.");
  });

  it("numbers multiple excerpts distinctly", () => {
    const context = formatContext([EDITORIAL, COVID_RELIEF]);
    expect(context).toContain("Excerpt 1");
    expect(context).toContain("Excerpt 2");
  });
});

describe("buildCitations", () => {
  it("builds one citation per chunk", () => {
    const citations = buildCitations([EDITORIAL, COVID_RELIEF]);
    expect(citations).toEqual([
      {
        articleId: 1,
        articleTitle: "Editorial",
        issueMonth: "2021-06",
        sourceUrl: "https://www.mcciapunesampada.com/p/sampada-june-2021.html",
      },
      { articleId: 2, articleTitle: "COVID Relief in Pune", issueMonth: "2020-05", sourceUrl: "" },
    ]);
  });

  it("dedupes multiple chunks from the same article", () => {
    const citations = buildCitations([EDITORIAL, SECOND_CHUNK_SAME_ARTICLE]);
    expect(citations).toHaveLength(1);
  });

  it("returns an empty array for no chunks", () => {
    expect(buildCitations([])).toEqual([]);
  });
});

function fakeGeminiClient(embedding: number[], outputText: string) {
  const embedContent = vi.fn().mockResolvedValue({ embeddings: [{ values: embedding }] });
  const create = vi.fn().mockResolvedValue({ output_text: outputText });
  return {
    client: {
      models: { embedContent },
      interactions: { create },
    } as unknown as import("@google/genai").GoogleGenAI,
    embedContent,
    create,
  };
}

function fakeDbClient(rows: SearchResult[]) {
  const calls: unknown[][] = [];
  const fn = (strings: TemplateStringsArray, ...values: unknown[]) => {
    calls.push(values);
    return Promise.resolve(rows);
  };
  return {
    dbClient: fn as unknown as NonNullable<Parameters<typeof generateAnswer>[2]>["dbClient"],
    calls,
  };
}

describe("generateAnswer", () => {
  it("embeds the question, searches, and generates a cited answer", async () => {
    const { client, embedContent, create } = fakeGeminiClient(
      [0.1, 0.2],
      'MCCIA ran robotics workshops (Sampada, June 2021, "Editorial").'
    );
    const { dbClient } = fakeDbClient([EDITORIAL]);
    process.env.GEMINI_API_KEY = "test-key";
    process.env.DATABASE_URL = "postgres://test";

    const result = await generateAnswer(
      "What happened in June 2021?",
      { scope: "issue", issueMonth: "2021-06" },
      { client, dbClient }
    );

    expect(embedContent).toHaveBeenCalledTimes(1);
    expect(embedContent.mock.calls[0][0].config.taskType).toBe("RETRIEVAL_QUERY");

    expect(result.answer).toContain("robotics workshops");
    expect(result.citations).toEqual([
      {
        articleId: 1,
        articleTitle: "Editorial",
        issueMonth: "2021-06",
        sourceUrl: "https://www.mcciapunesampada.com/p/sampada-june-2021.html",
      },
    ]);

    const genParams = create.mock.calls[0][0];
    expect(genParams.model).toBeTruthy();
    expect(genParams.system_instruction).toBe(SYSTEM_PROMPT);
    expect(genParams.input).toContain("What happened in June 2021?");
    expect(genParams.input).toContain('Sampada, June 2021, "Editorial"');
  });

  it("returns a not-found answer without calling Gemini when search returns nothing", async () => {
    const { client, create } = fakeGeminiClient([0.1], "should not be used");
    const { dbClient } = fakeDbClient([]);
    process.env.GEMINI_API_KEY = "test-key";
    process.env.DATABASE_URL = "postgres://test";

    const result = await generateAnswer("Anything about widgets?", { scope: "open" }, { client, dbClient });

    expect(result.answer).toMatch(/couldn't find/i);
    expect(result.citations).toEqual([]);
    expect(create).not.toHaveBeenCalled();
  });

  it("passes the caller-supplied limit through to search", async () => {
    const { client } = fakeGeminiClient([0.1], "answer");
    const { dbClient, calls } = fakeDbClient([EDITORIAL]);
    process.env.GEMINI_API_KEY = "test-key";
    process.env.DATABASE_URL = "postgres://test";

    await generateAnswer("question", { scope: "open" }, { client, dbClient, limit: 8 });

    expect(calls[0]).toContain(8);
  });
});
