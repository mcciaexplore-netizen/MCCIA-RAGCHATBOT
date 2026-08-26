import { describe, expect, it } from "vitest";
import { formatIssueMonth } from "../format";

describe("formatIssueMonth", () => {
  it("formats a YYYY-MM string as Month Year", () => {
    expect(formatIssueMonth("2021-06")).toBe("June 2021");
    expect(formatIssueMonth("1999-01")).toBe("January 1999");
    expect(formatIssueMonth("2020-12")).toBe("December 2020");
  });

  it("returns the input unchanged if it can't be parsed", () => {
    expect(formatIssueMonth("not-a-date")).toBe("not-a-date");
    expect(formatIssueMonth("2021-13")).toBe("2021-13");
  });
});
