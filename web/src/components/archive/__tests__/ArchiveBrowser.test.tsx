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
      { title: "Editorial", slug: "editorial", sourceUrl: "" },
      {
        title: "Women in Robotics",
        slug: "women-in-robotics",
        sourceUrl: "https://mcciapunesampada.com/2021/06/women-in-robotics.html",
      },
    ],
  },
  {
    year: 2020,
    month: 5,
    issueMonth: "2020-05",
    label: "May 2020",
    articles: [{ title: "COVID Relief", slug: "covid-relief", sourceUrl: "" }],
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

  it("links an article to its source url when present", () => {
    render(<ArchiveBrowser issues={ISSUES} />);
    const link = screen.getByRole("link", { name: "Women in Robotics" });
    expect(link).toHaveAttribute(
      "href",
      "https://mcciapunesampada.com/2021/06/women-in-robotics.html"
    );
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("renders an article with no source url as plain text, not a link", () => {
    render(<ArchiveBrowser issues={ISSUES} />);
    expect(screen.queryByRole("link", { name: "Editorial" })).not.toBeInTheDocument();
    expect(screen.getByText("Editorial")).toBeInTheDocument();
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
