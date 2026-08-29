import "server-only";

// Exact normalized-query cache for /api/chat -- the smallest safe caching
// strategy for this stage, not a semantic/intent-based cache (which would
// risk two genuinely different questions sharing a cached answer). Two
// requests only share a cache entry if they normalize to the identical
// question text.
//
// In-memory, per-process: correct for this app's current single-process
// local deployment (see the deployment note in HANDOFF.md/memory -- this is
// not deployed yet), but won't provide meaningful hit rates across multiple
// serverless instances if/when this is ever deployed that way. That's a
// known, explicit limitation of choosing "smallest appropriate" here rather
// than a shared external cache (Redis, a Neon table) this stage doesn't
// need yet.
//
// Invalidation: bounded automatically by TTL_MS, so a stale answer can
// never be served indefinitely after the archive changes underneath it.
// clearCache() is also exported for an operator to call explicitly (or
// simply restart the process) right after running an ingestion pass, for
// immediate invalidation rather than waiting out the TTL.

const TTL_MS = 10 * 60 * 1000; // 10 minutes
const MAX_ENTRIES = 500; // bounds memory; oldest entry evicted beyond this

type CacheEntry<T> = {
  value: T;
  expiresAt: number;
};

const store = new Map<string, CacheEntry<unknown>>();

export function normalizeQuestion(question: string): string {
  return question.trim().toLowerCase().replace(/\s+/g, " ");
}

export function getCached<T>(question: string): T | undefined {
  const key = normalizeQuestion(question);
  const entry = store.get(key);
  if (!entry) return undefined;
  if (Date.now() > entry.expiresAt) {
    store.delete(key);
    return undefined;
  }
  return entry.value as T;
}

export function setCached<T>(question: string, value: T): void {
  const key = normalizeQuestion(question);
  if (!store.has(key) && store.size >= MAX_ENTRIES) {
    const oldestKey = store.keys().next().value;
    if (oldestKey !== undefined) store.delete(oldestKey);
  }
  store.set(key, { value, expiresAt: Date.now() + TTL_MS });
}

/** Clears every cached answer -- call after an ingestion run so newly
 * indexed content isn't shadowed by a stale cached answer until the TTL
 * expires on its own. */
export function clearCache(): void {
  store.clear();
}

export function cacheSize(): number {
  return store.size;
}
