// src/lib/hooks/use-kpi-catalog.test.ts
/**
 * Drift tests for KPI catalog frontend fallback.
 *
 * Validates LOCAL_FALLBACK shape and invariants that must match backend
 * kpi_catalog.py METRIC_CATALOG. If these tests fail, the frontend
 * fallback has drifted from the canonical backend catalog.
 */
import { describe, it, expect } from "vitest";
import { LOCAL_FALLBACK, isCalendarMonth } from "./use-kpi-catalog";
import type { MetricCatalogEntry } from "../api/meta";

const EXPECTED_CODES = new Set([
  "consultations_daily",
  "conversion_rate",
  "win_rate",
  "response_time_hours",
  "enrollments_monthly",
  "enrollments_annual",
  "sla_compliance_rate",
  "consultation_effectiveness",
]);

describe("LOCAL_FALLBACK catalog invariants", () => {
  it("has exactly 8 metrics", () => {
    expect(LOCAL_FALLBACK).toHaveLength(8);
  });

  it("contains the canonical code set", () => {
    const codes = new Set(LOCAL_FALLBACK.map((m) => m.code));
    expect(codes).toEqual(EXPECTED_CODES);
  });

  it("has no duplicate codes", () => {
    const codes = LOCAL_FALLBACK.map((m) => m.code);
    expect(new Set(codes).size).toBe(codes.length);
  });

  it.each(LOCAL_FALLBACK.map((m) => [m.code, m]))(
    "%s has valid unit",
    (_code, m) => {
      expect(["count", "percent", "hours"]).toContain(
        (m as MetricCatalogEntry).unit,
      );
    },
  );

  it.each(LOCAL_FALLBACK.map((m) => [m.code, m]))(
    "%s has valid period_type",
    (_code, m) => {
      expect(["daily", "monthly", "annual"]).toContain(
        (m as MetricCatalogEntry).period_type,
      );
    },
  );

  it.each(LOCAL_FALLBACK.map((m) => [m.code, m]))(
    "%s has positive default_value",
    (_code, m) => {
      expect((m as MetricCatalogEntry).default_value).toBeGreaterThan(0);
    },
  );

  it.each(LOCAL_FALLBACK.map((m) => [m.code, m]))(
    "%s has all 4 display_aliases",
    (_code, m) => {
      const aliases = (m as MetricCatalogEntry).display_aliases;
      expect(Object.keys(aliases).sort()).toEqual(
        ["annual_progress", "config", "dashboard", "planning"],
      );
      for (const val of Object.values(aliases)) {
        expect(val.trim().length).toBeGreaterThan(0);
      }
    },
  );

  it.each(LOCAL_FALLBACK.map((m) => [m.code, m]))(
    "%s has valid comparison policy shape",
    (_code, m) => {
      const cp = (m as MetricCatalogEntry).comparison;
      expect(typeof cp.comparable).toBe("boolean");
      expect(typeof cp.requires_period_match).toBe("boolean");
      expect([null, "daily", "monthly", "annual"]).toContain(cp.target_period);
    },
  );

  it("response_time_hours has higher_is_better=false", () => {
    const rt = LOCAL_FALLBACK.find((m) => m.code === "response_time_hours");
    expect(rt?.higher_is_better).toBe(false);
  });

  it("non-comparable metrics have caveats", () => {
    const nonComparable = LOCAL_FALLBACK.filter(
      (m) => !m.comparison.comparable,
    );
    expect(nonComparable.length).toBeGreaterThan(0);
    for (const m of nonComparable) {
      expect(m.comparison.caveat).toBeTruthy();
    }
  });

  it("consultations_daily does not require period match", () => {
    const cd = LOCAL_FALLBACK.find((m) => m.code === "consultations_daily");
    expect(cd?.comparison.comparable).toBe(true);
    expect(cd?.comparison.requires_period_match).toBe(false);
  });

  it("enrollments_monthly requires period match", () => {
    const em = LOCAL_FALLBACK.find((m) => m.code === "enrollments_monthly");
    expect(em?.comparison.comparable).toBe(true);
    expect(em?.comparison.requires_period_match).toBe(true);
    expect(em?.comparison.target_period).toBe("monthly");
  });
});

describe("LOCAL_FALLBACK exact values (drift detection)", () => {
  it("consultations_daily defaults match backend", () => {
    const m = LOCAL_FALLBACK.find((e) => e.code === "consultations_daily")!;
    expect(m.default_value).toBe(10);
    expect(m.period_type).toBe("daily");
    expect(m.unit).toBe("count");
    expect(m.display_name).toBe("Tư vấn/ngày");
  });

  it("enrollments_annual defaults match backend", () => {
    const m = LOCAL_FALLBACK.find((e) => e.code === "enrollments_annual")!;
    expect(m.default_value).toBe(80);
    expect(m.period_type).toBe("annual");
    expect(m.actual_kind).toBe("ytd_count");
  });

  it("win_rate comparison policy matches backend", () => {
    const m = LOCAL_FALLBACK.find((e) => e.code === "win_rate")!;
    expect(m.comparison).toEqual({
      comparable: true,
      requires_period_match: true,
      target_period: "monthly",
      caveat:
        "Dashboard denominator = won+lost (excludes neutral final). Planning snapshot denominator = all is_final_stage leads. If neutral final stages exist, denominators differ.",
    });
  });
});

describe("isCalendarMonth utility", () => {
  it("returns true for exact calendar month", () => {
    expect(
      isCalendarMonth({
        start: new Date(2026, 0, 1),
        end: new Date(2026, 0, 31),
      }),
    ).toBe(true);
  });

  it("returns true for February (non-leap)", () => {
    expect(
      isCalendarMonth({
        start: new Date(2025, 1, 1),
        end: new Date(2025, 1, 28),
      }),
    ).toBe(true);
  });

  it("returns false for partial month", () => {
    expect(
      isCalendarMonth({
        start: new Date(2026, 0, 5),
        end: new Date(2026, 0, 31),
      }),
    ).toBe(false);
  });

  it("returns false for cross-month range", () => {
    expect(
      isCalendarMonth({
        start: new Date(2026, 0, 1),
        end: new Date(2026, 1, 28),
      }),
    ).toBe(false);
  });
});
