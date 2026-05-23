/**
 * use-priority-evidence cache parity tests.
 *
 * PR #323 review P1-4 (memory `admission-review-followups-2026-05-22`) —
 * 4 hooks share `invalidateRelated()` which performs:
 *   1. setQueryData(admissionsKeys.detail(id)) — write fresh profile to cache
 *   2. invalidateQueries(admissionsKeys.detail(id)) — refetch
 *   3. invalidateQueries(predicate ["priority-kv-preview", id, ...]) — sibling
 *
 * Without these tests a refactor that drops one branch silently breaks
 * the cache parity contract per memory `react-query-mutation-cache-parity`.
 * Coverage previously existed only for choices (`useAdmissionChoices.test`).
 *
 * Real `QueryClient` (no `vi.fn()` tautology) + MSW intercept at fetch layer
 * (no mock of `priorityEvidenceApi`) per memory `vitest-url-mock-tautological`.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { renderHook, waitFor, act } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClientProvider } from "@tanstack/react-query"
import React from "react"

import { server } from "@/test/mocks/server"
import { createTestQueryClient } from "@/test/utils/test-utils"
import { admissionsKeys } from "@/hooks/admissions/useAdmissions"
import {
  useVerifyObjectEvidence,
  useRejectObjectEvidence,
  useUploadPriorityEvidence,
  useUntickPriorityEvidence,
} from "./use-priority-evidence"

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"

const PROFILE_ID = 42
const SUB_CODE = "04"

const SAMPLE_PROFILE_RESPONSE = {
  id: PROFILE_ID,
  status: "draft",
  version: 5,
  academic_year: 2026,
  permissions: {},
  available_actions: [],
  validation_errors: [],
  completion_percent: 80,
  eligibility_status: "eligible",
  priority_object_codes: ["04"],
  priority_resolution_snapshot: {},
  priority_audit_log: [],
} as const

function createWrapperWithClient() {
  const queryClient = createTestQueryClient()
  const Wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children)
  Wrapper.displayName = "TestQueryClientWrapper"
  return { queryClient, Wrapper }
}

/**
 * Assert the cache-parity contract that `invalidateRelated` is expected
 * to satisfy. Run AFTER `result.current.isSuccess === true`.
 *
 *   1. setQueryData(detailKey, freshProfile) called — fresh write into cache
 *   2. invalidateQueries(detailKey) called — triggers refetch
 *   3. invalidateQueries(predicate) called — and the predicate matches
 *      `["priority-kv-preview", PROFILE_ID, ...]` while rejecting unrelated
 *      keys (defensive against an over-broad predicate that nukes the cache)
 *
 * We spy on `setQueryData` rather than reading `getQueryData()` because the
 * test client uses `gcTime: 0`, which evicts the data immediately after
 * `invalidateQueries` triggers a refetch with no observer.
 */
function assertCacheParity(
  setDataSpy: ReturnType<typeof vi.spyOn>,
  invalidateSpy: ReturnType<typeof vi.spyOn>,
) {
  // 1. setQueryData(detailKey, freshProfile)
  expect(setDataSpy).toHaveBeenCalledWith(
    admissionsKeys.detail(PROFILE_ID),
    expect.objectContaining({ id: PROFILE_ID, version: 5 }),
  )

  // 2. invalidate detail key
  expect(invalidateSpy).toHaveBeenCalledWith(
    expect.objectContaining({
      queryKey: admissionsKeys.detail(PROFILE_ID),
    }),
  )

  // 3. sibling preview-priority-kv predicate must accept this profile's preview
  const predicateCall = invalidateSpy.mock.calls.find(([opts]) => {
    return typeof (opts as { predicate?: unknown })?.predicate === "function"
  })
  expect(predicateCall).toBeDefined()
  const predicate = (
    predicateCall![0] as { predicate: (q: { queryKey: unknown[] }) => boolean }
  ).predicate
  expect(
    predicate({ queryKey: ["priority-kv-preview", PROFILE_ID, "draft-input"] }),
  ).toBe(true)
  // Defensive: predicate must NOT match unrelated keys
  expect(
    predicate({ queryKey: ["priority-kv-preview", PROFILE_ID + 1] }),
  ).toBe(false)
  expect(predicate({ queryKey: ["admissions", "list"] })).toBe(false)
}

