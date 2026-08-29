import "server-only";
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import type { NeonQueryFunction } from "@neondatabase/serverless";
import { config } from "@/lib/config";
import { getDb } from "@/lib/db";
import { formatIssueMonth } from "@/lib/format";
import { MAX_YEAR, MIN_YEAR } from "@/lib/gemini/query-router";

const execFileAsync = promisify(execFile);

const ISSUE_MONTH_RE = /^(\d{4})-(\d{2})$/;

export type SourcePreviewError =
  | "invalid_issue_month"
  | "invalid_page"
  | "source_not_indexed"
  | "source_file_missing"
  | "page_out_of_range"
  | "render_failed";

export type SourcePreviewResult =
  | { ok: true; jpegPath: string; minPage: number; maxPage: number; humanLabel: string }
  | { ok: false; error: SourcePreviewError; message: string };

type SourceRow = {
  sourceFilename: string | null;
  driveFileId: string;
  pdfPageOffset: number | null;
  minPage: number | null;
  maxPage: number | null;
};

/** Resolves a citation's (issueMonth, page) to a real, on-disk scanned page
 * -- exclusively by looking up `sampada`/`articles`, the same tables every
 * citation's page number already comes from (see generate-answer.ts's
 * buildCitations). The caller never supplies a filesystem path or a Drive
 * ID directly; every value that touches the filesystem here (pdfPath,
 * driveFileId, the physical page index) is read back out of the database,
 * not accepted from the request. See render_page_preview.py for the actual
 * rasterization, and the module-level comment there for why that split
 * (validation here, rendering there) is the trust boundary. */
export async function resolveSourcePreview(
  issueMonth: string,
  page: number,
  opts: { client?: NeonQueryFunction<false, false> } = {}
): Promise<SourcePreviewResult> {
  const match = ISSUE_MONTH_RE.exec(issueMonth);
  if (!match) {
    return { ok: false, error: "invalid_issue_month", message: "issueMonth must look like YYYY-MM." };
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (year < MIN_YEAR || year > MAX_YEAR || month < 1 || month > 12) {
    return { ok: false, error: "invalid_issue_month", message: "That issue is outside the archive's real range." };
  }
  if (!Number.isInteger(page) || page < 1) {
    return { ok: false, error: "invalid_page", message: "page must be a positive integer." };
  }

  const sql = opts.client ?? getDb();
  const rows = (await sql`
    select
      s.source_filename as "sourceFilename",
      s.source_pdf_id as "driveFileId",
      s.pdf_page_offset as "pdfPageOffset",
      min(a.issue_page_start) as "minPage",
      max(a.issue_page_end) as "maxPage"
    from sampada s
    left join articles a on a.year = s.year and a.month = s.month
    where s.year = ${year} and s.month = ${month}
    group by s.source_filename, s.source_pdf_id, s.pdf_page_offset
  `) as SourceRow[];

  const row = rows[0];
  if (!row || row.sourceFilename == null || row.pdfPageOffset == null) {
    return {
      ok: false,
      error: "source_not_indexed",
      message: "This edition doesn't have a verified source page mapping yet.",
    };
  }

  const minPage = 1;
  // No article rows on record for this edition (shouldn't happen for
  // anything actually indexed) -- rather than fabricate a bound, only the
  // exact page asked for is allowed.
  const maxPage = row.maxPage ?? page;
  if (page > maxPage) {
    return {
      ok: false,
      error: "page_out_of_range",
      message: `Page ${page} is beyond this edition's indexed content (up to page ${maxPage}).`,
    };
  }

  const rawDir = path.resolve(config.archiveRootDir, "staging", "raw");
  const pdfPath = path.resolve(rawDir, row.sourceFilename);
  // Defense in depth: source_filename is always DB-written from our own
  // Drive sync (never client input), but this still refuses to open
  // anything outside staging/raw/ if that filename ever contained a
  // path segment.
  if (path.dirname(pdfPath) !== rawDir || !existsSync(pdfPath)) {
    return {
      ok: false,
      error: "source_file_missing",
      message: "The original scanned PDF for this edition isn't available locally.",
    };
  }

  const physicalPage0 = row.pdfPageOffset + (page - 1);
  const previewDir = path.join(config.archiveRootDir, "staging", "processed", row.driveFileId, "previews");
  const jpegPath = path.join(previewDir, `page-${String(physicalPage0).padStart(4, "0")}.jpg`);

  if (!existsSync(jpegPath)) {
    const pythonBin = path.join(config.archiveRootDir, ".venv", "bin", "python3");
    try {
      await execFileAsync(
        pythonBin,
        ["-m", "ingest.render_page_preview", "--pdf", pdfPath, "--page", String(physicalPage0), "--out", jpegPath],
        { cwd: config.archiveRootDir }
      );
    } catch (err) {
      const execErr = err as { code?: number };
      if (execErr.code === 2) {
        return {
          ok: false,
          error: "page_out_of_range",
          message: "That page is out of range for the original scanned PDF.",
        };
      }
      return { ok: false, error: "render_failed", message: "Could not render the original scanned page." };
    }
  }

  return {
    ok: true,
    jpegPath,
    minPage,
    maxPage,
    humanLabel: `Sampada — ${formatIssueMonth(issueMonth)} — Page ${page}`,
  };
}
