import { describe, expect, it, vi } from "vitest";
import { classifyQuery, parseClassification, tryDeterministicClassify } from "../query-router";

describe("parseClassification", () => {
  it("returns issue scope with a well-formed issue_month", () => {
    const route = parseClassification(
      JSON.stringify({ scope: "issue", issue_month: "2021-06", intent: "semantic" })
    );
    expect(route).toEqual({ scope: "issue", issueMonth: "2021-06", intent: "semantic" });
  });

  it("falls back to open when scope is issue but issue_month is missing", () => {
    const route = parseClassification(JSON.stringify({ scope: "issue", intent: "semantic" }));
    expect(route).toEqual({ scope: "open", intent: "semantic" });
  });

  it("falls back to open when issue_month is malformed", () => {
    const route = parseClassification(
      JSON.stringify({ scope: "issue", issue_month: "June 2021", intent: "semantic" })
    );
    expect(route).toEqual({ scope: "open", intent: "semantic" });
  });

  it("falls back to open when the JSON doesn't match the schema at all", () => {
    const route = parseClassification(JSON.stringify({ nonsense: true }));
    expect(route).toEqual({ scope: "open", intent: "semantic" });
  });

  it("falls back to open when the response isn't valid JSON", () => {
    const route = parseClassification("not json at all");
    expect(route).toEqual({ scope: "open", intent: "semantic" });
  });

  it("returns open scope as-is", () => {
    const route = parseClassification(JSON.stringify({ scope: "open", intent: "semantic" }));
    expect(route).toEqual({ scope: "open", intent: "semantic" });
  });

  it("defaults intent to semantic when the model omits it", () => {
    const route = parseClassification(JSON.stringify({ scope: "open" }));
    expect(route).toEqual({ scope: "open", intent: "semantic" });
  });

  it("throws if Gemini returns no output text", () => {
    expect(() => parseClassification(undefined)).toThrow(/no output text/);
  });

  describe("range scope", () => {
    it("returns a well-formed year range", () => {
      const route = parseClassification(
        JSON.stringify({ scope: "range", year_from: 1955, year_to: 1965, intent: "semantic" })
      );
      expect(route).toEqual({ scope: "range", yearFrom: 1955, yearTo: 1965, intent: "semantic" });
    });

    it("accepts a single named year as a range with equal bounds", () => {
      const route = parseClassification(
        JSON.stringify({ scope: "range", year_from: 1960, year_to: 1960, intent: "semantic" })
      );
      expect(route).toEqual({ scope: "range", yearFrom: 1960, yearTo: 1960, intent: "semantic" });
    });

    it("falls back to open when year_from is missing", () => {
      const route = parseClassification(JSON.stringify({ scope: "range", year_to: 1965, intent: "semantic" }));
      expect(route).toEqual({ scope: "open", intent: "semantic" });
    });

    it("falls back to open when year_from is after year_to", () => {
      const route = parseClassification(
        JSON.stringify({ scope: "range", year_from: 1970, year_to: 1960, intent: "semantic" })
      );
      expect(route).toEqual({ scope: "open", intent: "semantic" });
    });

    it("falls back to open when a year is outside the archive's real span", () => {
      const route = parseClassification(
        JSON.stringify({ scope: "range", year_from: 1800, year_to: 1900, intent: "semantic" })
      );
      expect(route).toEqual({ scope: "open", intent: "semantic" });
    });

    it("falls back to open when a year isn't an integer", () => {
      const route = parseClassification(
        JSON.stringify({ scope: "range", year_from: 1960.5, year_to: 1965, intent: "semantic" })
      );
      expect(route).toEqual({ scope: "open", intent: "semantic" });
    });
  });

  describe("search_terms", () => {
    it("carries alternate-spelling/script variants through as searchTerms", () => {
      const route = parseClassification(
        JSON.stringify({ scope: "open", intent: "exact", search_terms: ["Ogale", "Ogle", "ओगले"] })
      );
      expect(route).toEqual({ scope: "open", intent: "exact", searchTerms: ["Ogale", "Ogle", "ओगले"] });
    });

    it("omits searchTerms entirely when the model doesn't supply any", () => {
      const route = parseClassification(JSON.stringify({ scope: "open", intent: "semantic" }));
      expect(route).not.toHaveProperty("searchTerms");
    });

    it("omits searchTerms when the model returns an empty array", () => {
      const route = parseClassification(JSON.stringify({ scope: "open", intent: "exact", search_terms: [] }));
      expect(route).not.toHaveProperty("searchTerms");
    });

    it("drops blank entries from search_terms", () => {
      const route = parseClassification(
        JSON.stringify({ scope: "open", intent: "exact", search_terms: ["Ogale", "  ", ""] })
      );
      expect(route).toEqual({ scope: "open", intent: "exact", searchTerms: ["Ogale"] });
    });

    it("caps search_terms at 5 entries even if the model returns more", () => {
      const many = ["a", "b", "c", "d", "e", "f", "g"];
      const route = parseClassification(JSON.stringify({ scope: "open", intent: "exact", search_terms: many }));
      expect(route.searchTerms).toHaveLength(5);
    });

    it("carries searchTerms through for issue scope too", () => {
      const route = parseClassification(
        JSON.stringify({ scope: "issue", issue_month: "1956-07", intent: "exact", search_terms: ["Kirloskar"] })
      );
      expect(route).toEqual({ scope: "issue", issueMonth: "1956-07", intent: "exact", searchTerms: ["Kirloskar"] });
    });
  });

  describe("intent", () => {
    it("passes through an exact intent", () => {
      const route = parseClassification(JSON.stringify({ scope: "open", intent: "exact" }));
      expect(route).toEqual({ scope: "open", intent: "exact" });
    });

    it("passes through a summary intent", () => {
      const route = parseClassification(
        JSON.stringify({ scope: "issue", issue_month: "1956-07", intent: "summary" })
      );
      expect(route).toEqual({ scope: "issue", issueMonth: "1956-07", intent: "summary" });
    });
  });
});

