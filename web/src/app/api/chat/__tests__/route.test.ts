import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/gemini/client", () => ({
  buildGeminiClient: vi.fn(() => ({ fake: "client" })),
}));
vi.mock("@/lib/gemini/embed", () => ({
  embedQuery: vi.fn(),
}));
vi.mock("@/lib/gemini/query-router", () => ({
  classifyQuery: vi.fn(),
}));
vi.mock("@/lib/gemini/generate-answer", () => ({
  generateAnswer: vi.fn(),
}));

import { embedQuery } from "@/lib/gemini/embed";
import { generateAnswer } from "@/lib/gemini/generate-answer";
import { classifyQuery } from "@/lib/gemini/query-router";
import { clearCache } from "@/lib/query-cache";
import { POST } from "../route";

function jsonRequest(body: unknown): Request {
  return new Request("http://localhost/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

const FAKE_EMBEDDING = [0.1, 0.2, 0.3];

beforeEach(() => {
  vi.mocked(classifyQuery).mockReset();
  vi.mocked(generateAnswer).mockReset();
  vi.mocked(embedQuery).mockReset().mockResolvedValue(FAKE_EMBEDDING);
  clearCache(); // each test starts with no cached answers from a prior test
});

describe("POST /api/chat", () => {
  it("classifies and embeds concurrently, then generates, and returns the issue scope in the response", async () => {
    vi.mocked(classifyQuery).mockResolvedValue({ scope: "issue", issueMonth: "2021-06", intent: "semantic" });
    vi.mocked(generateAnswer).mockResolvedValue({
      answerEnglish: 'MCCIA covered robotics (Sampada, June 2021, "Editorial").',
      answerMarathi: 'MCCIA ने रोबोटिक्सवर काम केले (Sampada, June 2021, "Editorial").',
      citations: [
        { articleId: 1, articleTitle: "Editorial", issueMonth: "2021-06", sourceUrl: "", page: null, pdfPageOffset: null },
      ],
    });

    const response = await POST(jsonRequest({ question: "What was in the June 2021 issue?" }));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.scope).toBe("issue");
    expect(body.issueMonth).toBe("2021-06");
    expect(body.yearFrom).toBeNull();
    expect(body.yearTo).toBeNull();
    expect(body.citations).toHaveLength(1);
    expect(embedQuery).toHaveBeenCalledWith("What was in the June 2021 issue?", expect.anything());
    expect(generateAnswer).toHaveBeenCalledWith(
      "What was in the June 2021 issue?",
      { scope: "issue", issueMonth: "2021-06", intent: "semantic" },
      expect.objectContaining({ embedding: FAKE_EMBEDDING })
    );
  });

  it("returns issueMonth: null for open-scope answers", async () => {
    vi.mocked(classifyQuery).mockResolvedValue({ scope: "open", intent: "semantic" });
    vi.mocked(generateAnswer).mockResolvedValue({ answerEnglish: "answer", answerMarathi: "उत्तर", citations: [] });

    const response = await POST(jsonRequest({ question: "What did MCCIA do during COVID?" }));
    const body = await response.json();

    expect(body.scope).toBe("open");
    expect(body.issueMonth).toBeNull();
    expect(body.yearFrom).toBeNull();
    expect(body.yearTo).toBeNull();
  });

  it("returns yearFrom/yearTo for range-scope answers, and null issueMonth", async () => {
    vi.mocked(classifyQuery).mockResolvedValue({ scope: "range", yearFrom: 1955, yearTo: 1965, intent: "semantic" });
    vi.mocked(generateAnswer).mockResolvedValue({ answerEnglish: "answer", answerMarathi: "उत्तर", citations: [] });

    const response = await POST(jsonRequest({ question: "Find Tata between 1955 and 1965" }));
    const body = await response.json();

    expect(body.scope).toBe("range");
    expect(body.issueMonth).toBeNull();
    expect(body.yearFrom).toBe(1955);
    expect(body.yearTo).toBe(1965);
  });

  it("rejects a missing question with 400 before calling the backend", async () => {
    const response = await POST(jsonRequest({}));
    expect(response.status).toBe(400);
    expect(classifyQuery).not.toHaveBeenCalled();
  });

  it("rejects a blank question with 400", async () => {
    const response = await POST(jsonRequest({ question: "   " }));
    expect(response.status).toBe(400);
  });

  it("rejects a non-JSON body with 400 instead of throwing", async () => {
    const response = await POST(
      new Request("http://localhost/api/chat", { method: "POST", body: "not json" })
    );
    expect(response.status).toBe(400);
  });

  it("returns 500 with a generic message when the backend throws", async () => {
    vi.mocked(classifyQuery).mockRejectedValue(new Error("Gemini is down"));

    const response = await POST(jsonRequest({ question: "anything" }));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body.error).not.toContain("Gemini is down");
  });

  describe("query cache", () => {
    it("serves a repeated identical question from cache without calling classify/embed/generate again", async () => {
      vi.mocked(classifyQuery).mockResolvedValue({ scope: "open", intent: "semantic" });
      vi.mocked(generateAnswer).mockResolvedValue({ answerEnglish: "first answer", answerMarathi: "उत्तर", citations: [] });

      const first = await POST(jsonRequest({ question: "What did MCCIA do during COVID?" }));
      const firstBody = await first.json();
      expect(firstBody.answerEnglish).toBe("first answer");
      expect(classifyQuery).toHaveBeenCalledTimes(1);

      // Change the mocks -- if the cache is bypassed, the response would
      // change too. It shouldn't: this is the same question again.
      vi.mocked(generateAnswer).mockResolvedValue({ answerEnglish: "different answer", answerMarathi: "वेगळे", citations: [] });

      const second = await POST(jsonRequest({ question: "What did MCCIA do during COVID?" }));
      const secondBody = await second.json();

      expect(secondBody.answerEnglish).toBe("first answer");
      expect(classifyQuery).toHaveBeenCalledTimes(1); // still just once
      expect(generateAnswer).toHaveBeenCalledTimes(1); // still just once
    });

    it("treats a differently-cased/whitespaced repeat as the same cached question", async () => {
      vi.mocked(classifyQuery).mockResolvedValue({ scope: "open", intent: "semantic" });
      vi.mocked(generateAnswer).mockResolvedValue({ answerEnglish: "cached answer", answerMarathi: "उत्तर", citations: [] });

      await POST(jsonRequest({ question: "What did MCCIA do during COVID?" }));
      const second = await POST(jsonRequest({ question: "  what did mccia do during covid?  " }));
      const secondBody = await second.json();

      expect(secondBody.answerEnglish).toBe("cached answer");
      expect(classifyQuery).toHaveBeenCalledTimes(1);
    });

    it("does not cache across genuinely different questions", async () => {
      vi.mocked(classifyQuery).mockResolvedValue({ scope: "open", intent: "semantic" });
      vi.mocked(generateAnswer).mockResolvedValue({ answerEnglish: "answer", answerMarathi: "उत्तर", citations: [] });

      await POST(jsonRequest({ question: "Question one?" }));
      await POST(jsonRequest({ question: "Question two?" }));

      expect(classifyQuery).toHaveBeenCalledTimes(2);
    });

    it("does not cache an error response", async () => {
      vi.mocked(classifyQuery).mockRejectedValueOnce(new Error("Gemini is down"));
      vi.mocked(classifyQuery).mockResolvedValue({ scope: "open", intent: "semantic" });
      vi.mocked(generateAnswer).mockResolvedValue({ answerEnglish: "recovered", answerMarathi: "उत्तर", citations: [] });

      const first = await POST(jsonRequest({ question: "flaky question" }));
      expect(first.status).toBe(500);

      const second = await POST(jsonRequest({ question: "flaky question" }));
      const secondBody = await second.json();

      expect(second.status).toBe(200);
      expect(secondBody.answerEnglish).toBe("recovered");
      expect(classifyQuery).toHaveBeenCalledTimes(2);
    });
  });
});
