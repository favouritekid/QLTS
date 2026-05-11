/**
 * Stateful anchor tests cho useUpdatePathQuota cache invalidation (Bug #2).
 *
 * Memory `vitest-url-mock-tautological` lesson: `vi.spyOn(qc, "invalidateQueries")
 * .toHaveBeenCalledWith(...)` verify CALL không equal verify CACHE STATE.
 * Stateful pattern: pre-seed cache → run mutation → assert
 * `getQueryState(detail(pathId)).isInvalidated === true`.
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

import * as quotaMatrixApi from "@/lib/api/quota-matrix"

import { useUpdatePathQuota, quotaMatrixKeys } from "./useQuotaMatrix"
import { admissionPathKeys } from "./useAdmissionPaths"

function makeWrapper(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

describe("useUpdatePathQuota cache invalidation (stateful)", () => {
  it("ANCHOR (Bug #2 cache parity): cache detail(pathId) marked invalidated after mutation success", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    // Pre-seed cache với stale data (simulate drawer mở lần đầu cache populated)
    qc.setQueryData(admissionPathKeys.detail(106), {
      id: 106,
      round_quota: null,
      admit_quota: null,
    })
    const stateBefore = qc.getQueryState(admissionPathKeys.detail(106))
    expect(stateBefore?.isInvalidated).toBeFalsy()

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

    // Stateful assertion: cache detail(106) phải marked invalidated
    // → next consumer subscribe sẽ trigger refetch fresh data từ server
    const stateAfter = qc.getQueryState(admissionPathKeys.detail(106))
    expect(stateAfter?.isInvalidated).toBe(true)
  })

  it("ANCHOR (cache parity): quota-matrix counter cache cũng marked invalidated", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    // Pre-seed matrix counter cache
    qc.setQueryData(quotaMatrixKeys.byYear(2026), {
      academic_year: 2026,
      total_rows: 1,
      rounds: [],
      rows: [],
    })

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

    // quotaMatrixKeys.all invalidate → byYear(2026) thuộc all → marked invalid
    const stateAfter = qc.getQueryState(quotaMatrixKeys.byYear(2026))
    expect(stateAfter?.isInvalidated).toBe(true)
  })

  it("ANCHOR (error path): cache KHÔNG invalidated khi mutation reject", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    // Pre-seed cache
    qc.setQueryData(admissionPathKeys.detail(106), {
      id: 106,
      round_quota: 50,
      admit_quota: 30,
    })

    // Override mock để reject (BE Tier 1 violation simulate)
    vi.mocked(quotaMatrixApi.updatePathQuota).mockRejectedValueOnce(
      new Error("Tier 1 chain violated"),
    )

    const { result } = renderHook(() => useUpdatePathQuota(), {
      wrapper: makeWrapper(qc),
    })

    // mutateAsync reject — swallow để test continue
    await result.current
      .mutateAsync({
        pathId: 106,
        data: { round_quota: 50, admit_quota: 80 },
      })
      .catch(() => {
        /* expected reject */
      })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })

    // Mutation failed → onSuccess KHÔNG fire → cache KHÔNG invalidated
    const stateAfter = qc.getQueryState(admissionPathKeys.detail(106))
    expect(stateAfter?.isInvalidated).toBe(false)
  })
})
