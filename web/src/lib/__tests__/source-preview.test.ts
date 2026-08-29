import type { NeonQueryFunction } from "@neondatabase/serverless";
import { beforeEach, describe, expect, it, vi } from "vitest";

const execFileMock = vi.fn();
vi.mock("node:child_process", () => ({ execFile: (...args: unknown[]) => execFileMock(...args) }));

const existsSyncMock = vi.fn();
vi.mock("node:fs", () => ({ existsSync: (...args: unknown[]) => existsSyncMock(...args) }));

vi.mock("@/lib/config", () => ({
  config: { archiveRootDir: "/repo" },
}));

const { resolveSourcePreview } = await import("../source-preview");

type Row = {
  sourceFilename: string | null;
  driveFileId: string;
  pdfPageOffset: number | null;
  minPage: number | null;
  maxPage: number | null;
};

function fakeSql(rows: Row[]) {
  const fn = () => Promise.resolve(rows);
  return fn as unknown as NeonQueryFunction<false, false>;
}

const REAL_ROW: Row = {
  sourceFilename: "1956 -April To 1957 -March Part No.12.pdf",
  driveFileId: "1Zd7nL-l6FPipepSVmvFQtgBKQDdbS6tH",
  pdfPageOffset: 95,
  minPage: 3,
  maxPage: 60,
};

beforeEach(() => {
  execFileMock.mockReset();
  existsSyncMock.mockReset();
  // execFile is promisified via node:util's callback-style contract --
  // default to "success" so most tests don't need to know that shape.
  execFileMock.mockImplementation((...args: unknown[]) => {
    const cb = args[args.length - 1] as (err: unknown, out: unknown) => void;
    cb(null, { stdout: "", stderr: "" });
  });
});

describe("resolveSourcePreview", () => {
  it("rejects a malformed issueMonth", async () => {
    const result = await resolveSourcePreview("June 1956", 1, { client: fakeSql([]) });
    expect(result).toEqual({ ok: false, error: "invalid_issue_month", message: expect.any(String) });
  });

  it("rejects an issueMonth outside the archive's real range", async () => {
    const result = await resolveSourcePreview("2021-06", 1, { client: fakeSql([]) });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("invalid_issue_month");
  });

  it("rejects a non-positive page", async () => {
    const result = await resolveSourcePreview("1956-06", 0, { client: fakeSql([]) });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("invalid_page");
  });

  it("rejects a non-integer page", async () => {
    const result = await resolveSourcePreview("1956-06", 1.5, { client: fakeSql([]) });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("invalid_page");
  });

  it("returns source_not_indexed when the edition has no DB row", async () => {
    const result = await resolveSourcePreview("1956-06", 37, { client: fakeSql([]) });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("source_not_indexed");
  });

  it("returns source_not_indexed when pdf_page_offset is null (not yet re-processed)", async () => {
    const result = await resolveSourcePreview("1956-06", 37, {
      client: fakeSql([{ ...REAL_ROW, pdfPageOffset: null }]),
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("source_not_indexed");
  });

  it("rejects a page beyond the edition's known content", async () => {
    const result = await resolveSourcePreview("1956-06", 999, { client: fakeSql([REAL_ROW]) });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("page_out_of_range");
    expect(execFileMock).not.toHaveBeenCalled();
  });

  it("refuses a source_filename that would resolve outside staging/raw (path traversal defense)", async () => {
    existsSyncMock.mockReturnValue(true); // even if a file happened to exist there
    const result = await resolveSourcePreview("1956-06", 10, {
      client: fakeSql([{ ...REAL_ROW, sourceFilename: "../../etc/passwd" }]),
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("source_file_missing");
    expect(execFileMock).not.toHaveBeenCalled();
  });

  it("returns source_file_missing when the real PDF isn't on disk", async () => {
    existsSyncMock.mockReturnValue(false);
    const result = await resolveSourcePreview("1956-06", 10, { client: fakeSql([REAL_ROW]) });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("source_file_missing");
  });

  it("reuses an existing cached preview without invoking the renderer", async () => {
    existsSyncMock.mockReturnValue(true); // pdf exists AND jpeg cache exists
    const result = await resolveSourcePreview("1956-06", 37, { client: fakeSql([REAL_ROW]) });
    expect(result.ok).toBe(true);
    expect(execFileMock).not.toHaveBeenCalled();
    if (result.ok) {
      expect(result.jpegPath).toContain(REAL_ROW.driveFileId);
      expect(result.jpegPath).toContain("page-0131.jpg"); // 95 + (37 - 1) = 131
    }
  });

  it("computes the correct physical page and invokes the renderer on a cache miss", async () => {
    existsSyncMock.mockImplementation((p: string) => !p.includes("previews")); // pdf exists, jpeg cache doesn't
    const result = await resolveSourcePreview("1956-06", 37, { client: fakeSql([REAL_ROW]) });
    expect(execFileMock).toHaveBeenCalledTimes(1);
    const args = execFileMock.mock.calls[0][1] as string[];
    expect(args).toContain("--page");
    expect(args[args.indexOf("--page") + 1]).toBe("131");
    expect(result.ok).toBe(true);
  });

  it("maps a page-out-of-range renderer exit code to page_out_of_range, not a raw error", async () => {
    existsSyncMock.mockImplementation((p: string) => !p.includes("previews"));
    execFileMock.mockImplementation((...args: unknown[]) => {
      const cb = args[args.length - 1] as (err: unknown) => void;
      cb({ code: 2 });
    });
    const result = await resolveSourcePreview("1956-06", 37, { client: fakeSql([REAL_ROW]) });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("page_out_of_range");
  });

  it("maps any other renderer failure to render_failed without leaking internals", async () => {
    existsSyncMock.mockImplementation((p: string) => !p.includes("previews"));
    execFileMock.mockImplementation((...args: unknown[]) => {
      const cb = args[args.length - 1] as (err: unknown) => void;
      cb(new Error("some raw pymupdf stack trace"));
    });
    const result = await resolveSourcePreview("1956-06", 37, { client: fakeSql([REAL_ROW]) });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toBe("render_failed");
      expect(result.message).not.toContain("pymupdf");
    }
  });

  it("never calls anything Gemini-related", async () => {
    // resolveSourcePreview's own module graph has no Gemini import at all --
    // this just documents that guarantee for the section-17 performance/
    // safety requirement ("opening a citation must not call Gemini").
    const src = await import("../source-preview");
    expect(Object.keys(src)).not.toContain("generateAnswer");
  });
});