describe("tryDeterministicClassify", () => {
  it("parses 'Sampada July 1956' as an exact issue", () => {
    expect(tryDeterministicClassify("Sampada July 1956")).toEqual({
      scope: "issue",
      issueMonth: "1956-07",
      intent: "semantic",
    });
  });

  it("parses a bare 'July 1956' the same way, with no publication name needed", () => {
    expect(tryDeterministicClassify("July 1956")).toEqual({
      scope: "issue",
      issueMonth: "1956-07",
      intent: "semantic",
    });
  });

  it("detects a summary cue alongside a month+year", () => {
    expect(tryDeterministicClassify("July 1956 summary")).toEqual({
      scope: "issue",
      issueMonth: "1956-07",
      intent: "summary",
    });
  });

  it("parses an explicit 'between X and Y' range", () => {
    expect(tryDeterministicClassify("Find Tata between 1955 and 1965")).toEqual({
      scope: "range",
      yearFrom: 1955,
      yearTo: 1965,
      intent: "semantic",
    });
  });

  it("parses a dash-separated range", () => {
    expect(tryDeterministicClassify("Kirloskar 1960-1970")).toEqual({
      scope: "range",
      yearFrom: 1960,
      yearTo: 1970,
      intent: "semantic",
    });
  });

  it("parses a single bare year as a range with equal bounds", () => {
    expect(tryDeterministicClassify("Tata 1960")).toEqual({
      scope: "range",
      yearFrom: 1960,
      yearTo: 1960,
      intent: "semantic",
    });
  });

  it("always defers to Gemini when an exact/verbatim cue is present, even with a clear date", () => {
    // Exact intent benefits most from Gemini's alias/transliteration
    // generation (see query-router.ts's comment) -- shortcutting this would
    // silently regress cross-script search quality.
    expect(tryDeterministicClassify("exact mentions of Kirloskar in 1960")).toBeNull();
    expect(tryDeterministicClassify("exact mentions of Kirloskar")).toBeNull();
  });

  it("defers to Gemini for two or more unconnected bare years (genuinely ambiguous)", () => {
    expect(tryDeterministicClassify("Compare 1960 and 1970 policies")).toBeNull();
  });

  it("defers to Gemini for a year outside the archive's real span", () => {
    expect(tryDeterministicClassify("What happened in 2021?")).toBeNull();
    expect(tryDeterministicClassify("What happened in 1800?")).toBeNull();
  });

  it("defers to Gemini for a question with no date structure at all", () => {
    expect(tryDeterministicClassify("What did MCCIA do during COVID?")).toBeNull();
  });

  it("is case-insensitive on month names and cue words", () => {
    expect(tryDeterministicClassify("sampada JULY 1956 SUMMARY")).toEqual({
      scope: "issue",
      issueMonth: "1956-07",
      intent: "summary",
    });
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
      JSON.stringify({ scope: "issue", issue_month: "2021-06", intent: "semantic" })
    );
    process.env.GEMINI_API_KEY = "test-key";

    const route = await classifyQuery("What was in the June 2021 issue?", {
      today: "2026-08-26",
      client,
    });

    expect(route).toEqual({ scope: "issue", issueMonth: "2021-06", intent: "semantic" });
    expect(create).toHaveBeenCalledTimes(1);
    const params = create.mock.calls[0][0];
    expect(params.system_instruction).toContain("2026-08-26");
    expect(params.input).toBe("What was in the June 2021 issue?");
    expect(params.response_format).toEqual({
      type: "text",
      mime_type: "application/json",
      schema: expect.objectContaining({ required: ["scope", "intent"] }),
    });
    // Classification is a small bounded task, same rationale as the answer
    // call in generate-answer.ts -- measured live at 3.8-4.4s without this.
    expect(params.generation_config).toEqual({ thinking_level: "low" });
  });

  it("propagates a clear error when Gemini returns no output text", async () => {
    const { client } = fakeClient(undefined as unknown as string);
    process.env.GEMINI_API_KEY = "test-key";

    await expect(classifyQuery("anything", { client })).rejects.toThrow(/no output text/);
  });

  it("skips the Gemini call entirely for a deterministically-parseable question", async () => {
    const { client, create } = fakeClient("should never be read");

    const route = await classifyQuery("Sampada July 1956", { client });

    expect(route).toEqual({ scope: "issue", issueMonth: "1956-07", intent: "semantic" });
    expect(create).not.toHaveBeenCalled();
  });

  it("still calls Gemini for a question the deterministic parser can't confidently handle", async () => {
    const { client, create } = fakeClient(JSON.stringify({ scope: "open", intent: "semantic" }));
    process.env.GEMINI_API_KEY = "test-key";

    await classifyQuery("What did MCCIA do during COVID?", { client });

    expect(create).toHaveBeenCalledTimes(1);
  });
});
