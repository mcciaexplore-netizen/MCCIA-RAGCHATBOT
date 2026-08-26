import "server-only";
import type { GoogleGenAI } from "@google/genai";
import { buildGeminiClient } from "@/lib/gemini/client";
import { EMBEDDING_DIMENSIONS, GEMINI_EMBED_MODEL } from "@/lib/gemini/models";

/** L2-normalizes the vector -- Google's docs note gemini-embedding-001
 * doesn't auto-normalize at a non-default dimensionality (only
 * gemini-embedding-2 does). Cosine distance is scale-invariant either way,
 * but this matches the treatment ingest/embeddings.py gives chunk
 * embeddings on the Python side, and costs nothing.
 */
function normalize(vector: number[]): number[] {
  const magnitude = Math.sqrt(vector.reduce((sum, v) => sum + v * v, 0));
  if (magnitude === 0) return vector;
  return vector.map((v) => v / magnitude);
}

/** Embeds the user's question (Phase 4 step 1) with the "query" side of
 * Gemini's asymmetric retrieval embeddings -- chunks were indexed with
 * RETRIEVAL_DOCUMENT (see ingest/embeddings.py), so the question must use
 * RETRIEVAL_QUERY for the two to compare meaningfully.
 */
export async function embedQuery(
  text: string,
  opts?: { client?: GoogleGenAI }
): Promise<number[]> {
  const client = opts?.client ?? buildGeminiClient();

  const response = await client.models.embedContent({
    model: GEMINI_EMBED_MODEL,
    contents: [text],
    config: {
      taskType: "RETRIEVAL_QUERY",
      outputDimensionality: EMBEDDING_DIMENSIONS,
    },
  });

  const values = response.embeddings?.[0]?.values;
  if (!values) {
    throw new Error("Gemini embedding response had no values");
  }
  return normalize(values);
}
