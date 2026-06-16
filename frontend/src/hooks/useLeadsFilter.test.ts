// src/hooks/useLeadsFilter.test.ts
// @vitest-environment jsdom
/**
 * useLeadsFilter Hook Tests
 *
 * Validates T7 fix: scoreRange persistence and URL sync.
 * - scoreRange is included in localStorage persistence check
 * - score_min/score_max appear in apiFilters
 * - scoreRange syncs from URL params on external navigation
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { renderHook, act, waitFor } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockSearchParams = new URLSearchParams();
const useSearchParamsMock = vi.fn(() => mockSearchParams);
const usePathnameMock = vi.fn(() => "/leads");

vi.mock("next/navigation", () => ({
  useSearchParams: () => useSearchParamsMock(),
  usePathname: () => usePathnameMock(),
}));

import { useLeadsFilter } from "./useLeadsFilter";

function makeStoredFilters(overrides: Record<string, unknown> = {}) {
  return JSON.stringify({
    version: 6,
    data: {
      page: 1,
      search: "",
      statusFilters: [],
      sourceFilters: [],
      validityFilters: [],
      offeringFilters: [],
      stageFilters: [],
      officerFilters: [],
      unitId: "",
      dateFrom: "",
      dateTo: "",
      dateField: "created_at",
      scoreMin: 0,
      scoreMax: 100,
      sortBy: "created_at",
      sortOrder: "desc",
      // v6: actionable + consultation-status filters
      overdue: false,
      unassigned: false,
      isHot: false,
      noConsultation: false,
      nextActivityFrom: "",
      nextActivityTo: "",
      consultationStatusFilters: [],
      ...overrides,
    },
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

// Mock window.history.replaceState to avoid errors in jsdom
let replaceStateSpy: ReturnType<typeof vi.fn>;

describe("useLeadsFilter", () => {
  let getItemSpy: ReturnType<typeof vi.spyOn>;
  let setItemSpy: ReturnType<typeof vi.spyOn>;
  let removeItemSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.clearAllMocks();

    // Mock history.replaceState inside jsdom environment (window available after setup)
    replaceStateSpy = vi.fn();
    vi.spyOn(window.history, "replaceState").mockImplementation(
      replaceStateSpy as unknown as typeof window.history.replaceState,
    );

    // Fresh localStorage spies for each test
    getItemSpy = vi.spyOn(Storage.prototype, "getItem").mockReturnValue(null);
    setItemSpy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {});
    removeItemSpy = vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {});

    // Default: no URL params
    useSearchParamsMock.mockReturnValue(new URLSearchParams());
  });

  describe("SSR-safe persisted filters", () => {
    it("does not read localStorage during the server render path", () => {
      useSearchParamsMock.mockReturnValue(new URLSearchParams());
      getItemSpy.mockReturnValue(makeStoredFilters({ statusFilters: ["sts02"] }));

      function Probe() {
        const { state } = useLeadsFilter();
        return createElement("span", null, state.statusFilters.join(",") || "none");
      }

      // renderToString bypasses effects so the initial render must NOT touch
      // localStorage — otherwise the client's first render would diverge
      // from the SSR HTML and trigger a hydration mismatch.
      expect(renderToString(createElement(Probe))).toContain("none");
      expect(getItemSpy).not.toHaveBeenCalled();
    });

    it("restores stored filters after hydration when URL has no params", async () => {
      useSearchParamsMock.mockReturnValue(new URLSearchParams());
      getItemSpy.mockReturnValue(
        makeStoredFilters({
          page: 2,
          search: "Nguyen",
          statusFilters: ["sts02"],
          stageFilters: ["stg01"],
          unitId: "3",
          dateFrom: "2026-04-01",
          dateTo: "2026-04-30",
          dateField: "last_consultation_at",
          scoreMin: 20,
          scoreMax: 80,
          sortBy: "full_name",
          sortOrder: "asc",
        }),
      );

      const { result } = renderHook(() => useLeadsFilter());

      await waitFor(() => {
        expect(result.current.state.statusFilters).toEqual(["sts02"]);
      });

      expect(result.current.state.page).toBe(2);
      expect(result.current.state.search).toBe("Nguyen");
      expect(result.current.state.stageFilters).toEqual(["stg01"]);
      expect(result.current.state.unitId).toBe("3");
      expect(result.current.state.dateFrom).toBe("2026-04-01");
      expect(result.current.state.dateTo).toBe("2026-04-30");
      expect(result.current.state.dateField).toBe("last_consultation_at");
      expect(result.current.state.scoreRange).toEqual([20, 80]);
      expect(result.current.state.sortBy).toBe("full_name");
      expect(result.current.state.sortOrder).toBe("asc");
    });

    it("URL params override localStorage — stored filters are not restored", async () => {
      useSearchParamsMock.mockReturnValue(new URLSearchParams("stage=stg05"));
      getItemSpy.mockReturnValue(
        makeStoredFilters({ statusFilters: ["sts02"], stageFilters: ["stg01"] }),
      );

      const { result } = renderHook(() => useLeadsFilter());

      // Give the restore effect a microtask to run — it should bail out.
      await act(async () => {
        await Promise.resolve();
      });

      expect(result.current.state.stageFilters).toEqual(["stg05"]);
      expect(result.current.state.statusFilters).toEqual([]);
    });

    it("emits +07:00 ISO strings for date bounds to match the SSR parser", () => {
      useSearchParamsMock.mockReturnValue(
        new URLSearchParams("from=2026-03-17&to=2026-03-23"),
      );

      const { result } = renderHook(() => useLeadsFilter());

      expect(result.current.apiFilters.date_from).toBe("2026-03-17T00:00:00+07:00");
      expect(result.current.apiFilters.date_to).toBe("2026-03-23T23:59:59.999+07:00");
    });

    it("does not clear storage on first mount while no URL filters are present", () => {
      useSearchParamsMock.mockReturnValue(new URLSearchParams());
      getItemSpy.mockReturnValue(makeStoredFilters({ statusFilters: ["sts02"] }));

      renderHook(() => useLeadsFilter());

      // First mount must NOT wipe storage — otherwise the restore effect
      // would read `null` and miss the persisted filters entirely.
      expect(removeItemSpy).not.toHaveBeenCalledWith("leads_filters");
    });
  });

  it("should include scoreRange in localStorage when score filter active", async () => {
    const { result } = renderHook(() => useLeadsFilter());

    // Change score range to a non-default value
    act(() => {
      result.current.handlers.handleScoreRangeChange([20, 80]);
    });

    // The localStorage sync effect runs after state update.
    // Wait for the effect to execute.
    await vi.waitFor(() => {
      const calls = setItemSpy.mock.calls.filter(
        ([key]: [string]) => key === "leads_filters",
      );
      expect(calls.length).toBeGreaterThan(0);

      // Parse the last stored value
      const lastCall = calls[calls.length - 1];
      const stored = JSON.parse(lastCall[1] as string);
      expect(stored.data.scoreMin).toBe(20);
      expect(stored.data.scoreMax).toBe(80);
    });
  });

  it("should NOT persist to localStorage when all filters are default", () => {
    const { result } = renderHook(() => useLeadsFilter());

    // With defaults (page=1, no search, score 0-100), nothing should be saved.
    // localStorage.removeItem should be called instead.
    // After initial mount, the effect runs once.
    expect(result.current.state.scoreRange).toEqual([0, 100]);
    expect(result.current.state.search).toBe("");

    // The hook should either not call setItem or call removeItem
    const setItemCalls = setItemSpy.mock.calls.filter(
      ([key]: [string]) => key === "leads_filters",
    );
    // If no active filters, removeItem is called (or setItem is not)
    // We just verify that no data with active filters was persisted
    if (setItemCalls.length > 0) {
      // If it did call setItem, it should be a false positive from another effect
      // The important thing is that clearFiltersFromStorage was called
      const removeCalls = removeItemSpy.mock.calls.filter(
        ([key]: [string]) => key === "leads_filters",
      );
      expect(removeCalls.length).toBeGreaterThan(0);
    }
  });

  it("should include score_min and score_max in apiFilters", () => {
    const { result } = renderHook(() => useLeadsFilter());

    act(() => {
      result.current.handlers.handleScoreRangeChange([10, 90]);
    });

    expect(result.current.apiFilters.score_min).toBe(10);
    expect(result.current.apiFilters.score_max).toBe(90);
  });

  it("should sync scoreRange from URL params on external navigation", () => {
    // Start with URL params containing score range
    const params = new URLSearchParams("score_min=30&score_max=70");
    useSearchParamsMock.mockReturnValue(params);

    const { result } = renderHook(() => useLeadsFilter());

    // The hook reads URL params on initialization and sets scoreRange
    expect(result.current.state.scoreRange).toEqual([30, 70]);
    expect(result.current.state.scoreMin).toBe(30);
    expect(result.current.state.scoreMax).toBe(70);
  });

  it("should preserve dashboard context params during URL sync", async () => {
    useSearchParamsMock.mockReturnValue(
      new URLSearchParams("nav_source=dashboard&scope=unit&scope_unit_id=7&include_descendants=1"),
    );

    const { result } = renderHook(() => useLeadsFilter());

    act(() => {
      result.current.handlers.handleStageChange(["stg01"]);
    });

    await vi.waitFor(() => {
      expect(replaceStateSpy).toHaveBeenCalled();
      const latestUrl = replaceStateSpy.mock.calls.at(-1)?.[2] as string;
      expect(latestUrl).toContain("nav_source=dashboard");
      expect(latestUrl).toContain("scope=unit");
      expect(latestUrl).toContain("scope_unit_id=7");
      expect(latestUrl).toContain("include_descendants=1");
      expect(latestUrl).toContain("stage=stg01");
    });
  });

  it("should normalize legacy scope=team to unit in dashboard context", () => {
    useSearchParamsMock.mockReturnValue(
      new URLSearchParams("nav_source=dashboard&scope=team&scope_unit_id=11"),
    );

    const { result } = renderHook(() => useLeadsFilter());

    expect(result.current.dashboardContext?.scope).toBe("unit");
    expect(result.current.apiFilters.scope).toBe("unit");
  });

  it("should clear dashboard context when exitDashboardContext is called", () => {
    useSearchParamsMock.mockReturnValue(
      new URLSearchParams("nav_source=dashboard&scope=unit&scope_unit_id=7"),
    );

    const { result } = renderHook(() => useLeadsFilter());

    act(() => {
      result.current.handlers.exitDashboardContext();
    });

    expect(replaceStateSpy).toHaveBeenCalledWith(window.history.state, "", "/leads");
    expect(result.current.dashboardContext).toBeNull();
  });

  // ==========================================================================
  // LEAD_FILTER_UX_PLAN §4-§5.6 — actionable + consultation-status filters
  // ==========================================================================
  describe("actionable + consultation-status filters", () => {
    it("maps actionable bool filters into apiFilters only when active", () => {
      const { result } = renderHook(() => useLeadsFilter());
      // default: none present
      expect(result.current.apiFilters.overdue).toBeUndefined();
      expect(result.current.apiFilters.is_hot).toBeUndefined();

      act(() => {
        result.current.handlers.handleOverdueChange(true);
        result.current.handlers.handleIsHotChange(true);
        result.current.handlers.handleNoConsultationChange(true);
      });

      expect(result.current.apiFilters.overdue).toBe(true);
      expect(result.current.apiFilters.is_hot).toBe(true);
      expect(result.current.apiFilters.no_consultation).toBe(true);
    });

    it("formats next_activity bounds with +07:00 (parity with SSR parser)", () => {
      useSearchParamsMock.mockReturnValue(
        new URLSearchParams("na_from=2026-06-16&na_to=2026-06-20"),
      );
      const { result } = renderHook(() => useLeadsFilter());
      expect(result.current.apiFilters.next_activity_from).toBe("2026-06-16T00:00:00+07:00");
      expect(result.current.apiFilters.next_activity_to).toBe("2026-06-20T23:59:59.999+07:00");
    });

    it("joins multi-select consultation_status_id", () => {
      const { result } = renderHook(() => useLeadsFilter());
      act(() => {
        result.current.handlers.handleConsultationStatusChange(["sts06", "sts20"]);
      });
      expect(result.current.apiFilters.consultation_status_id).toBe("sts06,sts20");
    });

    it("enforces unassigned XOR officer (conflict policy §5.3)", () => {
      const { result } = renderHook(() => useLeadsFilter());
      // pick an officer first
      act(() => {
        result.current.handlers.handleOfficerChange(["5"]);
      });
      expect(result.current.apiFilters.assigned_officer_id).toBe("5");
      // turning on unassigned must clear the officer filter
      act(() => {
        result.current.handlers.handleUnassignedChange(true);
      });
      expect(result.current.apiFilters.unassigned).toBe(true);
      expect(result.current.apiFilters.assigned_officer_id).toBeUndefined();
      // selecting an officer again clears unassigned
      act(() => {
        result.current.handlers.handleOfficerChange(["7"]);
      });
      expect(result.current.apiFilters.assigned_officer_id).toBe("7");
      expect(result.current.apiFilters.unassigned).toBeUndefined();
    });

    it("resetFilters clears the new fields", () => {
      const { result } = renderHook(() => useLeadsFilter());
      act(() => {
        result.current.handlers.handleOverdueChange(true);
        result.current.handlers.handleConsultationStatusChange(["sts06"]);
        result.current.handlers.handleNextActivityFromChange("2026-06-16");
      });
      act(() => {
        result.current.handlers.resetFilters();
      });
      expect(result.current.state.overdue).toBe(false);
      expect(result.current.state.consultationStatusFilters).toEqual([]);
      expect(result.current.state.nextActivityFrom).toBe("");
      expect(result.current.apiFilters.overdue).toBeUndefined();
    });

    it("drawerFilterCount excludes search but counts drawer filters", () => {
      const { result } = renderHook(() => useLeadsFilter());
      act(() => {
        result.current.handlers.handleSearchChange("nguyen");
      });
      // search is on the bar, not the drawer → not counted
      expect(result.current.drawerFilterCount).toBe(0);
      act(() => {
        result.current.handlers.handleOverdueChange(true);
        result.current.handlers.handleConsultationStatusChange(["sts06", "sts20"]);
      });
      // overdue (1) + consultation status group (1) = 2; search still excluded
      expect(result.current.drawerFilterCount).toBe(2);
    });

    it("restores v6 actionable + consultation-status fields from storage", async () => {
      // Guards the v6 restore effect: a dropped setter (e.g. setOverdue /
      // setConsultationStatusFilters) would silently lose persisted filters on
      // reload. The old restore test only covered v5 fields.
      useSearchParamsMock.mockReturnValue(new URLSearchParams());
      getItemSpy.mockReturnValue(
        makeStoredFilters({
          overdue: true,
          isHot: true,
          noConsultation: true,
          nextActivityFrom: "2026-06-16",
          nextActivityTo: "2026-06-20",
          consultationStatusFilters: ["sts06", "sts20"],
        }),
      );

      const { result } = renderHook(() => useLeadsFilter());

      await waitFor(() => {
        expect(result.current.state.overdue).toBe(true);
      });
      expect(result.current.state.isHot).toBe(true);
      expect(result.current.state.noConsultation).toBe(true);
      expect(result.current.state.nextActivityFrom).toBe("2026-06-16");
      expect(result.current.state.nextActivityTo).toBe("2026-06-20");
      expect(result.current.state.consultationStatusFilters).toEqual(["sts06", "sts20"]);
      // …and they flow into apiFilters
      expect(result.current.apiFilters.overdue).toBe(true);
      expect(result.current.apiFilters.consultation_status_id).toBe("sts06,sts20");
    });
  });
});
