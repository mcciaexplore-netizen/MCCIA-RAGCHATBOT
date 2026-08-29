// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SourceViewer } from "../SourceViewer";

function imageResponse(headers: Record<string, string> = {}) {
  return {
    ok: true,
    headers: new Headers(headers),
    json: async () => ({}),
    blob: async () => new Blob([new Uint8Array([1, 2, 3])], { type: "image/jpeg" }),
  } as unknown as Response;
}

function errorResponse(message: string, status = 404) {
  return { ok: false, status, headers: new Headers(), json: async () => ({ error: message }) } as unknown as Response;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:fake"), revokeObjectURL: vi.fn() });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SourceViewer", () => {
  it("shows a calm empty state when no citation has been clicked", () => {
    render(<SourceViewer target={null} onClose={() => {}} onNavigate={() => {}} />);
    expect(screen.getByText(/click a citation/i)).toBeInTheDocument();
  });

  it("requests exactly the clicked citation's page, nothing else", async () => {
    vi.mocked(fetch).mockResolvedValue(imageResponse({ "x-sampada-min-page": "1", "x-sampada-max-page": "60" }));
    render(
      <SourceViewer
        target={{ issueMonth: "1956-06", page: 37, articleTitle: "Editorial" }}
        onClose={() => {}}
        onNavigate={() => {}}
      />
    );

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(fetch).toHaveBeenCalledWith("/api/source-preview?issueMonth=1956-06&page=37");
  });

  it("never calls the chat API or anything Gemini-related when opening a citation", async () => {
    vi.mocked(fetch).mockResolvedValue(imageResponse());
    render(
      <SourceViewer
        target={{ issueMonth: "1956-06", page: 37, articleTitle: "Editorial" }}
        onClose={() => {}}
        onNavigate={() => {}}
      />
    );

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    const calledUrls = vi.mocked(fetch).mock.calls.map((c) => String(c[0]));
    expect(calledUrls.every((url) => url.startsWith("/api/source-preview"))).toBe(true);
  });

  it("renders the resolved image and the human-facing label", async () => {
    vi.mocked(fetch).mockResolvedValue(imageResponse({ "x-sampada-min-page": "1", "x-sampada-max-page": "60" }));
    render(
      <SourceViewer
        target={{ issueMonth: "1956-06", page: 37, articleTitle: "Editorial" }}
        onClose={() => {}}
        onNavigate={() => {}}
      />
    );

    expect(await screen.findByRole("img")).toHaveAttribute(
      "alt",
      expect.stringContaining("page 37")
    );
    expect(screen.getByText("Sampada — June 1956")).toBeInTheDocument();
  });

  it("shows a clean message on a not-found response instead of a raw error", async () => {
    vi.mocked(fetch).mockResolvedValue(errorResponse("This edition doesn't have a verified source page mapping yet."));
    render(
      <SourceViewer
        target={{ issueMonth: "1945-07", page: 1, articleTitle: "Editorial" }}
        onClose={() => {}}
        onNavigate={() => {}}
      />
    );

    expect(await screen.findByText("This edition doesn't have a verified source page mapping yet.")).toBeInTheDocument();
  });

  it("disables Previous at the minimum page and Next at the maximum page", async () => {
    vi.mocked(fetch).mockResolvedValue(imageResponse({ "x-sampada-min-page": "3", "x-sampada-max-page": "60" }));
    render(
      <SourceViewer
        target={{ issueMonth: "1956-06", page: 3, articleTitle: "Editorial" }}
        onClose={() => {}}
        onNavigate={() => {}}
      />
    );

    await screen.findByRole("img");
    expect(screen.getByRole("button", { name: /previous page/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /next page/i })).not.toBeDisabled();
  });

  it("calls onNavigate with page + 1 when Next is clicked", async () => {
    vi.mocked(fetch).mockResolvedValue(imageResponse({ "x-sampada-min-page": "1", "x-sampada-max-page": "60" }));
    const onNavigate = vi.fn();
    const user = userEvent.setup();
    render(
      <SourceViewer
        target={{ issueMonth: "1956-06", page: 37, articleTitle: "Editorial" }}
        onClose={() => {}}
        onNavigate={onNavigate}
      />
    );

    await user.click(await screen.findByRole("button", { name: /next page/i }));
    expect(onNavigate).toHaveBeenCalledWith(38);
  });

  it("calls onClose when the close button is clicked", async () => {
    vi.mocked(fetch).mockResolvedValue(imageResponse());
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <SourceViewer
        target={{ issueMonth: "1956-06", page: 37, articleTitle: "Editorial" }}
        onClose={onClose}
        onNavigate={() => {}}
      />
    );

    await user.click(screen.getByRole("button", { name: /close source viewer/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("re-fetches independently when the page changes, without a new mount", async () => {
    vi.mocked(fetch).mockResolvedValue(imageResponse({ "x-sampada-min-page": "1", "x-sampada-max-page": "60" }));
    const { rerender } = render(
      <SourceViewer
        target={{ issueMonth: "1956-06", page: 37, articleTitle: "Editorial" }}
        onClose={() => {}}
        onNavigate={() => {}}
      />
    );
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

    rerender(
      <SourceViewer
        target={{ issueMonth: "1956-06", page: 38, articleTitle: "Editorial" }}
        onClose={() => {}}
        onNavigate={() => {}}
      />
    );
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(fetch).toHaveBeenLastCalledWith("/api/source-preview?issueMonth=1956-06&page=38");
  });
});
