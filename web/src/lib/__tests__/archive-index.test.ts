import { NoSuchKey } from "@aws-sdk/client-s3";
import { describe, expect, it, vi } from "vitest";
import { getBrowseIndex } from "../archive-index";

function fakeClient(send: ReturnType<typeof vi.fn>) {
  return { send } as unknown as import("@aws-sdk/client-s3").S3Client;
}

describe("getBrowseIndex", () => {
  it("parses the stored index JSON", async () => {
    process.env.S3_BUCKET = "test-bucket";
    const index = { issues: [{ year: 2021, month: 6, issueMonth: "2021-06", label: "June 2021", articles: [] }] };
    const send = vi.fn().mockResolvedValue({
      Body: { transformToString: async () => JSON.stringify(index) },
    });

    const result = await getBrowseIndex(fakeClient(send));
    expect(result).toEqual(index);
  });

  it("returns an empty index when the object doesn't exist yet", async () => {
    process.env.S3_BUCKET = "test-bucket";
    const send = vi.fn().mockRejectedValue(
      new NoSuchKey({ message: "not found", $metadata: {} })
    );

    const result = await getBrowseIndex(fakeClient(send));
    expect(result).toEqual({ issues: [] });
  });

  it("returns an empty index when the body is empty", async () => {
    process.env.S3_BUCKET = "test-bucket";
    const send = vi.fn().mockResolvedValue({ Body: undefined });

    const result = await getBrowseIndex(fakeClient(send));
    expect(result).toEqual({ issues: [] });
  });

  it("rethrows errors other than NoSuchKey", async () => {
    process.env.S3_BUCKET = "test-bucket";
    const send = vi.fn().mockRejectedValue(new Error("access denied"));

    await expect(getBrowseIndex(fakeClient(send))).rejects.toThrow("access denied");
  });
});
