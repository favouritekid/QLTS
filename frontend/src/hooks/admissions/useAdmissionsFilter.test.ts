// src/hooks/admissions/useAdmissionsFilter.test.ts
// @vitest-environment jsdom
/**
 * useAdmissionsFilter Hook Tests
 *
 * Validates BUG-18 fix: STATUS_TABS must include revision_requested
 * in "pending" tab and withdrawn in "rejected" tab.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { createElement } from "react"
import { renderToString } from "react-dom/server"
import { renderHook, act, waitFor } from "@testing-library/react"

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/admissions",
}))

// Mock window.history.replaceState for jsdom
let replaceStateSpy: ReturnType<typeof vi.fn>

import { useAdmissionsFilter } from "./useAdmissionsFilter"

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useAdmissionsFilter", () => {
  beforeEach(() => {
    vi.clearAllMocks()

    replaceStateSpy = vi.fn()
    vi.spyOn(window.history, "replaceState").mockImplementation(
      replaceStateSpy as unknown as typeof window.history.replaceState,
    )

    vi.spyOn(Storage.prototype, "getItem").mockReturnValue(null)
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {})
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {})
  })

  describe("SSR-safe persisted filters", () => {
    it("does not read localStorage during the server render path", () => {
      const getItemSpy = vi.spyOn(Storage.prototype, "getItem").mockReturnValue(
        JSON.stringify({
          version: 1,
          data: {
            page: 1,
            search: "",
            statusFilters: ["draft"],
            majorFilter: "",
            academicYear: new Date().getFullYear(),
            degreeLevelFilter: "",
            paymentStatusFilter: "",
            dateFrom: "",
            dateTo: "",
            activeTab: "draft",
          },
        }),
      )

      function Probe() {
        const { state } = useAdmissionsFilter()
        return createElement("span", null, state.activeTab)
      }

      expect(renderToString(createElement(Probe))).toContain("all")
      expect(getItemSpy).not.toHaveBeenCalled()
    })

    it("restores localStorage filters after hydration", async () => {
      vi.spyOn(Storage.prototype, "getItem").mockReturnValue(
        JSON.stringify({
          version: 1,
          data: {
            page: 2,
            search: "Nguyen",
            statusFilters: ["draft"],
            majorFilter: "3",
            academicYear: new Date().getFullYear() - 1,
            degreeLevelFilter: "bachelor",
            paymentStatusFilter: "paid",
            dateFrom: "2026-01-01",
            dateTo: "2026-01-31",
            activeTab: "draft",
          },
        }),
      )

      const { result } = renderHook(() => useAdmissionsFilter())

      await waitFor(() => {
        expect(result.current.state.activeTab).toBe("draft")
      })

      expect(result.current.state.page).toBe(2)
      expect(result.current.state.search).toBe("Nguyen")
      expect(result.current.state.statusFilters).toEqual(["draft"])
      expect(result.current.state.majorFilter).toBe("3")
      expect(result.current.state.academicYear).toBe(new Date().getFullYear() - 1)
      expect(result.current.state.degreeLevelFilter).toBe("bachelor")
      expect(result.current.state.paymentStatusFilter).toBe("paid")
      expect(result.current.state.dateFrom).toBe("2026-01-01")
      expect(result.current.state.dateTo).toBe("2026-01-31")
    })
  })

  describe("STATUS_TABS mapping (BUG-18)", () => {
    it('should include "revision_requested" in the "pending" tab statuses', () => {
      const { result } = renderHook(() => useAdmissionsFilter())

      act(() => {
        result.current.handlers.handleTabClick("pending")
      })

      expect(result.current.state.activeTab).toBe("pending")
      expect(result.current.state.statusFilters).toContain("submitted")
      expect(result.current.state.statusFilters).toContain("resubmitted")
      expect(result.current.state.statusFilters).toContain("revision_requested")
    })

    it('should include "withdrawn" in the "rejected" tab statuses', () => {
      const { result } = renderHook(() => useAdmissionsFilter())

      act(() => {
        result.current.handlers.handleTabClick("rejected")
      })

      expect(result.current.state.activeTab).toBe("rejected")
      expect(result.current.state.statusFilters).toContain("rejected")
      expect(result.current.state.statusFilters).toContain("withdrawn")
    })

    it('should set empty statusFilters for the "all" tab', () => {
      const { result } = renderHook(() => useAdmissionsFilter())

      // First select a specific tab
      act(() => {
        result.current.handlers.handleTabClick("pending")
      })
      expect(result.current.state.statusFilters.length).toBeGreaterThan(0)

      // Then switch to "all"
      act(() => {
        result.current.handlers.handleTabClick("all")
      })

      expect(result.current.state.activeTab).toBe("all")
      expect(result.current.state.statusFilters).toEqual([])
    })

    it('should set statusFilters for the "approved" tab (admitted/overridden, NOT confirmed)', () => {
      const { result } = renderHook(() => useAdmissionsFilter())

      act(() => {
        result.current.handlers.handleTabClick("approved")
      })

      expect(result.current.state.activeTab).toBe("approved")
      expect(result.current.state.statusFilters).toContain("approved")
      expect(result.current.state.statusFilters).toContain("admitted")
      expect(result.current.state.statusFilters).toContain("overridden")
      // `confirmed` has its OWN tab — it must NOT be folded into approved, or the
      // "Đã duyệt" count (which excludes confirmed) would disagree with the result.
      expect(result.current.state.statusFilters).not.toContain("confirmed")
    })

    it('should filter to ["confirmed"] for the "confirmed" tab (regression: hook drift left it empty → showed ALL)', () => {
      const { result } = renderHook(() => useAdmissionsFilter())

      act(() => {
        result.current.handlers.handleTabClick("confirmed")
      })

      expect(result.current.state.activeTab).toBe("confirmed")
      expect(result.current.state.statusFilters).toEqual(["confirmed"])
    })

    it("should reset page to 1 when switching tabs", () => {
      const { result } = renderHook(() => useAdmissionsFilter())

      // Change page first
      act(() => {
        result.current.handlers.setPage(5)
      })
      expect(result.current.state.page).toBe(5)

      // Switch tab — page should reset
      act(() => {
        result.current.handlers.handleTabClick("pending")
      })
      expect(result.current.state.page).toBe(1)
    })
  })
})
