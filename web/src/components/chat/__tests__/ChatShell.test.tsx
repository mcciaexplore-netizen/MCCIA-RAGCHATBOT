// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "@/lib/types";
import { loadConversations } from "@/lib/conversation-history";

// ChatShell only needs to orchestrate state between these three -- stub
// them so this test exercises ChatShell's own wiring, not ChatInterface's
// fetch/rendering logic (covered separately in ChatInterface.test.tsx) or
// SourceViewer's fetch logic (covered in SourceViewer.test.tsx).
vi.mock("../ChatInterface", () => ({
  ChatInterface: ({
    initialMessages,
    onConversationUpdate,
    onOpenSource,
  }: {
    initialMessages?: ChatMessage[];
    onConversationUpdate?: (messages: ChatMessage[]) => void;
    onOpenSource?: (t: { issueMonth: string; page: number; articleTitle: string }) => void;
  }) => (
    <div>
      <p data-testid="message-count">{initialMessages?.length ?? 0}</p>
      <button onClick={() => onConversationUpdate?.([{ id: 0, role: "user", content: "What was in June 1956?" }])}>
        simulate-ask
      </button>
      <button onClick={() => onOpenSource?.({ issueMonth: "1956-06", page: 37, articleTitle: "Editorial" })}>
        simulate-citation-click
      </button>
    </div>
  ),
}));

const { ChatShell } = await import("../ChatShell");

beforeEach(() => {
  window.localStorage.clear();
  // SourceViewer fetches independently once a citation is opened -- never
  // let that hit a real network call in this orchestration-focused test
  // (SourceViewer's own fetch behavior is covered in SourceViewer.test.tsx).
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
  vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:fake"), revokeObjectURL: vi.fn() });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ChatShell", () => {
  it("shows no recent searches before any conversation exists", () => {
    render(<ChatShell />);
    expect(screen.getByText(/your recent searches will appear here/i)).toBeInTheDocument();
  });

  it("persists a conversation to local history once ChatInterface reports an update", async () => {
    const user = userEvent.setup();
    render(<ChatShell />);

    await user.click(screen.getByText("simulate-ask"));

    const saved = loadConversations();
    expect(saved).toHaveLength(1);
    expect(saved[0].title).toBe("In June 1956"); // mechanical trim of "What was in June 1956?"
    expect(screen.getByText("In June 1956")).toBeInTheDocument(); // now shows in the sidebar
  });

  it("New Search starts a fresh conversation without erasing prior history", async () => {
    const user = userEvent.setup();
    render(<ChatShell />);

    await user.click(screen.getByText("simulate-ask"));
    expect(loadConversations()).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: /new search/i }));

    // The previous conversation is still saved...
    expect(loadConversations()).toHaveLength(1);
    // ...but the active view is a fresh, empty one.
    expect(screen.getByTestId("message-count")).toHaveTextContent("0");
  });

  it("selecting a saved conversation reopens its messages", async () => {
    const user = userEvent.setup();
    render(<ChatShell />);

    await user.click(screen.getByText("simulate-ask"));
    await user.click(screen.getByRole("button", { name: /new search/i }));
    expect(screen.getByTestId("message-count")).toHaveTextContent("0");

    await user.click(screen.getByText("In June 1956"));
    expect(screen.getByTestId("message-count")).toHaveTextContent("1");
  });

  it("deleting the active conversation falls back to a new, empty search", async () => {
    const user = userEvent.setup();
    render(<ChatShell />);

    await user.click(screen.getByText("simulate-ask"));
    await user.click(screen.getByRole("button", { name: /delete "in june 1956"/i }));

    expect(loadConversations()).toHaveLength(0);
    expect(screen.getByTestId("message-count")).toHaveTextContent("0");
  });

  it("Clear history removes every saved conversation", async () => {
    const user = userEvent.setup();
    render(<ChatShell />);

    await user.click(screen.getByText("simulate-ask"));
    await user.click(screen.getByRole("button", { name: /clear history/i }));

    expect(loadConversations()).toHaveLength(0);
  });

  it("renders no source panel at all on the landing page, before any conversation exists", () => {
    render(<ChatShell />);
    expect(screen.queryByText(/click a citation to view/i)).not.toBeInTheDocument();
  });

  it("shows the source panel's empty state once a conversation has started", async () => {
    const user = userEvent.setup();
    render(<ChatShell />);

    await user.click(screen.getByText("simulate-ask"));

    expect(screen.getByText(/click a citation to view/i)).toBeInTheDocument();
  });

  it("opening a citation renders the source viewer for that target", async () => {
    const user = userEvent.setup();
    render(<ChatShell />);

    await user.click(screen.getByText("simulate-ask"));
    await user.click(screen.getByText("simulate-citation-click"));

    expect(screen.getByText("Sampada — June 1956")).toBeInTheDocument();
  });

  it("closing the source viewer returns to its empty state, not to no panel at all", async () => {
    const user = userEvent.setup();
    render(<ChatShell />);

    await user.click(screen.getByText("simulate-ask"));
    await user.click(screen.getByText("simulate-citation-click"));
    await user.click(screen.getByRole("button", { name: /close source viewer/i }));

    expect(screen.getByText(/click a citation to view/i)).toBeInTheDocument();
  });

  it("starting a New Search hides the source panel again", async () => {
    const user = userEvent.setup();
    render(<ChatShell />);

    await user.click(screen.getByText("simulate-ask"));
    expect(screen.getByText(/click a citation to view/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /new search/i }));
    expect(screen.queryByText(/click a citation to view/i)).not.toBeInTheDocument();
  });
});
