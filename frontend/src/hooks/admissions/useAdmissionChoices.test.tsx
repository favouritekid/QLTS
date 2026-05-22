/**
 * useAdmissionChoices Hook Tests
 *
 * Code review 2026-05-22 P2 anchor — waitlist promote/reject flips
 * profile.status thật trên BE (waitlisted → admitted/rejected per
 * `admission_state_service.py:217`). FE phải invalidate KHÔNG chỉ
 * choices + detail mà còn list/status-counts/stats. Trước fix, hook
 * chỉ invalidate choices + detail → list rows/badges/dashboard stale
 * sau action.
 */

import { describe, it, expect, beforeEach, vi } from "vitest"
import { renderHook, waitFor, act } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { server } from "@/test/mocks/server"
import { createTestQueryClient } from "@/test/utils/test-utils"
import { QueryClientProvider } from "@tanstack/react-query"
import {
  usePromoteWaitlistedChoice,
  useRejectWaitlistedChoice,
  useDeleteChoice,
  admissionChoiceKeys,
} from "./useAdmissionChoices"
import { admissionsKeys } from "./useAdmissions"

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"

const PROFILE_ID = 42
const CHOICE_ID = 7

function createWrapperWithClient() {
  const queryClient = createTestQueryClient()
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  Wrapper.displayName = "TestQueryClientWrapper"
  return { queryClient, Wrapper }
}

describe("useAdmissionChoices — waitlist status-flip cache invalidation (P2)", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe("usePromoteWaitlistedChoice", () => {
    it("invalidates choices + detail + lists + status-counts + stats", async () => {
      server.use(
        http.post(
          `${API_BASE_URL}/api/v2/admissions/:id/waitlist-promote`,
          () =>
            HttpResponse.json({
              choice_id: CHOICE_ID,
              decision: "admitted",
              profile_id: PROFILE_ID,
            }),
        ),
      )

      const { queryClient, Wrapper } = createWrapperWithClient()
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries")

      const { result } = renderHook(
        () => usePromoteWaitlistedChoice(PROFILE_ID),
        { wrapper: Wrapper },
      )

      act(() => {
        result.current.mutate({ choiceId: CHOICE_ID, reason: "Slot opened" })
      })

      await waitFor(() => expect(result.current.isSuccess).toBe(true))

      // Choice + detail (existing parity)
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          queryKey: admissionChoiceKeys.forProfile(PROFILE_ID),
        }),
      )
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          queryKey: ["admissions", "detail", PROFILE_ID],
        }),
      )

      // P2 anchor — list/status-counts/stats invalidation cho status flip
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: admissionsKeys.lists() }),
      )

      const statusCountsCalls = invalidateSpy.mock.calls.filter(([opts]) => {
        const key = (opts as { queryKey: readonly unknown[] }).queryKey
        return (
          Array.isArray(key) &&
          key[0] === "admissions" &&
          key[1] === "status-counts" &&
          key.length === 2
        )
      })
      expect(statusCountsCalls.length).toBeGreaterThan(0)

      const statsCalls = invalidateSpy.mock.calls.filter(([opts]) => {
        const key = (opts as { queryKey: readonly unknown[] }).queryKey
        return (
          Array.isArray(key) &&
          key[0] === "admissions" &&
          key[1] === "stats" &&
          key.length === 2
        )
      })
      expect(statsCalls.length).toBeGreaterThan(0)

      invalidateSpy.mockRestore()
    })
  })

  describe("useRejectWaitlistedChoice", () => {
    it("invalidates choices + detail + lists + status-counts + stats", async () => {
      server.use(
        http.post(
          `${API_BASE_URL}/api/v2/admissions/:id/waitlist-reject`,
          () =>
            HttpResponse.json({
              choice_id: CHOICE_ID,
              decision: "rejected",
              profile_id: PROFILE_ID,
            }),
        ),
      )

      const { queryClient, Wrapper } = createWrapperWithClient()
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries")

      const { result } = renderHook(
        () => useRejectWaitlistedChoice(PROFILE_ID),
        { wrapper: Wrapper },
      )

      act(() => {
        result.current.mutate({
          choiceId: CHOICE_ID,
          reason: "Closed without slot ten characters minimum",
        })
      })

      await waitFor(() => expect(result.current.isSuccess).toBe(true))

      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: admissionsKeys.lists() }),
      )

      const statsCalls = invalidateSpy.mock.calls.filter(([opts]) => {
        const key = (opts as { queryKey: readonly unknown[] }).queryKey
        return (
          Array.isArray(key) &&
          key[0] === "admissions" &&
          key[1] === "stats" &&
          key.length === 2
        )
      })
      expect(statsCalls.length).toBeGreaterThan(0)

      invalidateSpy.mockRestore()
    })
  })

  describe("useDeleteChoice — scope hẹp (KHÔNG flip status)", () => {
    it("invalidates only choices + detail, NOT lists/stats", async () => {
      server.use(
        http.delete(
          `${API_BASE_URL}/api/v2/admissions/:id/choices/:choiceId`,
          () =>
            HttpResponse.json({
              choice_id: CHOICE_ID,
              profile_id: PROFILE_ID,
            }),
        ),
      )

      const { queryClient, Wrapper } = createWrapperWithClient()
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries")

      const { result } = renderHook(() => useDeleteChoice(PROFILE_ID), {
        wrapper: Wrapper,
      })

      act(() => {
        result.current.mutate(CHOICE_ID)
      })

      await waitFor(() => expect(result.current.isSuccess).toBe(true))

      // Anchor: delete choice là CRUD ops trên child entity, KHÔNG flip
      // profile.status → list/counts/stats không cần refetch (avoid storm).
      const listCalls = invalidateSpy.mock.calls.filter(([opts]) => {
        const key = (opts as { queryKey: readonly unknown[] }).queryKey
        return Array.isArray(key) && key[1] === "list"
      })
      expect(listCalls.length).toBe(0)

      const statsCalls = invalidateSpy.mock.calls.filter(([opts]) => {
        const key = (opts as { queryKey: readonly unknown[] }).queryKey
        return Array.isArray(key) && key[1] === "stats"
      })
      expect(statsCalls.length).toBe(0)

      invalidateSpy.mockRestore()
    })
  })
})
