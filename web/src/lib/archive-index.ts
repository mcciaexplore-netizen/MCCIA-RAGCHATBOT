import "server-only";
import { GetObjectCommand, NoSuchKey, S3Client } from "@aws-sdk/client-s3";
import { config } from "@/lib/config";
import { BROWSE_INDEX_KEY, type BrowseIndex } from "@/lib/types";

const EMPTY_INDEX: BrowseIndex = { issues: [] };

function buildClient(): S3Client {
  return new S3Client({ region: config.awsRegion });
}

/** Returns an empty index if nothing has been ingested yet, rather than
 * failing the whole browse page -- this is expected before Phase 1 has run
 * against real data.
 */
export async function getBrowseIndex(client: S3Client = buildClient()): Promise<BrowseIndex> {
  try {
    const response = await client.send(
      new GetObjectCommand({ Bucket: config.s3Bucket, Key: BROWSE_INDEX_KEY })
    );
    const body = await response.Body?.transformToString();
    if (!body) return EMPTY_INDEX;
    return JSON.parse(body) as BrowseIndex;
  } catch (error) {
    if (error instanceof NoSuchKey) return EMPTY_INDEX;
    throw error;
  }
}
