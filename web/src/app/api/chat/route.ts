import { NextResponse } from "next/server";
import { z } from "zod";
import { buildGeminiClient } from "@/lib/gemini/client";
import { embedQuery } from "@/lib/gemini/embed";
import { generateAnswer } from "@/lib/gemini/generate-answer";
import { classifyQuery } from "@/lib/gemini/query-router";
import type { ChatApiResponse } from "@/lib/types";

const ChatRequestSchema = z.object({
  question: z.string().trim().min(1).max(2000),
});

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const parsed = ChatRequestSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "Expected a JSON body with a non-empty 'question' string." },
      { status: 400 }
    );
  }

  const { question } = parsed.data;

  try {
    const client = buildGeminiClient();
    // classifyQuery and embedQuery don't depend on each other -- running
    // them concurrently instead of serially shaves a full network
    // round-trip off every request.
    const [route, embedding] = await Promise.all([
      classifyQuery(question, { client }),
      embedQuery(question, { client }),
    ]);
    const { answerEnglish, answerMarathi, citations } = await generateAnswer(question, route, {
      client,
      embedding,
    });

    const body: ChatApiResponse = {
      answerEnglish,
      answerMarathi,
      citations,
      scope: route.scope,
      issueMonth: route.scope === "issue" ? route.issueMonth : null,
    };
    return NextResponse.json(body);
  } catch (error) {
    console.error("[/api/chat] failed to answer question", error);
    return NextResponse.json(
      { error: "Something went wrong answering that question. Please try again." },
      { status: 500 }
    );
  }
}
