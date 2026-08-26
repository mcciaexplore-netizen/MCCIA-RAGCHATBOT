// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatApiResponse } from "@/lib/types";
import { ChatInterface } from "../ChatInterface";

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body } as Response;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ChatInterface", () => {
  it("shows the empty state with example questions before any message is sent", () => {
    render(<ChatInterface />);
    expect(screen.getByRole("heading", { name: /ask\s*mccia/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "What initiatives has MCCIA undertaken for MSMEs?" })
    ).toBeInTheDocument();
  });

  it("sends the typed question, then renders the answer and its citations", async () => {
    const response: ChatApiResponse = {
      answer: 'MCCIA covered robotics (Sampada, June 2021, "Editorial").',
      citations: [{ articleTitle: "Editorial", issueMonth: "2021-06", sourceUrl: "" }],
      scope: "issue",
      issueMonth: "2021-06",
    };
    vi.mocked(fetch).mockResolvedValue(jsonResponse(response));

    const user = userEvent.setup();
    render(<ChatInterface />);

    await user.type(screen.getByPlaceholderText(/ask anything about mccia sampada|ask about any issue/i), "What was in June 2021?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(screen.getByText("What was in June 2021?")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/MCCIA covered robotics/)).toBeInTheDocument());
    expect(screen.getByText("June 2021 — Editorial")).toBeInTheDocument();

    expect(fetch).toHaveBeenCalledWith(
      "/api/chat",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ question: "What was in June 2021?" }),
      })
    );
  });

  it("clicking an example question asks it directly", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ answer: "answer", citations: [], scope: "open", issueMonth: null })
    );
    const user = userEvent.setup();
    render(<ChatInterface />);

    await user.click(screen.getByRole("button", { name: "What initiatives has MCCIA undertaken for MSMEs?" }));

    expect(screen.getByText("What initiatives has MCCIA undertaken for MSMEs?")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("answer")).toBeInTheDocument());
  });

  it("shows the server's error message when the API call fails", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: "Something went wrong answering that question." }, false, 500)
    );
    const user = userEvent.setup();
    render(<ChatInterface />);

    await user.type(screen.getByPlaceholderText(/ask anything about mccia sampada|ask about any issue/i), "anything");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() =>
      expect(screen.getByText("Something went wrong answering that question.")).toBeInTheDocument()
    );
  });

  it("shows a fallback message when fetch itself throws", async () => {
    vi.mocked(fetch).mockRejectedValue(new Error("network down"));
    const user = userEvent.setup();
    render(<ChatInterface />);

    await user.type(screen.getByPlaceholderText(/ask anything about mccia sampada|ask about any issue/i), "anything");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => expect(screen.getByText(/couldn't reach sampada/i)).toBeInTheDocument());
  });

  it("disables the ask button while a request is in flight", async () => {
    let resolveFetch!: (value: Response) => void;
    vi.mocked(fetch).mockReturnValue(new Promise((resolve) => (resolveFetch = resolve)));

    const user = userEvent.setup();
    render(<ChatInterface />);

    await user.type(screen.getByPlaceholderText(/ask anything about mccia sampada|ask about any issue/i), "anything");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    expect(screen.getByText("Thinking…")).toBeInTheDocument();

    resolveFetch(jsonResponse({ answer: "done", citations: [], scope: "open", issueMonth: null }));
    await waitFor(() => expect(screen.getByText("done")).toBeInTheDocument());

    // The input was cleared after submit, so the button is disabled again --
    // for "no text typed", not for "still loading". Type something to check
    // the loading-disable specifically was lifted.
    await user.type(screen.getByPlaceholderText(/ask anything about mccia sampada|ask about any issue/i), "again");
    expect(screen.getByRole("button", { name: "Ask" })).not.toBeDisabled();
  });
});
