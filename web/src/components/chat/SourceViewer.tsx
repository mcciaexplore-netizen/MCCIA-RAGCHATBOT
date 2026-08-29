"use client";

import { useEffect, useRef, useState } from "react";
import { formatIssueMonth } from "@/lib/format";
import type { SourceTarget } from "./CitationTag";

export type { SourceTarget };

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; url: string; minPage: number; maxPage: number };

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" className="h-5 w-5">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

/** The right-hand panel: the actual scanned historical page for a clicked
 * citation. Rendered by the backend from the real local PDF (see
 * api/source-preview/route.ts) -- never generated or recreated, and never a
 * Gemini call. Opening/closing/navigating this panel never touches search
 * or retrieval at all. */
export function SourceViewer({
  target,
  onClose,
  onNavigate,
}: {
  target: SourceTarget | null;
  onClose: () => void;
  onNavigate: (page: number) => void;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  // Reset to "loading" synchronously during render as soon as a new
  // target is picked, rather than as the first line of the effect below --
  // avoids the extra render a setState-in-effect would cause, and avoids a
  // flash of the previous page's content while the new fetch is in flight.
  const requestedKey = target ? `${target.issueMonth}:${target.page}` : null;
  const lastRequestedKey = useRef<string | null>(null);
  if (requestedKey !== lastRequestedKey.current) {
    lastRequestedKey.current = requestedKey;
    if (requestedKey !== null && state.status !== "loading") {
      setState({ status: "loading" });
    }
  }

  useEffect(() => {
    if (!target) return;
    let cancelled = false;
    let objectUrl: string | null = null;

    fetch(`/api/source-preview?issueMonth=${encodeURIComponent(target.issueMonth)}&page=${target.page}`)
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          setState({
            status: "error",
            message: body?.error ?? "No reliable original page was found for this citation.",
          });
          return;
        }
        const minPage = Number(res.headers.get("x-sampada-min-page") ?? 1);
        const maxPage = Number(res.headers.get("x-sampada-max-page") ?? target.page);
        const blob = await res.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setState({ status: "ready", url: objectUrl, minPage, maxPage });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error", message: "Could not reach the archive to load this page." });
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
    // Depends on the primitive (issueMonth, page) pair, not the `target`
    // object identity -- a new object with the same values shouldn't
    // re-fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target?.issueMonth, target?.page]);

  if (!target) {
    return (
      <aside className="hidden w-80 shrink-0 flex-col items-center justify-center gap-3 border-l border-brand-border bg-brand-surface p-8 text-center lg:flex">
        <p className="text-sm text-brand-text-muted">Click a citation to view the original scanned page.</p>
      </aside>
    );
  }

  return (
    <>
      {/* On narrower screens this panel becomes a slide-over instead of a
          third squeezed column -- see requirement to keep chat primary. */}
      <div className="fixed inset-0 z-40 bg-slate-900/30 lg:hidden" onClick={onClose} aria-hidden="true" />
      <aside className="fixed inset-y-0 right-0 z-50 flex w-full max-w-sm shrink-0 flex-col border-l border-brand-border bg-brand-surface lg:static lg:z-auto lg:w-96 lg:max-w-none">
      <div className="flex items-start justify-between gap-2 border-b border-brand-border p-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-brand-text-muted">Original Source</p>
          <h3 className="font-heading text-lg text-brand-primary">Sampada — {formatIssueMonth(target.issueMonth)}</h3>
          <p className="mt-0.5 text-sm text-brand-text-muted">{target.articleTitle}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close source viewer"
          className="rounded-full p-1.5 text-brand-text-muted hover:bg-brand-bg hover:text-brand-text"
        >
          <CloseIcon />
        </button>
      </div>

      <div className="flex flex-1 flex-col items-center gap-4 overflow-y-auto p-4">
        {state.status === "loading" && (
          <div className="flex h-64 w-full animate-pulse items-center justify-center rounded-lg bg-brand-bg text-sm text-brand-text-muted">
            Loading original page…
          </div>
        )}
        {state.status === "error" && (
          <p className="text-sm text-brand-text-muted">{state.message}</p>
        )}
        {state.status === "ready" && (
          // A locally fetched blob: URL, not an optimizable remote/static asset.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={state.url}
            alt={`Sampada, ${formatIssueMonth(target.issueMonth)}, page ${target.page}`}
            className="w-full rounded-lg border border-brand-border shadow-sm"
          />
        )}
      </div>

      {state.status === "ready" && (
        <div className="flex items-center justify-between gap-2 border-t border-brand-border p-4">
          <button
            type="button"
            disabled={target.page <= state.minPage}
            onClick={() => onNavigate(target.page - 1)}
            className="rounded-full border border-brand-border px-3 py-1.5 text-sm text-brand-text hover:border-brand-primary disabled:cursor-not-allowed disabled:opacity-40"
          >
            ← Previous page
          </button>
          <span className="text-sm font-medium text-brand-text-muted">Page {target.page}</span>
          <button
            type="button"
            disabled={target.page >= state.maxPage}
            onClick={() => onNavigate(target.page + 1)}
            className="rounded-full border border-brand-border px-3 py-1.5 text-sm text-brand-text hover:border-brand-primary disabled:cursor-not-allowed disabled:opacity-40"
          >
            Next page →
          </button>
        </div>
      )}
      </aside>
    </>
  );
}
