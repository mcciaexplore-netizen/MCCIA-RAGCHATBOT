import "server-only";
import type { GoogleGenAI } from "@google/genai";
import { z } from "zod";
import { buildGeminiClient } from "@/lib/gemini/client";
import { GEMINI_CLASSIFY_MODEL } from "@/lib/gemini/models";

const ISSUE_MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
export const MIN_YEAR = 1945;
export const MAX_YEAR = 2017;

/** How retrieval should weigh exact/keyword matching against semantic
 * similarity, and how broadly it should gather evidence -- see retrieval.ts.
 * - "exact": the question names a specific term/company/person and wants
 *   verbatim mentions of it ("exact mentions of Kirloskar").
 * - "summary": the question wants a broad overview of an edition or theme,
 *   not a narrow answer ("summarize Sampada July 1956", "what happened in
 *   the July 1956 issue").
 * - "semantic": anything else -- conceptual/thematic questions where
 *   meaning matters more than exact wording.
 */
export type QueryIntent = "exact" | "semantic" | "summary";

// Alternate spellings/scripts of a named entity in the question, for
// SEARCH EXPANSION ONLY -- e.g. "Ogale" -> ["Ogale", "Ogle", "ओगले"] so
// full-text search can find the archive's actual (often Devanagari)
// spelling of a name typed in Latin script. This is never a factual claim
// that two spellings refer to the same real person/company -- see the
// grounding note in generate-answer.ts's system prompt.
const MAX_SEARCH_TERMS = 5;

export type QueryRoute =
  | { scope: "issue"; issueMonth: string; intent: QueryIntent; searchTerms?: string[] }
  | { scope: "range"; yearFrom: number; yearTo: number; intent: QueryIntent; searchTerms?: string[] }
  | { scope: "open"; intent: QueryIntent; searchTerms?: string[] };

const ClassificationSchema = z.object({
  scope: z.enum(["issue", "range", "open"]),
  issue_month: z.string().optional(),
  year_from: z.number().optional(),
  year_to: z.number().optional(),
  intent: z.enum(["exact", "semantic", "summary"]).optional(),
  search_terms: z.array(z.string()).optional(),
});

const CLASSIFICATION_JSON_SCHEMA = {
  type: "object",
  properties: {
    scope: {
      type: "string",
      enum: ["issue", "range", "open"],
      description:
        "'issue' if the question names or clearly pins down one specific issue's month and year. " +
        "'range' if it constrains a year or span of years without one specific month (a single year, " +
        "an explicit span, or a decade). 'open' for anything else -- no year constraint at all.",
    },
    issue_month: {
      type: "string",
      // A prose description alone isn't reliable -- observed against a
      // real Gemini call, "June 2021" (a human date) came back instead of
      // "2021-06" despite the prompt spelling out the format. The pattern
      // constraint plus a concrete example fixes it; parseClassification's
      // regex check stays as defense-in-depth regardless.
      description: "Only when scope is 'issue': that issue's date as YYYY-MM, e.g. \"2021-06\" for June 2021. Never a month name.",
      pattern: "^\\d{4}-(0[1-9]|1[0-2])$",
    },
    year_from: {
      type: "integer",
      description:
        "Only when scope is 'range': the inclusive start year. A single named year (\"in 1960\") sets " +
        "year_from = year_to = 1960. A decade (\"the 1960s\") sets year_from=1960, year_to=1969.",
    },
    year_to: {
      type: "integer",
      description: "Only when scope is 'range': the inclusive end year (see year_from).",
    },
    intent: {
      type: "string",
      enum: ["exact", "semantic", "summary"],
      description:
        "'exact' when the question explicitly wants verbatim/exact mentions of a specific named term, " +
        "company, or person (e.g. \"exact mentions of Kirloskar\"). 'summary' when it wants a broad " +
        "overview of an entire edition or a broad theme, not a narrow answer (e.g. \"summarize Sampada " +
        "July 1956\", \"what happened in the July 1956 issue\"). 'semantic' for everything else.",
    },
    search_terms: {
      type: "array",
      items: { type: "string" },
      maxItems: MAX_SEARCH_TERMS,
      description:
        "Only when the question names a specific person, company, or term to search for: plausible " +
        "alternate spellings AND a Devanagari transliteration of that name, for keyword search only -- " +
        "the archive is 1945-2017 Marathi/Hindi/English text, so a name typed in Latin script often only " +
        "appears in the source in Devanagari. Include the original term itself as one entry. Example: for " +
        "\"Ogale\", return [\"Ogale\", \"Ogle\", \"ओगले\"]. Omit entirely for questions with no specific " +
        "named entity to search for.",
    },
  },
  required: ["scope", "intent"],
};

