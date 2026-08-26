"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import type { ChatApiResponse, ParsedCitation } from "@/lib/types";
import { CitationTag } from "./CitationTag";

type ChatMessage =
  | { id: number; role: "user"; content: string }
  | { id: number; role: "assistant"; content: string; citations: ParsedCitation[] }
  | { id: number; role: "error"; content: string };

// Plain `Omit<ChatMessage, "id">` collapses to only the keys shared across
// every union member (losing `citations`), because `Omit`/`Pick` don't
// distribute over a union on their own -- this does.
type DistributiveOmit<T, K extends keyof T> = T extends unknown ? Omit<T, K> : never;
type NewChatMessage = DistributiveOmit<ChatMessage, "id">;

const TRY_ASKING = [
  {
    label: "Summarize the June 2021 issue",
    question: "Summarize the June 2021 issue of Sampada.",
    icon: DocumentIcon,
  },
  {
    label: "What initiatives has MCCIA undertaken for MSMEs?",
    question: "What initiatives has MCCIA undertaken for MSMEs?",
    icon: HandshakeIcon,
  },
  {
    label: "Tell me about MCCIA's upcoming events",
    question: "Tell me about MCCIA's upcoming events.",
    icon: CalendarIcon,
  },
  {
    label: "What were the major highlights in the latest issue?",
    question: "What were the major highlights in the latest issue?",
    icon: ChartIcon,
  },
];

const EXPLORE_CATEGORIES: Array<
  | { label: string; icon: IconComponent; href: string; question?: undefined }
  | { label: string; icon: IconComponent; question: string; href?: undefined }
> = [
  { label: "Issues", icon: DocumentIcon, href: "/archive" },
  { label: "Industry", icon: FactoryIcon, question: "What has MCCIA covered about industry trends and developments?" },
  { label: "Events", icon: CalendarIcon, question: "What events has MCCIA organized or covered?" },
  { label: "Initiatives", icon: LightbulbIcon, question: "What initiatives has MCCIA launched?" },
  { label: "MSME", icon: HandshakeIcon, question: "What has MCCIA done for MSMEs?" },
  { label: "Policy", icon: ShieldIcon, question: "What policy matters has MCCIA addressed?" },
  { label: "Members", icon: PersonIcon, question: "What member stories has Sampada featured?" },
  { label: "Technology", icon: MonitorIcon, question: "What technology topics has Sampada covered?" },
];

type IconComponent = () => React.JSX.Element;

function ArrowIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-6 w-6"
    >
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" className="h-6 w-6 shrink-0">
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}

function PaperclipIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6 shrink-0">
      <path d="M21.44 11.05 12.25 20.24a5 5 0 0 1-7.07-7.07l8.5-8.49a3.5 3.5 0 0 1 4.95 4.95l-8.5 8.49a2 2 0 0 1-2.83-2.83l7.78-7.78" />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6 shrink-0">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0M12 19v3" />
    </svg>
  );
}

function DocumentIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7 shrink-0 text-brand-primary">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6M9 13h6M9 17h6" />
    </svg>
  );
}

function HandshakeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7 shrink-0 text-brand-primary">
      <circle cx="8" cy="8" r="3" />
      <circle cx="16" cy="8" r="3" />
      <path d="M3 20c0-3 2.5-5 5-5s5 2 5 5M11 20c0-3 2.5-5 5-5s5 2 5 5" />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7 shrink-0 text-brand-primary">
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <path d="M16 2v4M8 2v4M3 10h18" />
      <circle cx="12" cy="15" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

function ChartIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7 shrink-0 text-brand-primary">
      <path d="M4 20V10M12 20V4M20 20v-7" />
    </svg>
  );
}

function FactoryIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7 shrink-0 text-brand-primary">
      <path d="M3 21V10l6 4v-4l6 4V6l6 4v11H3Z" />
      <path d="M7 21v-4M12 21v-4M17 21v-4" />
    </svg>
  );
}

function LightbulbIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7 shrink-0 text-brand-primary">
      <path d="M9 18h6M10 22h4M12 2a6 6 0 0 0-3.5 10.9c.5.4.8 1 .8 1.6v.5h5.4v-.5c0-.6.3-1.2.8-1.6A6 6 0 0 0 12 2Z" />
    </svg>
  );
}

function ShieldIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7 shrink-0 text-brand-primary">
      <path d="M12 2 4 5v6c0 5 3.4 8.7 8 11 4.6-2.3 8-6 8-11V5l-8-3Z" />
    </svg>
  );
}

function PersonIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7 shrink-0 text-brand-primary">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" />
    </svg>
  );
}

function MonitorIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7 shrink-0 text-brand-primary">
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </svg>
  );
}

