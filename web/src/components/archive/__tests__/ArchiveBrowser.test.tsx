// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { BrowseIssue } from "@/lib/types";
import { ArchiveBrowser } from "../ArchiveBrowser";

const ISSUES: BrowseIssue[] = [
  {
    year: 2021,
    month: 6,
    issueMonth: "2021-06",
    label: "June 2021",
    articles: [
      { id: 1, title: "Editorial", sourceUrl: "" },
      {
        id: 2,
        title: "Women in Robotics",
        sourceUrl: "https://mcciapunesampada.com/2021/06/women-in-robotics.html",
      },
    ],
  },
  {
    year: 2020,
    month: 5,
    issueMonth: "2020-05",
    label: "May 2020",
    articles: [{ id: 3, title: "COVID Relief", sourceUrl: "" }],
  },
];

describe("ArchiveBrowser", () => {
  it("shows an empty state when there are no issues", () => {
    render(<ArchiveBrowser issues={[]} />);
    expect(screen.getByText(/no issues in the archive yet/i)).toBeInTheDocument();
  });

  it("renders every issue and article by default", () => {
    render(<ArchiveBrowser issues={ISSUES} />);
    expect(screen.getByText("June 2021")).toBeInTheDocument();
    expect(screen.getByText("May 2020")).toBeInTheDocument();
    expect(screen.getByText("Editorial")).toBeInTheDocument();
    expect(screen.getByText("COVID Relief")).toBeInTheDocument();
  });

  it("always links an article's title to its transcription page", () => {
    render(<ArchiveBrowser issues={ISSUES} />);
    expect(screen.getByRole("link", { name: "Editorial" })).toHaveAttribute("href", "/archive/1");
    expect(screen.getByRole("link", { name: "Women in Robotics" })).toHaveAttribute(
      "href",
      "/archive/2"
    );
  });

  it("also shows an external link when a source url is present", () => {
    render(<ArchiveBrowser issues={ISSUES} />);
    const externalLink = screen.getByTitle("Read the original on mcciapunesampada.com");
    expect(externalLink).toHaveAttribute(
      "href",
      "https://mcciapunesampada.com/2021/06/women-in-robotics.html"
    );
    expect(externalLink).toHaveAttribute("target", "_blank");
  });

  it("omits the external link for articles with no source url", () => {
    // Of the 3 fixture articles, only "Women in Robotics" has a source_url --
    // exactly one external link should exist, not one per article.
    render(<ArchiveBrowser issues={ISSUES} />);
    expect(screen.getAllByTitle("Read the original on mcciapunesampada.com")).toHaveLength(1);
  });

  it("filters to one year when its pill is clicked", async () => {
    const user = userEvent.setup();
    render(<ArchiveBrowser issues={ISSUES} />);

    await user.click(screen.getByRole("button", { name: "2021" }));

    expect(screen.getByText("June 2021")).toBeInTheDocument();
    expect(screen.queryByText("May 2020")).not.toBeInTheDocument();
  });

  it("shows all years again after selecting 'All years'", async () => {
    const user = userEvent.setup();
    render(<ArchiveBrowser issues={ISSUES} />);

    await user.click(screen.getByRole("button", { name: "2021" }));
    await user.click(screen.getByRole("button", { name: "All years" }));

    expect(screen.getByText("June 2021")).toBeInTheDocument();
    expect(screen.getByText("May 2020")).toBeInTheDocument();
  });
});
