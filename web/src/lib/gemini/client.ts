import "server-only";
import { GoogleGenAI } from "@google/genai";
import { config } from "@/lib/config";

export function buildGeminiClient(): GoogleGenAI {
  return new GoogleGenAI({ apiKey: config.geminiApiKey });
}
