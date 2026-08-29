// Shared shapes between server modules and client components. No
// "server-only" import here on purpose -- these are plain data types safe
// to import from either side.

export type ParsedCitation = {
  articleId: number;
  articleTitle: string;
  issueMonth: string;
  sourceUrl: string;
  // Issue-relative page number, or null when unavailable -- never a
  // fabricated value (see web/src/lib/retrieval.ts). A future source
  // viewer can combine this with pdfPageOffset to open the right PDF page.
  page: number | null;
  pdfPageOffset: number | null;
};

export type ChatApiResponse = {
  answerEnglish: string;
  answerMarathi: string;
  citations: ParsedCitation[];
  scope: "issue" | "range" | "open";
  issueMonth: string | null;
  yearFrom: number | null;
  yearTo: number | null;
};

export type BrowseArticle = {
  id: number;
  title: string;
  sourceUrl: string;
};

export type BrowseIssue = {
  year: number;
  month: number;
  issueMonth: string;
  label: string;
  articles: BrowseArticle[];
};

export type BrowseIndex = {
  issues: BrowseIssue[];
};

// Shared with conversation-history.ts (localStorage persistence) as well as
// ChatInterface's own render logic -- kept here rather than local to the
// component so history storage doesn't need to import a client component.
export type ChatMessage =
  | { id: number; role: "user"; content: string }
  | {
      id: number;
      role: "assistant";
      contentEn: string;
      contentMr: string;
      citations: ParsedCitation[];
    }
  | { id: number; role: "error"; content: string };
