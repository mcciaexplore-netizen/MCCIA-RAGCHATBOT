"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { BrowseIssue } from "@/lib/types";

export function ArchiveBrowser({ issues }: { issues: BrowseIssue[] }) {
  const years = useMemo(
    // Chronological, 1945 onward, matching the issue list below.
    () => Array.from(new Set(issues.map((issue) => issue.year))).sort((a, b) => a - b),
    [issues]
  );
  const [selectedYear, setSelectedYear] = useState<number | "all">("all");

  const visibleIssues =
    selectedYear === "all" ? issues : issues.filter((issue) => issue.year === selectedYear);

  if (issues.length === 0) {
    return (
      <p className="text-brand-text-muted">
        No issues in the archive yet -- check back once Sampada&apos;s issues have
        been ingested.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="scroll-thin flex flex-nowrap items-center gap-2 overflow-x-auto scroll-px-1 snap-x pb-2">
        <div className="snap-start shrink-0">
          <FilterPill
            label="All years"
            selected={selectedYear === "all"}
            onClick={() => setSelectedYear("all")}
          />
        </div>
        {years.map((year) => (
          <div key={year} className="snap-start shrink-0">
            <FilterPill
              label={String(year)}
              selected={selectedYear === year}
              onClick={() => setSelectedYear(year)}
            />
          </div>
        ))}
      </div>

      <ol className="flex flex-col gap-8">
        {visibleIssues.map((issue) => (
          <li key={issue.issueMonth}>
            <h2 className="font-heading text-2xl text-brand-primary">{issue.label}</h2>
            <ul className="mt-2 flex flex-col gap-1">
              {issue.articles.map((article) => (
                <li key={article.id} className="flex items-center gap-2">
                  <Link
                    href={`/archive/${article.id}`}
                    className="text-brand-text hover:text-brand-primary hover:underline"
                  >
                    {article.title}
                  </Link>
                  {article.sourceUrl && (
                    <a
                      href={article.sourceUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-brand-text-muted hover:text-brand-primary"
                      title="Read the original on mcciapunesampada.com"
                    >
                      ↗
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
    </div>
  );
}

function FilterPill({
  label,
  selected,
  onClick,
}: {
  label: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        selected
          ? "rounded-full bg-brand-primary px-4 py-1.5 text-sm font-medium text-white"
          : "rounded-full border border-brand-border bg-brand-surface px-4 py-1.5 text-sm text-brand-text hover:border-brand-primary"
      }
    >
      {label}
    </button>
  );
}