export function ChatInterface() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const nextId = useRef(0);

  function addMessage(message: NewChatMessage) {
    const withId = { ...message, id: nextId.current++ } as ChatMessage;
    setMessages((prev) => [...prev, withId]);
  }

  async function ask(question: string) {
    addMessage({ role: "user", content: question });
    setIsLoading(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        addMessage({
          role: "error",
          content: body?.error ?? "Something went wrong answering that question.",
        });
        return;
      }

      const data: ChatApiResponse = await response.json();
      addMessage({ role: "assistant", content: data.answer, citations: data.citations });
    } catch {
      addMessage({
        role: "error",
        content: "Couldn't reach Sampada's assistant. Check your connection and try again.",
      });
    } finally {
      setIsLoading(false);
    }
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const question = input.trim();
    if (!question || isLoading) return;
    setInput("");
    void ask(question);
  }

  return (
    <div className="flex w-full flex-1 flex-col px-12 py-12 sm:px-20 sm:py-20">
      {messages.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-12 text-center">
          <div className="flex flex-col items-center gap-4">
            <h1 className="font-heading text-7xl font-extrabold leading-[1.05] tracking-tight sm:text-8xl lg:text-9xl">
              <span className="text-slate-900">Ask </span>
              <span className="text-brand-primary">MCCI</span>
              <span className="text-brand-accent">A</span>
            </h1>
            <p className="font-heading text-2xl font-medium text-slate-400 sm:text-3xl">
              Search &amp; explore <span className="italic text-brand-primary">Sampada</span> with AI
            </p>
            <p className="text-lg text-slate-500 sm:text-xl">
              Ask questions about MCCIA activities, events, initiatives, industry updates and more.
            </p>
          </div>

          <form
            onSubmit={handleSubmit}
            className="mx-auto flex w-full max-w-5xl items-center gap-3 rounded-full border border-black/5 bg-white px-6 py-3.5 shadow-2xl"
          >
            <SearchIcon />
            <input
              type="text"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask anything about MCCIA Sampada..."
              disabled={isLoading}
              className="min-w-0 flex-1 bg-transparent py-1.5 text-lg text-slate-900 placeholder:text-slate-400 focus:outline-none disabled:opacity-60"
            />
            <span className="hidden text-slate-300 sm:inline-flex">
              <PaperclipIcon />
            </span>
            <span className="hidden text-slate-300 sm:inline-flex">
              <MicIcon />
            </span>
            <button
              type="submit"
              aria-label="Ask"
              disabled={isLoading || !input.trim()}
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-brand-primary text-white hover:bg-brand-primary-hover disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ArrowIcon />
            </button>
          </form>

          <section className="flex w-full max-w-5xl flex-col items-center gap-6">
            <h2 className="text-3xl font-bold text-slate-900">Try asking</h2>
            <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {TRY_ASKING.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  onClick={() => void ask(item.question)}
                  className="flex flex-col items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-5 text-center shadow-sm hover:border-brand-primary hover:shadow-md"
                >
                  <item.icon />
                  <span className="text-base font-medium text-slate-700">{item.label}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="flex w-full flex-col items-center gap-8">
            <h2 className="text-3xl font-bold text-slate-900">Explore Sampada</h2>
            <div className="flex flex-wrap justify-center gap-4">
              {EXPLORE_CATEGORIES.map((category) =>
                category.href ? (
                  <Link
                    key={category.label}
                    href={category.href}
                    className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-7 py-5 text-lg font-medium text-slate-700 hover:border-brand-primary hover:text-brand-primary"
                  >
                    <category.icon />
                    {category.label}
                  </Link>
                ) : (
                  <button
                    key={category.label}
                    type="button"
                    onClick={() => {
                      if (category.question) void ask(category.question);
                    }}
                    className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-7 py-5 text-lg font-medium text-slate-700 hover:border-brand-primary hover:text-brand-primary"
                  >
                    <category.icon />
                    {category.label}
                  </button>
                )
              )}
            </div>
          </section>

          <div className="flex flex-col items-center gap-2 text-base text-slate-400">
            <p>
              Powered by MCCIA <span className="italic">Sampada</span> archives
            </p>
            <p>
              AI-generated responses may contain inaccuracies. Please verify important information with the
              cited <span className="italic">Sampada</span> issue.
            </p>
          </div>
        </div>
      ) : (
        <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col">
          <ol className="flex flex-1 flex-col gap-4 overflow-y-auto pb-4">
            {messages.map((message) => (
              <li
                key={message.id}
                className={
                  message.role === "user"
                    ? "ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-brand-primary px-6 py-5 text-xl text-white"
                    : message.role === "error"
                      ? "mr-auto max-w-[85%] rounded-2xl rounded-bl-sm border border-brand-accent bg-brand-accent/10 px-6 py-5 text-xl text-brand-text"
                      : "mr-auto max-w-[85%] rounded-2xl rounded-bl-sm border border-brand-border bg-brand-surface px-6 py-5 text-xl text-brand-text"
                }
              >
                <p className="whitespace-pre-wrap">{message.content}</p>
                {message.role === "assistant" && message.citations.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {message.citations.map((citation) => (
                      <CitationTag
                        key={`${citation.issueMonth}-${citation.articleTitle}`}
                        citation={citation}
                      />
                    ))}
                  </div>
                )}
              </li>
            ))}
            {isLoading && (
              <li className="mr-auto max-w-[85%] rounded-2xl rounded-bl-sm border border-brand-border bg-brand-surface px-6 py-5 text-xl text-brand-text-muted">
                Thinking…
              </li>
            )}
          </ol>

          <form onSubmit={handleSubmit} className="mt-4 flex gap-3">
            <input
              type="text"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask about any issue or topic..."
              disabled={isLoading}
              className="flex-1 rounded-full border border-brand-border bg-brand-surface px-6 py-4 text-xl text-brand-text placeholder:text-brand-text-muted disabled:opacity-60"
            />
            <button
              type="submit"
              aria-label="Ask"
              disabled={isLoading || !input.trim()}
              className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-brand-primary text-white hover:bg-brand-primary-hover disabled:cursor-not-allowed disabled:opacity-30"
            >
              <ArrowIcon />
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
