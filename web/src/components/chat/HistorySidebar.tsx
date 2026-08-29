"use client";

import type { ConversationRecord } from "@/lib/conversation-history";

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" className="h-4 w-4">
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />
    </svg>
  );
}

/** Recent-search history, entirely local to this browser (see
 * conversation-history.ts) -- there is no server-side history yet, so this
 * never reflects another device or another employee's activity.
 *
 * Always visible as a normal column on desktop (lg+); on narrower screens
 * it's a slide-in drawer, closed by default, so it never squeezes the chat
 * or source panels -- see `isOpenOnMobile`/`onCloseMobile`. */
export function HistorySidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
  onClearAll,
  isOpenOnMobile = false,
  onCloseMobile,
}: {
  conversations: ConversationRecord[];
  activeId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onClearAll: () => void;
  isOpenOnMobile?: boolean;
  onCloseMobile?: () => void;
}) {
  return (
    <>
      {isOpenOnMobile && (
        <div className="fixed inset-0 z-40 bg-slate-900/30 lg:hidden" onClick={onCloseMobile} aria-hidden="true" />
      )}
      <aside
        className={`${isOpenOnMobile ? "fixed inset-y-0 left-0 z-50 flex" : "hidden"} w-72 shrink-0 flex-col border-r border-brand-border bg-brand-surface lg:static lg:z-auto lg:flex lg:w-64`}
      >
      <div className="p-3">
        <button
          type="button"
          onClick={onNew}
          className="flex w-full items-center justify-center gap-2 rounded-full bg-brand-primary px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-primary-hover"
        >
          <PlusIcon />
          New Search
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-2">
        <p className="px-2 pb-1 pt-2 text-xs font-medium uppercase tracking-wide text-brand-text-muted">
          Recent searches
        </p>
        {conversations.length === 0 ? (
          <p className="px-2 py-2 text-sm text-brand-text-muted">Your recent searches will appear here.</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {conversations.map((conversation) => (
              <li key={conversation.id} className="group flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => onSelect(conversation.id)}
                  aria-current={conversation.id === activeId}
                  className={
                    conversation.id === activeId
                      ? "flex-1 truncate rounded-lg bg-brand-primary/10 px-3 py-2 text-left text-sm font-medium text-brand-primary"
                      : "flex-1 truncate rounded-lg px-3 py-2 text-left text-sm text-brand-text hover:bg-brand-bg"
                  }
                  title={conversation.title}
                >
                  {conversation.title}
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(conversation.id)}
                  aria-label={`Delete "${conversation.title}"`}
                  className="shrink-0 rounded-md p-1.5 text-brand-text-muted opacity-0 hover:bg-brand-bg hover:text-brand-text group-hover:opacity-100"
                >
                  <TrashIcon />
                </button>
              </li>
            ))}
          </ul>
        )}
      </nav>

      {conversations.length > 0 && (
        <div className="border-t border-brand-border p-2">
          <button
            type="button"
            onClick={onClearAll}
            className="w-full rounded-lg px-3 py-2 text-left text-xs text-brand-text-muted hover:bg-brand-bg hover:text-brand-text"
          >
            Clear history
          </button>
        </div>
      )}
      </aside>
    </>
  );
}
