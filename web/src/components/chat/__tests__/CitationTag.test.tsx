// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ParsedCitation } from "@/lib/types";
import { CitationTag } from "../CitationTag";

describe("CitationTag", () => {
  it("links to the article's transcription page", () => {
    const citation: ParsedCitation = {
      articleId: 42,
      articleTitle: "Editorial",
      issueMonth: "2021-06",
      sourceUrl: "",
      page: null,
      pdfPageOffset: null,
    };
    render(<CitationTag citation={citation} />);

    const link = screen.getByRole("link", { name: "June 2021 — Editorial" });
    expect(link).toHaveAttribute("href", "/archive/42");
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

    const link = screen.getByRole("link", { name: "June 2021 — Women in Robotics" });
    expect(link).toHaveAttribute("href", "/archive/7");
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
    render(<CitationTag citation={citation} />);

    expect(screen.getByRole("link", { name: "July 1956 — Editorial, Page 27" })).toBeInTheDocument();
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
});
