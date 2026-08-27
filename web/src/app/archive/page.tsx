import Link from "next/link";
import { ArchiveBrowser } from "@/components/archive/ArchiveBrowser";
import { getBrowseIndex } from "@/lib/archive-index";

export const dynamic = "force-dynamic";

export default async function ArchivePage() {
  const index = await getBrowseIndex();

  return (
    <div className="w-full px-12 py-10 sm:px-20">
      <div className="mx-auto w-full max-w-4xl">
        <h1 className="font-heading text-4xl text-brand-primary">Browse the archive</h1>
        <p className="mt-2 text-brand-text-muted">
          Every Sampada issue, chronological from 1945. Prefer to ask a question instead?{" "}
          <Link href="/" className="text-brand-primary underline hover:text-brand-primary-hover">
            Go back to Ask
          </Link>
          .
        </p>
        <div className="mt-8">
          <ArchiveBrowser issues={index.issues} />
        </div>
      </div>
    </div>
  );
}