export function systemPrompt(today: string): string {
  return `You classify questions about Sampada, MCCIA's monthly industrial magazine archive (issues going back 70+ years). Today's date is ${today}.

Respond with JSON matching the given schema.

SCOPE:
- "issue" only when the question names or clearly pins down ONE specific issue: an explicit month+year ("June 2021"), or a relative reference resolvable from today's date ("last month's issue", "the latest issue"). Set issue_month to that issue's date in numeric YYYY-MM form -- "June 2021" becomes "2021-06", never the month name.
- "range" when the question constrains a year or span of years without one specific month: a single named year ("in 1960"), an explicit span ("between 1955 and 1965"), or a decade ("the 1960s", "during the 1970s"). Set year_from/year_to as the inclusive bounds -- a single year sets both to the same value; a decade like "the 1960s" is year_from=1960, year_to=1969.
- "open" for anything else: topics, themes, people, or companies with no year constraint at all.
- If you cannot confidently resolve a specific month or year bound, use "open" rather than guessing.

INTENT (always required):
- "exact" when the question explicitly wants verbatim/exact mentions of one specific named term, company, or person, and nothing broader (e.g. "exact mentions of Kirloskar", "find the exact reference to Tata Motors").
- "summary" when the question wants a broad overview of an entire edition or a broad theme spanning many sources, not a narrow answer (e.g. "summarize Sampada July 1956", "what happened in the July 1956 issue", "what was discussed about exports during the 1960s").
- "semantic" for everything else -- conceptual or thematic questions where meaning matters more than exact wording (e.g. "what did Sampada say about Tata in 1960").

SEARCH_TERMS: when the question names a specific person, company, or term (most relevant for "exact" intent, but useful whenever one is named), list a few plausible spelling variants AND a Devanagari transliteration -- the archive is 70+ years of Marathi/Hindi/English text, and a name typed in Latin script often appears in the source only in Devanagari. This is for search only, never a claim that the variants are confirmed to be the same real-world entity.`;
}

/** Pure parsing of the model's raw JSON text -- no network access, so this
 * is unit-testable without a live Gemini call. Falls back to open/semantic
 * whenever the model's answer is malformed or inconsistent, rather than
 * risking a broken SQL filter that would silently return zero results.
 */
export function parseClassification(outputText: string | undefined): QueryRoute {
  if (!outputText) {
    throw new Error("Gemini response had no output text");
  }

  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(outputText);
  } catch {
    return { scope: "open", intent: "semantic" };
  }

  const result = ClassificationSchema.safeParse(parsedJson);
  if (!result.success) return { scope: "open", intent: "semantic" };

  const { scope, issue_month, year_from, year_to } = result.data;
  const intent = result.data.intent ?? "semantic";
  const searchTerms = result.data.search_terms?.filter((t) => t.trim().length > 0).slice(0, MAX_SEARCH_TERMS);
  const searchTermsField = searchTerms && searchTerms.length > 0 ? { searchTerms } : {};

  if (scope === "issue" && issue_month && ISSUE_MONTH_RE.test(issue_month)) {
    return { scope: "issue", issueMonth: issue_month, intent, ...searchTermsField };
  }

  if (
    scope === "range" &&
    typeof year_from === "number" &&
    typeof year_to === "number" &&
    Number.isInteger(year_from) &&
    Number.isInteger(year_to) &&
    year_from <= year_to &&
    year_from >= MIN_YEAR &&
    year_to <= MAX_YEAR
  ) {
    return { scope: "range", yearFrom: year_from, yearTo: year_to, intent, ...searchTermsField };
  }

  return { scope: "open", intent, ...searchTermsField };
}

// --- Deterministic fast path -------------------------------------------
//
// Skips the ~4s Gemini classification call entirely for the subset of
// questions where scope/intent are unambiguous from date structure alone --
// measured live, this is the single largest fixed cost on every fresh
// request after answer generation itself. Deliberately narrow: this never
// tries to replace the Gemini classifier, only to shortcut it. Two
// consequences worth being explicit about:
//   1. It never determines "exact" intent, and always defers to Gemini when
//      an explicit exact/verbatim cue is present -- exact intent is exactly
//      where Gemini's alias/transliteration generation (search_terms, see
//      above) matters most, measured previously to be the difference
//      between 0 and 119 real full-text matches for a cross-script name.
//      Shortcutting that case would silently regress search quality.
//   2. A deterministically-parsed route never carries searchTerms (no
//      aliasing without Gemini) -- retrieval.ts already falls back to the
//      raw question text for full-text ranking when searchTerms is absent,
//      so this degrades gracefully rather than breaking.
const MONTH_NAMES: Record<string, number> = {
  jan: 1, january: 1,
  feb: 2, february: 2,
  mar: 3, march: 3,
  apr: 4, april: 4,
  may: 5,
  jun: 6, june: 6,
  jul: 7, july: 7,
  aug: 8, august: 8,
  sep: 9, sept: 9, september: 9,
  oct: 10, october: 10,
  nov: 11, november: 11,
  dec: 12, december: 12,
};

