// src/lib/utils/vn-date.test.ts
// @vitest-environment jsdom
/**
 * Unit tests for vn-date.ts timezone utilities.
 *
 * Validates:
 * - todayVN() returns YYYY-MM-DD in Asia/Ho_Chi_Minh timezone
 * - todayVN() handles UTC midnight → next day in VN (UTC+7)
 * - subDaysVN() arithmetic correctness
 * - subDaysVN() month/year boundary crossover
 * - startOfMonthVN() string manipulation
 */
import { describe, it, expect } from "vitest";
import { todayVN, subDaysVN, startOfMonthVN } from "./vn-date";

describe("todayVN", () => {
  it("returns ISO YYYY-MM-DD format", () => {
    const result = todayVN();
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("returns VN date when UTC is still previous day (e.g. UTC 20:00 = VN 03:00 next day)", () => {
    // UTC 2026-03-12T20:00:00Z → VN 2026-03-13T03:00:00+07:00
    const utcLateNight = new Date("2026-03-12T20:00:00Z");
    expect(todayVN(utcLateNight)).toBe("2026-03-13");
  });

  it("returns same VN date when UTC is early morning (UTC and VN same calendar day)", () => {
    // UTC 2026-03-13T10:00:00Z → VN 2026-03-13T17:00:00+07:00
    const utcMorning = new Date("2026-03-13T10:00:00Z");
    expect(todayVN(utcMorning)).toBe("2026-03-13");
  });

  it("handles year boundary: UTC Dec 31 23:00 → VN Jan 1", () => {
    // UTC 2025-12-31T23:00:00Z → VN 2026-01-01T06:00:00+07:00
    const utcNewYearEve = new Date("2025-12-31T23:00:00Z");
    expect(todayVN(utcNewYearEve)).toBe("2026-01-01");
  });

  it("handles UTC midnight exactly → VN 07:00 same day", () => {
    // UTC 2026-03-13T00:00:00Z → VN 2026-03-13T07:00:00+07:00
    const utcMidnight = new Date("2026-03-13T00:00:00Z");
    expect(todayVN(utcMidnight)).toBe("2026-03-13");
  });
});

describe("subDaysVN", () => {
  it("subtracts days within same month", () => {
    expect(subDaysVN("2026-03-13", 6)).toBe("2026-03-07");
  });

  it("subtracts days across month boundary", () => {
    expect(subDaysVN("2026-03-03", 5)).toBe("2026-02-26");
  });

  it("subtracts days across year boundary", () => {
    expect(subDaysVN("2026-01-02", 5)).toBe("2025-12-28");
  });

  it("subtracts 0 days returns same date", () => {
    expect(subDaysVN("2026-03-13", 0)).toBe("2026-03-13");
  });

  it("handles Feb 28 → Feb 29 in leap year", () => {
    // 2024 is a leap year
    expect(subDaysVN("2024-03-01", 1)).toBe("2024-02-29");
  });

  it("handles Feb 28 → Feb 28 in non-leap year", () => {
    expect(subDaysVN("2025-03-01", 1)).toBe("2025-02-28");
  });

  it("handles large subtraction (30 days)", () => {
    expect(subDaysVN("2026-03-13", 29)).toBe("2026-02-12");
  });
});

describe("startOfMonthVN", () => {
  it("replaces day with 01", () => {
    expect(startOfMonthVN("2026-03-13")).toBe("2026-03-01");
  });

  it("handles single-digit day", () => {
    expect(startOfMonthVN("2026-03-05")).toBe("2026-03-01");
  });

  it("handles last day of month", () => {
    expect(startOfMonthVN("2026-01-31")).toBe("2026-01-01");
  });

  it("idempotent on first day", () => {
    expect(startOfMonthVN("2026-03-01")).toBe("2026-03-01");
  });
});
