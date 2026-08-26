// Shared shapes between server modules and client components. No
// "server-only" import here on purpose -- these are plain data types safe
// to import from either side.

// Must match BROWSE_INDEX_KEY in infra/sampada_stack.py and INDEX_KEY in
// ingest/build_index.py -- the one S3 key the app's IAM role can read.
export const BROWSE_INDEX_KEY = "index/issues.json";

export type ParsedCitation = {
  articleTitle: string;
  issueMonth: string;
  sourceUrl: string;
};

export type ChatApiResponse = {
  answer: string;
  citations: ParsedCitation[];
  scope: "issue" | "open";
  issueMonth: string | null;
};

export type BrowseArticle = {
  title: string;
  slug: string;
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
