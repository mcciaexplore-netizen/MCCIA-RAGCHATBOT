// Shared shapes between server modules and client components. No
// "server-only" import here on purpose -- these are plain data types safe
// to import from either side.

export type ParsedCitation = {
  articleId: number;
  articleTitle: string;
  issueMonth: string;
  sourceUrl: string;
};

export type ChatApiResponse = {
  answerEnglish: string;
  answerMarathi: string;
  citations: ParsedCitation[];
  scope: "issue" | "open";
  issueMonth: string | null;
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
