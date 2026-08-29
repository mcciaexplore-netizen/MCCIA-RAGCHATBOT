import Link from "next/link";
import { formatIssueMonth } from "@/lib/format";
import type { ParsedCitation } from "@/lib/types";

export type SourceTarget = { issueMonth: string; page: number; articleTitle: string };

export function CitationTag({
  citation,
  onOpenSource,
}: {
  citation: ParsedCitation;
  /** Omit (or leave undefined) to render the plain, non-interactive label --
   * used wherever there's no source viewer to open into. */
  onOpenSource?: (target: SourceTarget) => void;
}) {
  // Page is appended only when known -- never fabricated for a citation
  // whose underlying chunk predates page tracking (see web/src/lib/retrieval.ts).
  const pageSuffix = citation.page != null ? `, Page ${citation.page}` : "";
  const label = `${formatIssueMonth(citation.issueMonth)} — ${citation.articleTitle}${pageSuffix}`;
  // Only a citation with a verified page AND a verified pdf_page_offset can
  // resolve to a real scanned page (see source-preview.ts) -- anything
  // ingested before page tracking has pdfPageOffset === null and must never
  // look clickable, since there's nothing real to show.
  const canOpenSource = citation.page != null && citation.pdfPageOffset != null && Boolean(onOpenSource);

  return (
    <span className="inline-flex items-center gap-1.5">
      {canOpenSource ? (
        <button
          type="button"
          onClick={() =>
            onOpenSource?.({
              issueMonth: citation.issueMonth,
              page: citation.page as number,
              articleTitle: citation.articleTitle,
            })
          }
          className="inline-flex items-center rounded-full border border-brand-accent/40 bg-brand-accent/10 px-3 py-1 text-xs font-medium text-brand-primary hover:bg-brand-accent/20"
        >
          {label}
        </button>
      ) : (
        <span className="inline-flex items-center rounded-full border border-brand-border bg-brand-surface px-3 py-1 text-xs font-medium text-brand-text-muted">
          {label}
        </span>
      )}
      {/* Every citation links to its full transcription -- most pre-2021
          issues have no external source_url, so that can't be the only way
          to read the cited article. Kept separate from the button above so
          "open the scanned page" and "read the transcription" stay two
          distinct actions instead of one overloaded click target. */}
      <Link
        href={`/archive/${citation.articleId}`}
        className="text-xs text-brand-text-muted underline decoration-dotted hover:text-brand-primary"
        title="Read the full transcription"
      >
        full text ↗
      </Link>
    </span>
  );
}
