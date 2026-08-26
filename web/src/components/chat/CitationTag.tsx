import Link from "next/link";
import { formatIssueMonth } from "@/lib/format";
import type { ParsedCitation } from "@/lib/types";

export function CitationTag({ citation }: { citation: ParsedCitation }) {
  const label = `${formatIssueMonth(citation.issueMonth)} — ${citation.articleTitle}`;

  // Every citation links to its full transcription -- most pre-2021 issues
  // have no external source_url, so that can't be the only way to read the
  // cited article.
  return (
    <Link
      href={`/archive/${citation.articleId}`}
      className="inline-flex items-center rounded-full border border-brand-accent/40 bg-brand-accent/10 px-3 py-1 text-xs font-medium text-brand-primary hover:bg-brand-accent/20"
    >
      {label}
    </Link>
  );
}
