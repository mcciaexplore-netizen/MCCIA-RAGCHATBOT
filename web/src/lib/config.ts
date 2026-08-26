import "server-only";

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
};
