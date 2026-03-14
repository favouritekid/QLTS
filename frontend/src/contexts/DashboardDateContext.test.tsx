// src/contexts/DashboardDateContext.test.tsx
// @vitest-environment jsdom
/**
 * Tests for DashboardDateContext URL sync behavior.
 *
 * Validates:
 * - init from URL range=30d
 * - init from URL from=...&to=...
 * - default when URL has no date params
 * - setPreset calls pushState with range param
 * - setCustomRange calls pushState with from/to params
 * - popstate restores date state from URL
 * - popstate resets to default when URL has no date params
 */
import { render, act } from "@testing-library/react";
import { renderHook } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("@/lib/utils/vn-date", () => ({
  todayVN: () => "2026-03-13",
  subDaysVN: (_today: string, days: number) => {
    const d = new Date(2026, 2, 13);
    d.setDate(d.getDate() - days);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${dd}`;
  },
  startOfMonthVN: () => "2026-03-01",
}));

import {
  DashboardDateProvider,
  useDashboardDate,
  formatDateForAPI,
} from "./DashboardDateContext";

/** Helper: set window.location.search */
function setUrlSearch(search: string) {
  Object.defineProperty(window, "location", {
    value: { ...window.location, search, pathname: "/dashboard/officer" },
    writable: true,
  });
}

/** Render hook inside DashboardDateProvider */
function renderDateHook(defaultPreset: "7d" | "30d" | "this_month" | "custom" = "7d") {
  return renderHook(() => useDashboardDate(), {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <DashboardDateProvider defaultPreset={defaultPreset}>
        {children}
      </DashboardDateProvider>
    ),
  });
}

describe("DashboardDateContext", () => {
  let originalLocation: Location;
  let pushStateSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    originalLocation = window.location;
    pushStateSpy = vi.spyOn(window.history, "pushState").mockImplementation(() => {});
    setUrlSearch("");
  });

  afterEach(() => {
    Object.defineProperty(window, "location", { value: originalLocation, writable: true });
    pushStateSpy.mockRestore();
  });

  // =========================================================================
  // Init from URL
  // =========================================================================

  it("initializes preset from URL range=30d", () => {
    setUrlSearch("?range=30d");
    const { result } = renderDateHook();
    expect(result.current.preset).toBe("30d");
  });

  it("initializes preset from URL range=this_month", () => {
    setUrlSearch("?range=this_month");
    const { result } = renderDateHook();
    expect(result.current.preset).toBe("this_month");
  });

  it("initializes custom range from URL from/to params", () => {
    setUrlSearch("?from=2026-02-01&to=2026-02-28");
    const { result } = renderDateHook();
    expect(result.current.preset).toBe("custom");
    expect(result.current.startDate).toBe("2026-02-01");
    expect(result.current.endDate).toBe("2026-02-28");
  });

  it("falls back to default preset when URL has no date params", () => {
    setUrlSearch("");
    const { result } = renderDateHook("7d");
    expect(result.current.preset).toBe("7d");
    // 7d = today - 6 days
    expect(result.current.startDate).toBe("2026-03-07");
    expect(result.current.endDate).toBe("2026-03-13");
  });

  it("ignores invalid date strings in from/to", () => {
    setUrlSearch("?from=not-a-date&to=2026-02-28");
    const { result } = renderDateHook("7d");
    // Should fall back to default
    expect(result.current.preset).toBe("7d");
  });

  it("ignores range=custom in URL (custom requires from/to)", () => {
    setUrlSearch("?range=custom");
    const { result } = renderDateHook("7d");
    expect(result.current.preset).toBe("7d");
  });

  // =========================================================================
  // setPreset → pushState
  // =========================================================================

  it("setPreset calls pushState with range param", () => {
    setUrlSearch("");
    const { result } = renderDateHook();

    act(() => {
      result.current.setPreset("30d");
    });

    expect(result.current.preset).toBe("30d");
    expect(pushStateSpy).toHaveBeenCalled();
    const lastUrl = pushStateSpy.mock.calls[pushStateSpy.mock.calls.length - 1][2] as string;
    expect(lastUrl).toContain("range=30d");
    // Should NOT have from/to
    expect(lastUrl).not.toContain("from=");
    expect(lastUrl).not.toContain("to=");
  });

  // =========================================================================
  // setCustomRange → pushState
  // =========================================================================

  it("setCustomRange calls pushState with from/to params", () => {
    setUrlSearch("");
    const { result } = renderDateHook();

    const customFrom = new Date(2026, 0, 15); // Jan 15
    const customTo = new Date(2026, 1, 15); // Feb 15

    act(() => {
      result.current.setCustomRange({ from: customFrom, to: customTo });
    });

    expect(result.current.preset).toBe("custom");
    expect(result.current.startDate).toBe("2026-01-15");
    expect(result.current.endDate).toBe("2026-02-15");
    expect(pushStateSpy).toHaveBeenCalled();
    const lastUrl = pushStateSpy.mock.calls[pushStateSpy.mock.calls.length - 1][2] as string;
    expect(lastUrl).toContain("from=2026-01-15");
    expect(lastUrl).toContain("to=2026-02-15");
    // Should NOT have range= (named presets cleared)
    expect(lastUrl).not.toContain("range=");
  });

  // =========================================================================
  // popstate restore
  // =========================================================================

  it("restores preset from URL on popstate", () => {
    setUrlSearch("?range=7d");
    const { result } = renderDateHook();
    expect(result.current.preset).toBe("7d");

    // Simulate back to 30d
    setUrlSearch("?range=30d");
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(result.current.preset).toBe("30d");
  });

  it("restores custom from/to from URL on popstate", () => {
    setUrlSearch("");
    const { result } = renderDateHook();
    expect(result.current.preset).toBe("7d");

    setUrlSearch("?from=2026-01-01&to=2026-01-31");
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(result.current.preset).toBe("custom");
    expect(result.current.startDate).toBe("2026-01-01");
    expect(result.current.endDate).toBe("2026-01-31");
  });

  it("resets to default preset on popstate when URL has no date params", () => {
    setUrlSearch("?range=30d");
    const { result } = renderDateHook("7d");
    expect(result.current.preset).toBe("30d");

    // Back to clean URL
    setUrlSearch("");
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    // Should reset to default "7d", not keep stale "30d"
    expect(result.current.preset).toBe("7d");
    expect(result.current.startDate).toBe("2026-03-07");
    expect(result.current.endDate).toBe("2026-03-13");
  });

  // =========================================================================
  // formatDateForAPI utility
  // =========================================================================

  it("formats Date to YYYY-MM-DD string", () => {
    expect(formatDateForAPI(new Date(2026, 0, 5))).toBe("2026-01-05");
    expect(formatDateForAPI(new Date(2026, 11, 31))).toBe("2026-12-31");
  });
});
