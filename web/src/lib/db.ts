import "server-only";
import { neon, type NeonQueryFunction } from "@neondatabase/serverless";
import { config } from "@/lib/config";

// A single place that knows how to talk to Neon -- swapping the retrieval
// layer's backing store later (Aurora pgvector, a Bedrock Knowledge Base)
// means changing this module (and the Python side's db/connection.py), not
// code scattered through the app. Mirrors db/connection.py's role on the
// ingestion side.
export function getDb(): NeonQueryFunction<false, false> {
  return neon(config.databaseUrl);
}

/** pgvector has no native binary type in the Neon HTTP driver -- format the
 * embedding as a bracketed literal and let the query cast it with `::vector`.
 */
export function toVectorLiteral(embedding: number[]): string {
  return `[${embedding.join(",")}]`;
}