const MONTH_YEAR_RE = new RegExp(`\\b(${Object.keys(MONTH_NAMES).join("|")})\\.?\\s+(\\d{4})\\b`, "i");
const EXPLICIT_RANGE_RE = /\bbetween\s+(\d{4})\s+and\s+(\d{4})\b/i;
const DASH_RANGE_RE = /\b(\d{4})\s*(?:-|–|—|to)\s*(\d{4})\b/i;
const BARE_YEAR_RE = /\b(\d{4})\b/g;
const SUMMARY_CUE_RE = /\b(summary|summarize|summarise|overview)\b/i;
const EXACT_CUE_RE = /\bexact(ly)?\b/i;

function isPlausibleYear(year: number): boolean {
  return Number.isInteger(year) && year >= MIN_YEAR && year <= MAX_YEAR;
}

/** Returns a confident QueryRoute for an unambiguous date pattern, or null
 * to fall back to the Gemini classifier. Exported for direct unit testing,
 * same pattern as parseClassification.
 */
export function tryDeterministicClassify(question: string): QueryRoute | null {
  if (EXACT_CUE_RE.test(question)) return null; // always defer -- see note above

  const intent: QueryIntent = SUMMARY_CUE_RE.test(question) ? "summary" : "semantic";

  const monthMatch = question.match(MONTH_YEAR_RE);
  if (monthMatch) {
    const month = MONTH_NAMES[monthMatch[1].toLowerCase()];
    const year = Number(monthMatch[2]);
    if (isPlausibleYear(year)) {
      return { scope: "issue", issueMonth: `${year}-${String(month).padStart(2, "0")}`, intent };
    }
  }

  const explicitRange = question.match(EXPLICIT_RANGE_RE);
  if (explicitRange) {
    const yearFrom = Number(explicitRange[1]);
    const yearTo = Number(explicitRange[2]);
    if (isPlausibleYear(yearFrom) && isPlausibleYear(yearTo) && yearFrom <= yearTo) {
      return { scope: "range", yearFrom, yearTo, intent };
    }
  }

  const dashRange = question.match(DASH_RANGE_RE);
  if (dashRange) {
    const yearFrom = Number(dashRange[1]);
    const yearTo = Number(dashRange[2]);
    if (isPlausibleYear(yearFrom) && isPlausibleYear(yearTo) && yearFrom <= yearTo) {
      return { scope: "range", yearFrom, yearTo, intent };
    }
  }

  // A single bare year, and only exactly one -- two or more unconnected
  // years ("compare 1960 and 1970") is genuinely ambiguous about what
  // range (if any) is meant, so that case correctly falls through to Gemini
  // rather than guessing.
  const allYears = [...question.matchAll(BARE_YEAR_RE)].map((m) => Number(m[1])).filter(isPlausibleYear);
  if (allYears.length === 1) {
    return { scope: "range", yearFrom: allYears[0], yearTo: allYears[0], intent };
  }

  return null;
}

export async function classifyQuery(
  question: string,
  opts?: { today?: string; client?: GoogleGenAI }
): Promise<QueryRoute> {
  const deterministic = tryDeterministicClassify(question);
  if (deterministic) return deterministic;

  const today = opts?.today ?? new Date().toISOString().slice(0, 10);
  const client = opts?.client ?? buildGeminiClient();

  const interaction = await client.interactions.create({
    model: GEMINI_CLASSIFY_MODEL,
    system_instruction: systemPrompt(today),
    input: question,
    response_format: {
      type: "text",
      mime_type: "application/json",
      schema: CLASSIFICATION_JSON_SCHEMA,
    },
    // Same rationale as generate-answer.ts's answer call: classification is
    // a small bounded extraction task (pick scope/intent/year bounds from
    // one question), not open-ended reasoning -- measured live, this call
    // was taking 3.8-4.4s on its own, disproportionate to the task, with
    // no default-thinking override in place unlike the answer call.
    generation_config: { thinking_level: "low" },
  });

  return parseClassification(interaction.output_text);
}
