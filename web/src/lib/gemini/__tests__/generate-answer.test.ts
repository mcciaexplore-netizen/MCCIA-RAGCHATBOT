import { describe, expect, it, vi } from "vitest";
import {
  buildCitations,
  describeQuestionType,
  formatContext,
  generateAnswer,
  isLowConfidence,
  parseAnswer,
  stripFabricatedPageNumbers,
  SYSTEM_PROMPT,
} from "../generate-answer";
import type { SearchResult } from "@/lib/retrieval";

const EDITORIAL: SearchResult = {
  articleId: 1,
  content: "MCCIA ran robotics workshops across Pune.",
  issueMonth: "2021-06",
  articleTitle: "Editorial",
  sourceUrl: "https://www.mcciapunesampada.com/p/sampada-june-2021.html",
  pageNumber: 12,
  pdfPageOffset: 4,
  score: 0.9,
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
  pageNumber: null,
  pdfPageOffset: null,
  score: 0.85,
};

const WEAK_MATCH: SearchResult = {
  ...COVID_RELIEF,
  articleId: 3,
  score: 0.1,
};

describe("formatContext", () => {
  it("labels each excerpt with its issue, article title, and page when known", () => {
    const context = formatContext([EDITORIAL]);
    expect(context).toContain('Sampada, June 2021, "Editorial", Page 12');
    expect(context).toContain("MCCIA ran robotics workshops across Pune.");
  });

  it("omits the page suffix when a chunk has no page number, never fabricating one", () => {
    const context = formatContext([COVID_RELIEF]);
    expect(context).toContain('Sampada, May 2020, "COVID Relief in Pune"]');
    expect(context).not.toContain("Page");
  });

  it("numbers multiple excerpts distinctly", () => {
    const context = formatContext([EDITORIAL, COVID_RELIEF]);
    expect(context).toContain("Excerpt 1");
    expect(context).toContain("Excerpt 2");
  });
});

describe("describeQuestionType", () => {
  it("describes an issue-scoped question with its edition", () => {
    expect(describeQuestionType({ scope: "issue", issueMonth: "1956-07", intent: "summary" })).toBe(
      "Classified as a summary question about the July 1956 issue."
    );
  });

  it("describes a range-scoped question with its year span", () => {
    expect(describeQuestionType({ scope: "range", yearFrom: 1955, yearTo: 1965, intent: "semantic" })).toBe(
      "Classified as a semantic question spanning 1955-1965."
    );
  });

  it("describes an open-scoped question with no scope note", () => {
    expect(describeQuestionType({ scope: "open", intent: "exact" })).toBe("Classified as a exact question.");
  });
});

describe("isLowConfidence", () => {
  it("is true when nothing was retrieved", () => {
    expect(isLowConfidence([])).toBe(true);
  });

  it("is false when the best result scores above the threshold", () => {
    expect(isLowConfidence([EDITORIAL, WEAK_MATCH])).toBe(false);
  });

  it("is true when every result scores below the threshold", () => {
    expect(isLowConfidence([WEAK_MATCH])).toBe(true);
  });
});

describe("buildCitations", () => {
  it("builds citations only for the excerpt numbers Gemini says it used, including page", () => {
    const citations = buildCitations([EDITORIAL, COVID_RELIEF], [1, 2]);
    expect(citations).toEqual([
      {
        articleId: 1,
        articleTitle: "Editorial",
        issueMonth: "2021-06",
        sourceUrl: "https://www.mcciapunesampada.com/p/sampada-june-2021.html",
        page: 12,
        pdfPageOffset: 4,
      },
      {
        articleId: 2,
        articleTitle: "COVID Relief in Pune",
        issueMonth: "2020-05",
        sourceUrl: "",
        page: null,
        pdfPageOffset: null,
      },
    ]);
  });

  it("excludes retrieved chunks Gemini did not actually cite", () => {
    const citations = buildCitations([EDITORIAL, COVID_RELIEF], [1]);
    expect(citations).toHaveLength(1);
    expect(citations[0].articleId).toBe(1);
  });

  it("dedupes multiple cited chunks from the same article", () => {
    const citations = buildCitations([EDITORIAL, SECOND_CHUNK_SAME_ARTICLE], [1, 2]);
    expect(citations).toHaveLength(1);
  });

  it("returns an empty array when nothing was cited", () => {
    expect(buildCitations([EDITORIAL, COVID_RELIEF], [])).toEqual([]);
    expect(buildCitations([], [])).toEqual([]);
  });

  it("never invents a page for a citation whose source chunk has none", () => {
    const citations = buildCitations([COVID_RELIEF], [1]);
    expect(citations[0].page).toBeNull();
  });
});

