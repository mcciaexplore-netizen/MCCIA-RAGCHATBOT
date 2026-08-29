import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Node's own built-in global `localStorage` (stable as of Node 22+, backed
// by SQLite and inert without a `--localstorage-file` path) shadows jsdom's
// real per-window Storage implementation in this environment -- window.
// localStorage resolves to Node's broken stub (every method undefined)
// instead of a working one. Only relevant to tests; real browsers have no
// such conflict. Replace it with a tiny working in-memory Storage so
// anything under test that touches localStorage (conversation-history.ts)
// behaves the way it does in a real browser.
class MemoryStorage implements Storage {
  private store = new Map<string, string>();
  get length() {
    return this.store.size;
  }
  clear() {
    this.store.clear();
  }
  getItem(key: string) {
    return this.store.has(key) ? this.store.get(key)! : null;
  }
  key(index: number) {
    return Array.from(this.store.keys())[index] ?? null;
  }
  removeItem(key: string) {
    this.store.delete(key);
  }
  setItem(key: string, value: string) {
    this.store.set(key, String(value));
  }
}

for (const target of [globalThis, globalThis.window].filter(Boolean)) {
  Object.defineProperty(target, "localStorage", {
    value: new MemoryStorage(),
    configurable: true,
    writable: true,
  });
}

// Vitest doesn't inject test globals here (tests import from "vitest"
// explicitly), so @testing-library/react's automatic afterEach(cleanup)
// registration -- which relies on a global `afterEach` -- never fires on
// its own. Without this, DOM from one test's render() leaks into the next.
afterEach(() => {
  cleanup();
});
