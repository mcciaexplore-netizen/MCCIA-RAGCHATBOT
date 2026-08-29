import "server-only";
import path from "node:path";

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `${name} is not set. Copy .env.example to .env.local and fill it in.`
    );
  }
  return value;
}

export const config = {
  get geminiApiKey(): string {
    return requireEnv("GEMINI_API_KEY");
  },
  get databaseUrl(): string {
    return requireEnv("DATABASE_URL");
  },
  // The Python ingestion pipeline (staging/, ingest/, .venv/) lives one level
  // up from this Next.js app's own directory -- see source-preview.ts, the
  // only module that needs to reach it. Overridable for a deployment where
  // that layout doesn't hold; defaults to the sibling directory `next dev`/
  // `next build` are actually run from in this repo.
  get archiveRootDir(): string {
    return process.env.ARCHIVE_ROOT_DIR ?? path.resolve(process.cwd(), "..");
  },
};