describe("stripFabricatedPageNumbers", () => {
  // Reproduces an actual failure observed in live testing: the model
  // invented "Page 17" for an excerpt whose real issue_page_number is null,
  // despite an explicit prompt instruction not to. This is the deterministic
  // safety net for that -- ground truth comes from `chunks`, never from
  // re-trusting what the model wrote.
  it("strips a fabricated page for an excerpt that has none, using the exact failure text observed live", () => {
    const chunkWithNoPage: SearchResult = {
      ...COVID_RELIEF,
      issueMonth: "1946-11",
      articleTitle: "गुरुनाथराव ओगले स्मृतिदिन",
      pageNumber: null,
    };
    const text =
      'Described as the creator of Prabhakar lanterns (Sampada, November 1946, "गुरुनाथराव ओगले स्मृतिदिन", Page 17).';

    const result = stripFabricatedPageNumbers(text, [chunkWithNoPage]);

    expect(result).toBe(
      'Described as the creator of Prabhakar lanterns (Sampada, November 1946, "गुरुनाथराव ओगले स्मृतिदिन").'
    );
    expect(result).not.toContain("Page");
  });

  it("keeps a page number when the cited excerpt genuinely has one", () => {
    const chunkWithPage: SearchResult = { ...EDITORIAL, pageNumber: 12 };
    const text = 'See (Sampada, June 2021, "Editorial", Page 12) for details.';

    const result = stripFabricatedPageNumbers(text, [chunkWithPage]);

    expect(result).toBe(text); // unchanged -- this page is real
  });

  it("leaves citations with no page suffix untouched", () => {
    const text = 'See (Sampada, June 2021, "Editorial") for details.';
    expect(stripFabricatedPageNumbers(text, [EDITORIAL])).toBe(text);
  });

  it("handles multiple citations, stripping only the fabricated ones", () => {
    const noPage: SearchResult = { ...COVID_RELIEF, pageNumber: null };
    const withPage: SearchResult = { ...EDITORIAL, pageNumber: 12 };
    const text =
      'First (Sampada, June 2021, "Editorial", Page 12) then (Sampada, May 2020, "COVID Relief in Pune", Page 99).';

    const result = stripFabricatedPageNumbers(text, [noPage, withPage]);

    expect(result).toBe('First (Sampada, June 2021, "Editorial", Page 12) then (Sampada, May 2020, "COVID Relief in Pune").');
  });

  it("is a no-op when the text has no citations at all", () => {
    expect(stripFabricatedPageNumbers("Plain answer, no citations.", [EDITORIAL])).toBe(
      "Plain answer, no citations."
    );
  });

  // Reproduces a second, distinct real failure from live testing: the model
  // combined two citations into ONE parenthetical joined by "; ", which a
  // regex anchored to a self-contained "(...)" wrapper never matches at all.
  it("strips a fabricated page from each citation when several are combined in one parenthetical", () => {
    const chunkA: SearchResult = { ...COVID_RELIEF, issueMonth: "1946-11", articleTitle: "गुरुनाथराव ओगले स्मृतिदिन", pageNumber: null };
    const chunkB: SearchResult = { ...EDITORIAL, issueMonth: "1947-06", articleTitle: "तेराव्या वर्षाचा अहवाल", pageNumber: null };
    const text =
      '(Sampada, November 1946, "गुरुनाथराव ओगले स्मृतिदिन", Page 17; Sampada, June 1947, "तेराव्या वर्षाचा अहवाल", Page 10).';

    const result = stripFabricatedPageNumbers(text, [chunkA, chunkB]);

    expect(result).toBe('(Sampada, November 1946, "गुरुनाथराव ओगले स्मृतिदिन"; Sampada, June 1947, "तेराव्या वर्षाचा अहवाल").');
  });

  // Reproduces a third real failure: the model cited a page *range*
  // ("Page 17-18"), not a single number -- the original regex only matched \d+.
  it("strips a fabricated page range, not just a single page number", () => {
    const chunk: SearchResult = { ...EDITORIAL, pageNumber: null };
    const text = 'See (Sampada, June 2021, "Editorial", Page 17-18) for details.';

    const result = stripFabricatedPageNumbers(text, [chunk]);

    expect(result).toBe('See (Sampada, June 2021, "Editorial") for details.');
  });

  // A fourth real failure from live testing: the model dropped the word
  // "Page" entirely and left a bare trailing number -- (Sampada, ..., "X", 16)
  it("strips a fabricated bare trailing number with no 'Page' word at all", () => {
    const chunk: SearchResult = { ...EDITORIAL, pageNumber: null };
    const text = 'Sources:\n- (Sampada, June 2021, "Editorial", 16)';

    const result = stripFabricatedPageNumbers(text, [chunk]);

    expect(result).toBe('Sources:\n- (Sampada, June 2021, "Editorial")');
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
        page: 12,
        pdfPageOffset: 4,
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

  it("strips a fabricated page number from the parsed answer text before returning", () => {
    const noPageChunk: SearchResult = { ...EDITORIAL, pageNumber: null };
    const raw = JSON.stringify({
      answer_en: 'MCCIA ran workshops (Sampada, June 2021, "Editorial", Page 5).',
      answer_mr: 'MCCIA ने कार्यशाळा घेतल्या (Sampada, June 2021, "Editorial", Page 5).',
      cited_excerpt_numbers: [1],
    });

    const result = parseAnswer(raw, [noPageChunk]);

    expect(result.answerEnglish).not.toContain("Page 5");
    expect(result.answerMarathi).not.toContain("Page 5");
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
  answer_en: 'MCCIA ran robotics workshops (Sampada, June 2021, "Editorial", Page 12).',
  answer_mr: 'MCCIA ने रोबोटिक्स कार्यशाळा घेतल्या (Sampada, June 2021, "Editorial", Page 12).',
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
      { scope: "issue", issueMonth: "2021-06", intent: "semantic" },
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
        page: 12,
        pdfPageOffset: 4,
      },
    ]);

    const genParams = create.mock.calls[0][0];
    expect(genParams.model).toBeTruthy();
    expect(genParams.system_instruction).toBe(SYSTEM_PROMPT);
    expect(genParams.input).toContain("What happened in June 2021?");
    expect(genParams.input).toContain('Sampada, June 2021, "Editorial", Page 12');
    expect(genParams.input).toContain("Classified as a semantic question about the June 2021 issue.");
    expect(genParams.response_format.schema.required).toEqual([
      "answer_en",
      "answer_mr",
      "cited_excerpt_numbers",
    ]);
    // gemini-3.7-flash thinks by default -- turned down since this is a
    // bounded extraction/synthesis task, not open-ended reasoning, and the
    // extra thinking time was adding several seconds to every chat request.
    expect(genParams.generation_config).toEqual({ thinking_level: "low" });
  });

  it("uses a caller-supplied embedding instead of calling Gemini to embed again", async () => {
    const { client, embedContent, create } = fakeGeminiClient([0.1, 0.2], BILINGUAL_ANSWER);
    const { dbClient } = fakeDbClient([EDITORIAL]);
    process.env.GEMINI_API_KEY = "test-key";
    process.env.DATABASE_URL = "postgres://test";

    await generateAnswer(
      "What happened in June 2021?",
      { scope: "issue", issueMonth: "2021-06", intent: "semantic" },
      { client, dbClient, embedding: [0.9, 0.9] }
    );

    expect(embedContent).not.toHaveBeenCalled();
    expect(create).toHaveBeenCalledTimes(1);
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

    const result = await generateAnswer(
      "What is the price of Bitcoin?",
      { scope: "open", intent: "semantic" },
      { client, dbClient }
    );

    expect(result.citations).toEqual([]);
  });

  it("returns a bilingual not-found answer without calling Gemini when search returns nothing", async () => {
    const { client, create } = fakeGeminiClient([0.1], "should not be used");
    const { dbClient } = fakeDbClient([]);
    process.env.GEMINI_API_KEY = "test-key";
    process.env.DATABASE_URL = "postgres://test";

    const result = await generateAnswer("Anything about widgets?", { scope: "open", intent: "semantic" }, { client, dbClient });

    expect(result.answerEnglish).toMatch(/not find sufficient information/i);
    expect(result.answerMarathi.length).toBeGreaterThan(0);
    expect(result.citations).toEqual([]);
    expect(create).not.toHaveBeenCalled();
  });

  it("returns a bilingual not-found answer without calling Gemini when all retrieved evidence is weak", async () => {
    const { client, create } = fakeGeminiClient([0.1], "should not be used");
    const { dbClient } = fakeDbClient([WEAK_MATCH]);
    process.env.GEMINI_API_KEY = "test-key";
    process.env.DATABASE_URL = "postgres://test";

    const result = await generateAnswer(
      "Something only weakly related?",
      { scope: "open", intent: "semantic" },
      { client, dbClient }
    );

    expect(result.answerEnglish).toMatch(/not find sufficient information/i);
    expect(create).not.toHaveBeenCalled();
  });

  it("passes the caller-supplied limit through to search", async () => {
    const { client } = fakeGeminiClient([0.1], BILINGUAL_ANSWER);
    const { dbClient, calls } = fakeDbClient([EDITORIAL]);
    process.env.GEMINI_API_KEY = "test-key";
    process.env.DATABASE_URL = "postgres://test";

    await generateAnswer("question", { scope: "open", intent: "semantic" }, { client, dbClient, limit: 8 });

    expect(calls[0]).toContain(8);
  });
});
