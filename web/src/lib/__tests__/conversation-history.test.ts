// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import type { ChatMessage } from "@/lib/types";
import {
  clearConversations,
  deleteConversation,
  loadConversations,
  saveConversation,
  titleFromQuestion,
  type ConversationRecord,
} from "../conversation-history";

const MESSAGES: ChatMessage[] = [{ id: 0, role: "user", content: "What was in the June 1956 issue?" }];

function record(overrides: Partial<ConversationRecord> = {}): ConversationRecord {
  return {
    id: "c1",
    title: "June 1956 issue",
    createdAt: 1000,
    updatedAt: 1000,
    messages: MESSAGES,
    ...overrides,
  };
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("conversation-history", () => {
  it("saves and reloads a conversation", () => {
    saveConversation(record());
    const loaded = loadConversations();
    expect(loaded).toHaveLength(1);
    expect(loaded[0].id).toBe("c1");
    expect(loaded[0].messages).toEqual(MESSAGES);
  });

  it("returns newest-updated first", () => {
    saveConversation(record({ id: "old", updatedAt: 100 }));
    saveConversation(record({ id: "new", updatedAt: 200 }));
    const loaded = loadConversations();
    expect(loaded.map((c) => c.id)).toEqual(["new", "old"]);
  });

  it("re-saving the same id replaces it rather than duplicating", () => {
    saveConversation(record({ id: "c1", title: "First" }));
    saveConversation(record({ id: "c1", title: "Updated" }));
    const loaded = loadConversations();
    expect(loaded).toHaveLength(1);
    expect(loaded[0].title).toBe("Updated");
  });

  it("deletes one conversation by id, leaving the rest", () => {
    saveConversation(record({ id: "keep" }));
    saveConversation(record({ id: "remove" }));
    deleteConversation("remove");
    const loaded = loadConversations();
    expect(loaded.map((c) => c.id)).toEqual(["keep"]);
  });

  it("clears all history", () => {
    saveConversation(record({ id: "a" }));
    saveConversation(record({ id: "b" }));
    clearConversations();
    expect(loadConversations()).toEqual([]);
  });

  it("degrades to empty history instead of throwing when storage is unreadable", () => {
    const original = window.localStorage.getItem;
    window.localStorage.getItem = () => {
      throw new Error("storage blocked");
    };
    expect(() => loadConversations()).not.toThrow();
    expect(loadConversations()).toEqual([]);
    window.localStorage.getItem = original;
  });
});

describe("titleFromQuestion", () => {
  it("strips leading question words and trailing punctuation", () => {
    expect(titleFromQuestion("What did MCCIA do for MSMEs?")).toBe("MCCIA do for MSMEs");
  });

  it("capitalizes the first letter of the trimmed title", () => {
    expect(titleFromQuestion("How has MCCIA supported members?").charAt(0)).toBe(
      titleFromQuestion("How has MCCIA supported members?").charAt(0).toUpperCase()
    );
  });

  it("truncates a long question with an ellipsis", () => {
    const long = "What are all the industrial policy changes MCCIA has ever documented across every decade?";
    const title = titleFromQuestion(long);
    expect(title.length).toBeLessThanOrEqual(43);
    expect(title.endsWith("…")).toBe(true);
  });

  it("never returns an empty title", () => {
    expect(titleFromQuestion("?")).not.toBe("");
    expect(titleFromQuestion("   ")).not.toBe("");
  });
});
