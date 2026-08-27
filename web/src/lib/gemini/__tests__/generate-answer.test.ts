import { describe, expect, it, vi } from "vitest";
import {
  buildCitations,
  formatContext,
  generateAnswer,
  parseAnswer,
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
  it("builds citations only for the excerpt numbers Gemini says it used", () => {
    const citations = buildCitations([EDITORIAL, COVID_RELIEF], [1, 2]);
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

  it("excludes retrieved chunks Gemini did not actually cite", () => {
    const citations = buildCitations([EDITORIAL, COVID_RELIEF], [1]);
    expect(citations).toEqual([
      {
        articleId: 1,
        articleTitle: "Editorial",
        issueMonth: "2021-06",
        sourceUrl: "https://www.mcciapunesampada.com/p/sampada-june-2021.html",
      },
    ]);
  });

  it("dedupes multiple cited chunks from the same article", () => {
    const citations = buildCitations([EDITORIAL, SECOND_CHUNK_SAME_ARTICLE], [1, 2]);
    expect(citations).toHaveLength(1);
  });

  it("returns an empty array when nothing was cited", () => {
    expect(buildCitations([EDITORIAL, COVID_RELIEF], [])).toEqual([]);
    expect(buildCitations([], [])).toEqual([]);
  });
});

describe("parseAnswer", () => {
  it("splits the English/Marathi answers and resolves cited excerpts", () => {
    const raw = JSON.stringify({
      answer_en: "MCCIA ran robotics workshops.",
      answer_mr: "MCCIA ने रोबोटिक्स कार्यशाळा घेतल्या.",
      cited_excerpt_numbers: [1],
    });

    const result = parseAnswer(raw, [EDITORIAL, COVID_RELIEF]);

    expect(result.answerEnglish).toBe("MCCIA ran robotics workshops.");
    expect(result.answerMarathi).toBe("MCCIA ने रोबोटिक्स कार्यशाळा घेतल्या.");
    expect(result.citations).toEqual([
      {
        articleId: 1,
        articleTitle: "Editorial",
        issueMonth: "2021-06",
        sourceUrl: "https://www.mcciapunesampada.com/p/sampada-june-2021.html",
      },
    ]);
  });

  it("defaults to no citations when cited_excerpt_numbers is omitted", () => {
    const raw = JSON.stringify({
      answer_en: "Not enough information.",
      answer_mr: "पुरेशी माहिती नाही.",
    });

    const result = parseAnswer(raw, [EDITORIAL]);
    expect(result.citations).toEqual([]);
  });

  it("throws when there's no output text", () => {
    expect(() => parseAnswer(undefined, [EDITORIAL])).toThrow();
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

const BILINGUAL_ANSWER = JSON.stringify({
  answer_en: 'MCCIA ran robotics workshops (Sampada, June 2021, "Editorial").',
  answer_mr: 'MCCIA ने रोबोटिक्स कार्यशाळा घेतल्या (Sampada, June 2021, "Editorial").',
  cited_excerpt_numbers: [1],
});

describe("generateAnswer", () => {
  it("embeds the question, searches, and generates a cited bilingual answer", async () => {
    const { client, embedContent, create } = fakeGeminiClient([0.1, 0.2], BILINGUAL_ANSWER);
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

    expect(result.answerEnglish).toContain("robotics workshops");
    expect(result.answerMarathi).toContain("रोबोटिक्स");
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
    expect(genParams.response_format.schema.required).toEqual([
      "answer_en",
      "answer_mr",
      "cited_excerpt_numbers",
    ]);
  });

  it("drops citations for retrieved chunks Gemini didn't actually use", async () => {
    const raw = JSON.stringify({
      answer_en: "The excerpts don't contain information about that.",
      answer_mr: "उतारांमध्ये त्याबद्दल माहिती नाही.",
      cited_excerpt_numbers: [],
    });
    const { client } = fakeGeminiClient([0.1], raw);
    const { dbClient } = fakeDbClient([EDITORIAL, COVID_RELIEF]);
    process.env.GEMINI_API_KEY = "test-key";
    process.env.DATABASE_URL = "postgres://test";

    const result = await generateAnswer("What is the price of Bitcoin?", { scope: "open" }, { client, dbClient });

    expect(result.citations).toEqual([]);
  });

  it("returns a bilingual not-found answer without calling Gemini when search returns nothing", async () => {
    const { client, create } = fakeGeminiClient([0.1], "should not be used");
    const { dbClient } = fakeDbClient([]);
    process.env.GEMINI_API_KEY = "test-key";
    process.env.DATABASE_URL = "postgres://test";

    const result = await generateAnswer("Anything about widgets?", { scope: "open" }, { client, dbClient });

    expect(result.answerEnglish).toMatch(/couldn't find/i);
    expect(result.answerMarathi.length).toBeGreaterThan(0);
    expect(result.citations).toEqual([]);
    expect(create).not.toHaveBeenCalled();
  });

  it("passes the caller-supplied limit through to search", async () => {
    const { client } = fakeGeminiClient([0.1], BILINGUAL_ANSWER);
    const { dbClient, calls } = fakeDbClient([EDITORIAL]);
    process.env.GEMINI_API_KEY = "test-key";
    process.env.DATABASE_URL = "postgres://test";

    await generateAnswer("question", { scope: "open" }, { client, dbClient, limit: 8 });

    expect(calls[0]).toContain(8);
  });
});
