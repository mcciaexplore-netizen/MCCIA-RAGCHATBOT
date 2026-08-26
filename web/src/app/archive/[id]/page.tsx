import Link from "next/link";
import { notFound } from "next/navigation";
import { fetchArticle } from "@/lib/article";
import { formatIssueMonth } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function ArticlePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const articleId = Number(id);
  const article = Number.isInteger(articleId) ? await fetchArticle(articleId) : null;

  if (!article) {
    notFound();
  }

  return (
    <div className="w-full px-12 py-10 sm:px-20">
      <div className="mx-auto w-full max-w-3xl">
        <Link href="/archive" className="text-sm text-brand-primary underline hover:text-brand-primary-hover">
          ← Back to the archive
        </Link>

        <p className="mt-6 text-sm font-medium text-brand-text-muted">
          Sampada, {formatIssueMonth(article.issueMonth)}
        </p>
        <h1 className="font-heading mt-1 text-3xl text-brand-primary sm:text-4xl">
          {article.articleTitle}
        </h1>
        {article.author && (
          <p className="mt-2 text-brand-text-muted">By {article.author}</p>
        )}

        {article.sourceUrl && (
          <a
            href={article.sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-4 inline-block text-sm text-brand-primary underline hover:text-brand-primary-hover"
          >
            Read the original on mcciapunesampada.com ↗
          </a>
        )}

        <p className="mt-8 whitespace-pre-wrap text-lg leading-relaxed text-brand-text">
          {article.body}
        </p>
      </div>
    </div>
  );
}
