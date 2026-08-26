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
  awsRegion: process.env.AWS_REGION ?? "ap-south-1",
  // Claude has no native in-region hosting in ap-south-1 -- this must be a
  // "global." cross-region inference profile ARN (RetrieveAndGenerate's
  // modelArn field requires an ARN; Converse's modelId field accepts one
  // too, so this one value covers both). See sampada/README.md.
  get bedrockModelArn(): string {
    return requireEnv("BEDROCK_MODEL_ARN");
  },
  get knowledgeBaseId(): string {
    return requireEnv("BEDROCK_KNOWLEDGE_BASE_ID");
  },
  get s3Bucket(): string {
    return requireEnv("S3_BUCKET");
  },

  // Gemini + Neon (the new retrieval layer) -- see sampada/README.md.
  get geminiApiKey(): string {
    return requireEnv("GEMINI_API_KEY");
  },
  get databaseUrl(): string {
    return requireEnv("DATABASE_URL");
  },
};
