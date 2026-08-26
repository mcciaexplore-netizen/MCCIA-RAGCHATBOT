import { formatIssueMonth } from "@/lib/format";
import type { ParsedCitation } from "@/lib/types";

export function CitationTag({ citation }: { citation: ParsedCitation }) {
  const label = `${formatIssueMonth(citation.issueMonth)} — ${citation.articleTitle}`;
  const className =
    "inline-flex items-center rounded-full border border-brand-accent/40 bg-brand-accent/10 px-3 py-1 text-xs font-medium text-brand-primary";

  if (citation.sourceUrl) {
    return (
      <a
        href={citation.sourceUrl}
        target="_blank"
        rel="noopener noreferrer"
        className={`${className} hover:bg-brand-accent/20`}
      >
        {label}
      </a>
    );
  }

  return <span className={className}>{label}</span>;
}