describe("use-priority-evidence — mutation cache parity (P1-4)", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe("useVerifyObjectEvidence", () => {
    it("setQueryData detail + invalidateQueries detail + sibling preview predicate", async () => {
      server.use(
        http.patch(
          `${API_BASE_URL}/api/v2/admissions/:id/priority-objects/:subCode/verify`,
          () => HttpResponse.json(SAMPLE_PROFILE_RESPONSE),
        ),
      )

      const { queryClient, Wrapper } = createWrapperWithClient()
      const setDataSpy = vi.spyOn(queryClient, "setQueryData")
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries")

      const { result } = renderHook(
        () => useVerifyObjectEvidence(PROFILE_ID, SUB_CODE),
        { wrapper: Wrapper },
      )

      act(() => {
        result.current.mutate({ version: 5 })
      })

      await waitFor(() => expect(result.current.isSuccess).toBe(true))

      assertCacheParity(setDataSpy, invalidateSpy)
      setDataSpy.mockRestore()
      invalidateSpy.mockRestore()
    })
  })

  describe("useRejectObjectEvidence", () => {
    it("setQueryData detail + invalidateQueries detail + sibling preview predicate", async () => {
      server.use(
        http.patch(
          `${API_BASE_URL}/api/v2/admissions/:id/priority-objects/:subCode/reject`,
          () => HttpResponse.json(SAMPLE_PROFILE_RESPONSE),
        ),
      )

      const { queryClient, Wrapper } = createWrapperWithClient()
      const setDataSpy = vi.spyOn(queryClient, "setQueryData")
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries")

      const { result } = renderHook(
        () => useRejectObjectEvidence(PROFILE_ID, SUB_CODE),
        { wrapper: Wrapper },
      )

      act(() => {
        result.current.mutate({
          version: 5,
          reason: "Minh chứng không hợp lệ — quá hạn",
        })
      })

      await waitFor(() => expect(result.current.isSuccess).toBe(true))

      assertCacheParity(setDataSpy, invalidateSpy)
      setDataSpy.mockRestore()
      invalidateSpy.mockRestore()
    })
  })

  describe("useUploadPriorityEvidence", () => {
    it("setQueryData detail + invalidateQueries detail + sibling preview predicate", async () => {
      server.use(
        http.post(
          `${API_BASE_URL}/api/v2/admissions/:id/priority-evidence/:subCode/upload`,
          () => HttpResponse.json(SAMPLE_PROFILE_RESPONSE),
        ),
      )

      const { queryClient, Wrapper } = createWrapperWithClient()
      const setDataSpy = vi.spyOn(queryClient, "setQueryData")
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries")

      const { result } = renderHook(
        () => useUploadPriorityEvidence(PROFILE_ID, SUB_CODE),
        { wrapper: Wrapper },
      )

      const file = new File(["fake-pdf-bytes"], "evidence.pdf", {
        type: "application/pdf",
      })

      act(() => {
        result.current.mutate({ file })
      })

      await waitFor(() => expect(result.current.isSuccess).toBe(true))

      assertCacheParity(setDataSpy, invalidateSpy)
      setDataSpy.mockRestore()
      invalidateSpy.mockRestore()
    })
  })

  describe("useUntickPriorityEvidence", () => {
    it("setQueryData detail + invalidateQueries detail + sibling preview predicate", async () => {
      server.use(
        http.delete(
          `${API_BASE_URL}/api/v2/admissions/:id/priority-evidence/:subCode`,
          () => HttpResponse.json(SAMPLE_PROFILE_RESPONSE),
        ),
      )

      const { queryClient, Wrapper } = createWrapperWithClient()
      const setDataSpy = vi.spyOn(queryClient, "setQueryData")
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries")

      const { result } = renderHook(
        () => useUntickPriorityEvidence(PROFILE_ID, SUB_CODE),
        { wrapper: Wrapper },
      )

      act(() => {
        result.current.mutate({ version: 5 })
      })

      await waitFor(() => expect(result.current.isSuccess).toBe(true))

      assertCacheParity(setDataSpy, invalidateSpy)
      setDataSpy.mockRestore()
      invalidateSpy.mockRestore()
    })
  })
})
