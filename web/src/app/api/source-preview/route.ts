import { readFile } from "node:fs/promises";
import { NextResponse } from "next/server";
import { resolveSourcePreview } from "@/lib/source-preview";

const ERROR_STATUS: Record<string, number> = {
  invalid_issue_month: 400,
  invalid_page: 400,
  source_not_indexed: 404,
  source_file_missing: 404,
  page_out_of_range: 404,
  render_failed: 500,
};

// GET only, and deliberately narrow: issueMonth + page are the only inputs,
// and both are re-validated against the database inside resolveSourcePreview
// -- see that module for why this never accepts a filesystem path or a
// Drive file ID directly from the client (security requirement from the
// UI phase this endpoint was built for).
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const issueMonth = searchParams.get("issueMonth");
  const pageParam = searchParams.get("page");

  if (!issueMonth || !pageParam) {
    return NextResponse.json({ error: "issueMonth and page are required." }, { status: 400 });
  }

  const page = Number(pageParam);
  const result = await resolveSourcePreview(issueMonth, page);

  if (!result.ok) {
    return NextResponse.json({ error: result.message }, { status: ERROR_STATUS[result.error] ?? 400 });
  }

  const bytes = await readFile(result.jpegPath);
  return new NextResponse(new Uint8Array(bytes), {
    headers: {
      "Content-Type": "image/jpeg",
      "Cache-Control": "private, max-age=86400",
      "X-Sampada-Min-Page": String(result.minPage),
      "X-Sampada-Max-Page": String(result.maxPage),
    },
  });
}
