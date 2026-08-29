import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cacheSize, clearCache, getCached, normalizeQuestion, setCached } from "../query-cache";

beforeEach(() => {
  clearCache();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("normalizeQuestion", () => {
  it("trims, lowercases, and collapses whitespace", () => {
    expect(normalizeQuestion("  What About TATA?  ")).toBe("what about tata?");
    expect(normalizeQuestion("Tata   in    1960")).toBe("tata in 1960");
  });
});

describe("getCached / setCached", () => {
  it("returns undefined for a question never cached", () => {
    expect(getCached("anything")).toBeUndefined();
  });

  it("returns the cached value for the exact same question", () => {
    setCached("What did Sampada say about Tata in 1960?", { answer: "cached" });
    expect(getCached("What did Sampada say about Tata in 1960?")).toEqual({ answer: "cached" });
  });

  it("treats differently-cased/whitespaced questions as the same exact query", () => {
    setCached("What did Sampada say about Tata in 1960?", { answer: "cached" });
    expect(getCached("  what did sampada say about tata in 1960?  ")).toEqual({ answer: "cached" });
  });

  it("treats genuinely different questions as distinct cache entries", () => {
    setCached("Question A", { answer: "A" });
    expect(getCached("Question B")).toBeUndefined();
  });

  it("expires an entry after the TTL elapses", () => {
    setCached("q", { answer: "cached" });
    expect(getCached("q")).toEqual({ answer: "cached" });

    vi.advanceTimersByTime(10 * 60 * 1000 + 1);

    expect(getCached("q")).toBeUndefined();
  });

  it("does not expire an entry just before the TTL elapses", () => {
    setCached("q", { answer: "cached" });
    vi.advanceTimersByTime(10 * 60 * 1000 - 1);
    expect(getCached("q")).toEqual({ answer: "cached" });
  });

  it("clearCache removes every cached entry", () => {
    setCached("q1", { answer: "a" });
    setCached("q2", { answer: "b" });
    clearCache();
    expect(getCached("q1")).toBeUndefined();
    expect(getCached("q2")).toBeUndefined();
    expect(cacheSize()).toBe(0);
  });

  it("evicts the oldest entry once the cache is full", () => {
    for (let i = 0; i < 500; i++) {
      setCached(`q${i}`, i);
    }
    expect(cacheSize()).toBe(500);
    expect(getCached("q0")).toBe(0);

    setCached("q500", 500);

    expect(cacheSize()).toBe(500);
    expect(getCached("q0")).toBeUndefined(); // oldest evicted
    expect(getCached("q500")).toBe(500);
  });
});
