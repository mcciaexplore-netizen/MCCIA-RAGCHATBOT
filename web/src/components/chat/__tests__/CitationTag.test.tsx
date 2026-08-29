// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ParsedCitation } from "@/lib/types";
import { CitationTag } from "../CitationTag";

describe("CitationTag", () => {
  it("always links the full-text affordance to the article's transcription page", () => {
    const citation: ParsedCitation = {
      articleId: 42,
      articleTitle: "Editorial",
      issueMonth: "2021-06",
      sourceUrl: "",
      page: null,
      pdfPageOffset: null,
    };
    render(<CitationTag citation={citation} />);

    expect(screen.getByRole("link", { name: /full text/i })).toHaveAttribute("href", "/archive/42");
  });

  it("still links to the transcription page even when a source url exists", () => {
    // The transcription page itself surfaces the external link -- the tag
    // in a chat answer should never be a dead end just because an issue
    // predates the site's web archive.
    const citation: ParsedCitation = {
      articleId: 7,
      articleTitle: "Women in Robotics",
      issueMonth: "2021-06",
      sourceUrl: "https://www.mcciapunesampada.com/p/women-in-robotics.html",
      page: null,
      pdfPageOffset: null,
    };
    render(<CitationTag citation={citation} />);

    expect(screen.getByRole("link", { name: /full text/i })).toHaveAttribute("href", "/archive/7");
  });

  it("appends the page number when the citation has one", () => {
    const citation: ParsedCitation = {
      articleId: 99,
      articleTitle: "Editorial",
      issueMonth: "1956-07",
      sourceUrl: "",
      page: 27,
      pdfPageOffset: 4,
    };
    render(<CitationTag citation={citation} onOpenSource={() => {}} />);

    expect(screen.getByText("July 1956 — Editorial, Page 27")).toBeInTheDocument();
  });

  it("never fabricates a page number when the citation has none", () => {
    const citation: ParsedCitation = {
      articleId: 100,
      articleTitle: "Editorial",
      issueMonth: "1956-07",
      sourceUrl: "",
      page: null,
      pdfPageOffset: null,
    };
    render(<CitationTag citation={citation} />);

    expect(screen.queryByText(/Page/)).not.toBeInTheDocument();
  });

  it("renders a clickable button when page and pdfPageOffset are both verified, and calls onOpenSource with the right target", async () => {
    const citation: ParsedCitation = {
      articleId: 372,
      articleTitle: "मराठा चेंबर वार्षिक अहवाल",
      issueMonth: "1956-06",
      sourceUrl: "",
      page: 37,
      pdfPageOffset: 95,
    };
    const onOpenSource = vi.fn();
    const user = userEvent.setup();
    render(<CitationTag citation={citation} onOpenSource={onOpenSource} />);

    const button = screen.getByRole("button", { name: /June 1956 — मराठा चेंबर वार्षिक अहवाल, Page 37/ });
    await user.click(button);

    expect(onOpenSource).toHaveBeenCalledWith({
      issueMonth: "1956-06",
      page: 37,
      articleTitle: "मराठा चेंबर वार्षिक अहवाल",
    });
  });

  it("does not render a clickable button when page metadata is missing, even if onOpenSource is provided", () => {
    const citation: ParsedCitation = {
      articleId: 1,
      articleTitle: "Editorial",
      issueMonth: "1948-04",
      sourceUrl: "",
      page: null,
      pdfPageOffset: null,
    };
    render(<CitationTag citation={citation} onOpenSource={vi.fn()} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("does not render a clickable button when onOpenSource is omitted, even with verified page metadata", () => {
    const citation: ParsedCitation = {
      articleId: 372,
      articleTitle: "Editorial",
      issueMonth: "1956-06",
      sourceUrl: "",
      page: 37,
      pdfPageOffset: 95,
    };
    render(<CitationTag citation={citation} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("June 1956 — Editorial, Page 37")).toBeInTheDocument();
  });
});
