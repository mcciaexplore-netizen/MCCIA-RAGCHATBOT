"use client";

import { useState } from "react";
import {
  clearConversations,
  deleteConversation,
  loadConversations,
  saveConversation,
  titleFromQuestion,
  type ConversationRecord,
} from "@/lib/conversation-history";
import type { ChatMessage } from "@/lib/types";
import { ChatInterface } from "./ChatInterface";
import type { SourceTarget } from "./CitationTag";
import { HistorySidebar } from "./HistorySidebar";
import { SourceViewer } from "./SourceViewer";

function newConversationId(): string {
  return crypto.randomUUID();
}

function MenuIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" className="h-5 w-5">
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  );
}

/** Composes the three-panel desktop layout (recent searches / chat /
 * original source) and owns the state each panel shares: which
 * conversation is active, and which citation's source page is open. The
 * actual message list for the active conversation lives inside
 * ChatInterface itself -- this only listens for changes so it can persist
 * them, and remounts ChatInterface (via `key`) when switching conversations
 * so its internal state resets cleanly. */
export function ChatShell() {
  // loadConversations() already no-ops to [] when window/localStorage isn't
  // available (SSR), so this is safe as a lazy initializer -- no effect
  // needed just to populate it after mount.
  const [conversations, setConversations] = useState<ConversationRecord[]>(() => loadConversations());
  const [activeId, setActiveId] = useState<string>(() => newConversationId());
  const [initialMessages, setInitialMessages] = useState<ChatMessage[]>([]);
  const [sourceTarget, setSourceTarget] = useState<SourceTarget | null>(null);
  const [isHistoryOpenOnMobile, setIsHistoryOpenOnMobile] = useState(false);
  // The source panel (even its empty "click a citation" placeholder) has
  // nothing to do until a conversation actually exists -- on the landing
  // page it would just be dead space next to the hero/example prompts.
  const [hasConversationStarted, setHasConversationStarted] = useState(false);

  function handleConversationUpdate(messages: ChatMessage[]) {
    setHasConversationStarted(messages.length > 0);
    const firstUserMessage = messages.find((m): m is Extract<ChatMessage, { role: "user" }> => m.role === "user");
    const existing = conversations.find((c) => c.id === activeId);
    const record: ConversationRecord = {
      id: activeId,
      title: firstUserMessage ? titleFromQuestion(firstUserMessage.content) : "New search",
      createdAt: existing?.createdAt ?? Date.now(),
      updatedAt: Date.now(),
      messages,
    };
    saveConversation(record);
    setConversations(loadConversations());
  }

  function handleNewSearch() {
    setActiveId(newConversationId());
    setInitialMessages([]);
    setSourceTarget(null);
    setIsHistoryOpenOnMobile(false);
    setHasConversationStarted(false);
  }

  function handleSelectConversation(id: string) {
    setIsHistoryOpenOnMobile(false);
    if (id === activeId) return;
    const conversation = conversations.find((c) => c.id === id);
    if (!conversation) return;
    setActiveId(id);
    setInitialMessages(conversation.messages);
    setSourceTarget(null);
    setHasConversationStarted(conversation.messages.length > 0);
  }

  function handleDeleteConversation(id: string) {
    deleteConversation(id);
    setConversations(loadConversations());
    if (id === activeId) handleNewSearch();
  }

  function handleClearAll() {
    clearConversations();
    setConversations([]);
    handleNewSearch();
  }

  return (
    <div className="flex w-full flex-1 overflow-hidden">
      <HistorySidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={handleSelectConversation}
        onNew={handleNewSearch}
        onDelete={handleDeleteConversation}
        onClearAll={handleClearAll}
        isOpenOnMobile={isHistoryOpenOnMobile}
        onCloseMobile={() => setIsHistoryOpenOnMobile(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <button
          type="button"
          onClick={() => setIsHistoryOpenOnMobile(true)}
          aria-label="Show recent searches"
          className="flex items-center gap-2 border-b border-brand-border px-4 py-2.5 text-sm text-brand-text-muted hover:text-brand-text lg:hidden"
        >
          <MenuIcon />
          Recent searches
        </button>
        <ChatInterface
          key={activeId}
          initialMessages={initialMessages}
          onConversationUpdate={handleConversationUpdate}
          onOpenSource={setSourceTarget}
        />
      </div>
      {hasConversationStarted && (
        <SourceViewer
          target={sourceTarget}
          onClose={() => setSourceTarget(null)}
          onNavigate={(page) => setSourceTarget((current) => (current ? { ...current, page } : current))}
        />
      )}
    </div>
  );
}
