// src/hooks/admissions/useAdmissionsFilter.test.ts
// @vitest-environment jsdom
/**
 * useAdmissionsFilter Hook Tests
 *
 * Validates BUG-18 fix: STATUS_TABS must include revision_requested
 * in "pending" tab and withdrawn in "rejected" tab.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { renderHook, act } from "@testing-library/react"

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

    it('should set statusFilters for the "approved" tab', () => {
      const { result } = renderHook(() => useAdmissionsFilter())

      act(() => {
        result.current.handlers.handleTabClick("approved")
      })

      expect(result.current.state.activeTab).toBe("approved")
      expect(result.current.state.statusFilters).toContain("approved")
      expect(result.current.state.statusFilters).toContain("confirmed")
      expect(result.current.state.statusFilters).toContain("overridden")
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
