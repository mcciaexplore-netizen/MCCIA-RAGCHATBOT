// Recent-conversation history, kept entirely in the browser's own
// localStorage. There is no server-side history yet -- employee
// authentication doesn't exist (see the standing local-only/deployment
// note), so nothing here is ever written to Neon, logged server-side, or
// sent to Gemini merely to display it. Reading/writing localStorage can
// throw (private browsing, blocked storage, a full quota) -- every function
// here degrades to "no history" rather than crashing the chat over it.

import type { ChatMessage } from "@/lib/types";

const STORAGE_KEY = "mccia-google:conversations:v1";
const MAX_CONVERSATIONS = 50;

export type ConversationRecord = {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
};

function readRaw(): ConversationRecord[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ConversationRecord[]) : [];
  } catch {
    return [];
  }
}

function writeRaw(conversations: ConversationRecord[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations.slice(0, MAX_CONVERSATIONS)));
  } catch {
    // Storage full or blocked -- history is a convenience, never worth
    // crashing the chat over.
  }
}

/** Newest first. */
export function loadConversations(): ConversationRecord[] {
  return [...readRaw()].sort((a, b) => b.updatedAt - a.updatedAt);
}

export function saveConversation(record: ConversationRecord): void {
  const others = readRaw().filter((c) => c.id !== record.id);
  writeRaw([record, ...others]);
}

export function deleteConversation(id: string): void {
  writeRaw(readRaw().filter((c) => c.id !== id));
}

export function clearConversations(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore -- nothing to clean up if storage was never writable
  }
}

const LEADING_QUESTION_WORDS =
  /^(what|how|who|when|where|why|which|did|does|do|is|are|was|were|has|have|had|can|could|should|show me|tell me about|explain)\s+/i;
const LEADING_FILLER = /^(about|regarding|on)\s+/i;
const MAX_TITLE_LENGTH = 42;

/** Mechanical, client-only title from the first question in a conversation
 * -- never a Gemini call (history must never be sent to Gemini just to
 * label it). This is a best-effort trim, not a summary: it strips one
 * leading question word/filler and truncates, so it won't always match a
 * hand-picked example as closely as an LLM-written title would, but it's
 * honest about being mechanical rather than fabricated. */
export function titleFromQuestion(question: string): string {
  let title = question.trim();
  // Loop rather than a single replace -- "What did X" strips to "did X" in
  // one pass and still reads like a question; only stops once nothing
  // leading matches, e.g. "What did MCCIA do" -> "did MCCIA do" -> "MCCIA do".
  let stripped = true;
  while (stripped) {
    stripped = false;
    const withoutQuestionWord = title.replace(LEADING_QUESTION_WORDS, "");
    const withoutFiller = withoutQuestionWord.replace(LEADING_FILLER, "");
    if (withoutFiller !== title) {
      title = withoutFiller;
      stripped = true;
    }
  }
  title = title.replace(/[?.!]+$/, "").trim();
  if (!title) title = question.trim();
  title = title.charAt(0).toUpperCase() + title.slice(1);
  if (title.length > MAX_TITLE_LENGTH) {
    title = title.slice(0, MAX_TITLE_LENGTH).replace(/\s+\S*$/, "") + "…";
  }
  return title || "New search";
}
