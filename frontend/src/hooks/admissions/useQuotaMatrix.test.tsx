/**
 * Anchor test cho useUpdatePathQuota cache invalidation (Bug #2 fix).
 *
 * Verify mutation onSuccess invalidate cả admissionPathKeys.detail(pathId)
 * VÀ quotaMatrixKeys.all — drawer reopen sau save không read stale cache.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api/quota-matrix", () => ({
  updatePathQuota: vi.fn(async () => ({ ok: true })),
  getPathMatrixByMajor: vi.fn(),
  getQuotaMatrix: vi.fn(),
}))

import { useUpdatePathQuota, quotaMatrixKeys } from "./useQuotaMatrix"
import { admissionPathKeys } from "./useAdmissionPaths"

function makeWrapper(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

describe("useUpdatePathQuota", () => {
  it("ANCHOR (Bug #2 cache parity): invalidates admissionPathKeys.detail(pathId) on success", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries")

    const { result } = renderHook(() => useUpdatePathQuota(), {
      wrapper: makeWrapper(qc),
    })

    await result.current.mutateAsync({
      pathId: 106,
      data: { round_quota: 50, admit_quota: 30 },
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: admissionPathKeys.detail(106),
    })
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: quotaMatrixKeys.all,
    })
  })
})
