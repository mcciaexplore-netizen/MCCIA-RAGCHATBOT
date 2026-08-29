import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/source-preview", () => ({
  resolveSourcePreview: vi.fn(),
}));
vi.mock("node:fs/promises", () => ({
  readFile: vi.fn(),
}));

import { readFile } from "node:fs/promises";
import { resolveSourcePreview } from "@/lib/source-preview";
import { GET } from "../route";

function req(query: string): Request {
  return new Request(`http://localhost/api/source-preview${query}`);
}

beforeEach(() => {
  vi.mocked(resolveSourcePreview).mockReset();
  vi.mocked(readFile).mockReset();
});

describe("GET /api/source-preview", () => {
  it("returns 400 when issueMonth or page is missing, without calling the resolver", async () => {
    const res = await GET(req("?page=37"));
    expect(res.status).toBe(400);
    expect(resolveSourcePreview).not.toHaveBeenCalled();
  });

  it("serves the resolved JPEG with the right content type and page-bound headers", async () => {
    vi.mocked(resolveSourcePreview).mockResolvedValue({
      ok: true,
      jpegPath: "/repo/staging/processed/abc/previews/page-0131.jpg",
      minPage: 1,
      maxPage: 60,
      humanLabel: "Sampada — June 1956 — Page 37",
    });
    vi.mocked(readFile).mockResolvedValue(Buffer.from([0xff, 0xd8, 0xff]));

    const res = await GET(req("?issueMonth=1956-06&page=37"));

    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("image/jpeg");
    expect(res.headers.get("x-sampada-min-page")).toBe("1");
    expect(res.headers.get("x-sampada-max-page")).toBe("60");
  });

  it("maps source_not_indexed to 404 with a clean message, not a raw error", async () => {
    vi.mocked(resolveSourcePreview).mockResolvedValue({
      ok: false,
      error: "source_not_indexed",
      message: "This edition doesn't have a verified source page mapping yet.",
    });

    const res = await GET(req("?issueMonth=1945-07&page=1"));
    const body = await res.json();

    expect(res.status).toBe(404);
    expect(body.error).toBe("This edition doesn't have a verified source page mapping yet.");
  });

  it("maps render_failed to a 500 without leaking the underlying error", async () => {
    vi.mocked(resolveSourcePreview).mockResolvedValue({
      ok: false,
      error: "render_failed",
      message: "Could not render the original scanned page.",
    });

    const res = await GET(req("?issueMonth=1956-06&page=37"));
    expect(res.status).toBe(500);
  });

  it("passes the raw query params straight through to the resolver, which owns all validation", async () => {
    vi.mocked(resolveSourcePreview).mockResolvedValue({
      ok: false,
      error: "invalid_page",
      message: "page must be a positive integer.",
    });

    await GET(req("?issueMonth=1956-06&page=-5"));
    expect(resolveSourcePreview).toHaveBeenCalledWith("1956-06", -5);
  });
});
