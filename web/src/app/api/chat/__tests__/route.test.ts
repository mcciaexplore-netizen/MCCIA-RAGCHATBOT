import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/bedrock/query-router", () => ({
  classifyQuery: vi.fn(),
}));
vi.mock("@/lib/bedrock/generate-answer", () => ({
  generateAnswer: vi.fn(),
}));

import { generateAnswer } from "@/lib/bedrock/generate-answer";
import { classifyQuery } from "@/lib/bedrock/query-router";
import { POST } from "../route";

function jsonRequest(body: unknown): Request {
  return new Request("http://localhost/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.mocked(classifyQuery).mockReset();
  vi.mocked(generateAnswer).mockReset();
});

describe("POST /api/chat", () => {
  it("classifies then generates, and returns the issue scope in the response", async () => {
    vi.mocked(classifyQuery).mockResolvedValue({ scope: "issue", issueMonth: "2021-06" });
    vi.mocked(generateAnswer).mockResolvedValue({
      answer: 'MCCIA covered robotics (Sampada, June 2021, "Editorial").',
      citations: [{ articleTitle: "Editorial", issueMonth: "2021-06", sourceUrl: "" }],
    });

    const response = await POST(jsonRequest({ question: "What was in the June 2021 issue?" }));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.scope).toBe("issue");
    expect(body.issueMonth).toBe("2021-06");
    expect(body.citations).toHaveLength(1);
    expect(generateAnswer).toHaveBeenCalledWith(
      "What was in the June 2021 issue?",
      { scope: "issue", issueMonth: "2021-06" }
    );
  });

  it("returns issueMonth: null for open-scope answers", async () => {
    vi.mocked(classifyQuery).mockResolvedValue({ scope: "open" });
    vi.mocked(generateAnswer).mockResolvedValue({ answer: "answer", citations: [] });

    const response = await POST(jsonRequest({ question: "What did MCCIA do during COVID?" }));
    const body = await response.json();

    expect(body.scope).toBe("open");
    expect(body.issueMonth).toBeNull();
  });

  it("rejects a missing question with 400 before calling Bedrock", async () => {
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

  it("returns 500 with a generic message when Bedrock throws", async () => {
    vi.mocked(classifyQuery).mockRejectedValue(new Error("Bedrock is down"));

    const response = await POST(jsonRequest({ question: "anything" }));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body.error).not.toContain("Bedrock is down");
  });
});
