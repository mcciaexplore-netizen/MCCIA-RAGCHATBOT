// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ConversationRecord } from "@/lib/conversation-history";
import { HistorySidebar } from "../HistorySidebar";

const CONVERSATIONS: ConversationRecord[] = [
  { id: "a", title: "June 1956 Sampada", createdAt: 1, updatedAt: 2, messages: [] },
  { id: "b", title: "Industrial policy", createdAt: 1, updatedAt: 1, messages: [] },
];

describe("HistorySidebar", () => {
  it("shows an empty-history message when there are no saved conversations", () => {
    render(
      <HistorySidebar
        conversations={[]}
        activeId="x"
        onSelect={() => {}}
        onNew={() => {}}
        onDelete={() => {}}
        onClearAll={() => {}}
      />
    );
    expect(screen.getByText(/your recent searches will appear here/i)).toBeInTheDocument();
    expect(screen.queryByText(/clear history/i)).not.toBeInTheDocument();
  });

  it("lists each conversation's title", () => {
    render(
      <HistorySidebar
        conversations={CONVERSATIONS}
        activeId="a"
        onSelect={() => {}}
        onNew={() => {}}
        onDelete={() => {}}
        onClearAll={() => {}}
      />
    );
    expect(screen.getByText("June 1956 Sampada")).toBeInTheDocument();
    expect(screen.getByText("Industrial policy")).toBeInTheDocument();
  });

  it("calls onSelect with the clicked conversation's id", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <HistorySidebar
        conversations={CONVERSATIONS}
        activeId="a"
        onSelect={onSelect}
        onNew={() => {}}
        onDelete={() => {}}
        onClearAll={() => {}}
      />
    );
    await user.click(screen.getByText("Industrial policy"));
    expect(onSelect).toHaveBeenCalledWith("b");
  });

  it("calls onNew when New Search is clicked", async () => {
    const onNew = vi.fn();
    const user = userEvent.setup();
    render(
      <HistorySidebar
        conversations={CONVERSATIONS}
        activeId="a"
        onSelect={() => {}}
        onNew={onNew}
        onDelete={() => {}}
        onClearAll={() => {}}
      />
    );
    await user.click(screen.getByRole("button", { name: /new search/i }));
    expect(onNew).toHaveBeenCalled();
  });

  it("calls onDelete with the right id, without triggering onSelect", async () => {
    const onDelete = vi.fn();
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <HistorySidebar
        conversations={CONVERSATIONS}
        activeId="a"
        onSelect={onSelect}
        onNew={() => {}}
        onDelete={onDelete}
        onClearAll={() => {}}
      />
    );
    await user.click(screen.getByRole("button", { name: /delete "industrial policy"/i }));
    expect(onDelete).toHaveBeenCalledWith("b");
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("calls onClearAll when Clear history is clicked", async () => {
    const onClearAll = vi.fn();
    const user = userEvent.setup();
    render(
      <HistorySidebar
        conversations={CONVERSATIONS}
        activeId="a"
        onSelect={() => {}}
        onNew={() => {}}
        onDelete={() => {}}
        onClearAll={onClearAll}
      />
    );
    await user.click(screen.getByRole("button", { name: /clear history/i }));
    expect(onClearAll).toHaveBeenCalled();
  });

  it("marks the active conversation for assistive tech", () => {
    render(
      <HistorySidebar
        conversations={CONVERSATIONS}
        activeId="a"
        onSelect={() => {}}
        onNew={() => {}}
        onDelete={() => {}}
        onClearAll={() => {}}
      />
    );
    expect(screen.getByText("June 1956 Sampada").closest("button")).toHaveAttribute("aria-current", "true");
    expect(screen.getByText("Industrial policy").closest("button")).toHaveAttribute("aria-current", "false");
  });
});
