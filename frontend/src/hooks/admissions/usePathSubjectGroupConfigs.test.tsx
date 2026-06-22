/**
 * usePathSubjectGroupConfigs — invalidation contract (#7).
 *
 * Every mutation (config + item CRUD) must invalidate the FULL set so the
 * multi-NV dropdown (["path-sg-configs", pathId], AddChoiceDialog), the admin
 * list, the path detail, .all, and ["quota-matrix"] all refetch. The first two
 * + quota-matrix are raw literals NOT under admissionPathKeys.all, so they're
 * easy to drop — pin all six hooks here.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

import {
  useAddPathSubjectGroupItem,
  useCreatePathSubjectGroupConfig,
  useDeletePathSubjectGroupConfig,
  useDeletePathSubjectGroupItem,
  useUpdatePathSubjectGroupConfig,
  useUpdatePathSubjectGroupItem,
} from "./usePathSubjectGroupConfigs"

vi.mock("@/lib/api/admission-paths", () => ({
  createPathSubjectGroupConfig: vi.fn().mockResolvedValue({ id: 1 }),
  updatePathSubjectGroupConfig: vi.fn().mockResolvedValue({ id: 1 }),
  deletePathSubjectGroupConfig: vi.fn().mockResolvedValue(undefined),
  addPathSubjectGroupItem: vi.fn().mockResolvedValue({ id: 9 }),
  updatePathSubjectGroupItem: vi.fn().mockResolvedValue({ id: 9 }),
  deletePathSubjectGroupItem: vi.fn().mockResolvedValue(undefined),
  getPathSubjectGroupConfigsAdmin: vi.fn(),
}))

function makeHarness() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  const spy = vi.spyOn(qc, "invalidateQueries")
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  return { spy, wrapper }
}

const PATH = 42

// The full invalidation set every mutation must emit.
const FULL_SET = [
  ["path-sg-configs-admin", PATH],
  ["path-sg-configs", PATH], // AddChoiceDialog officer GET (raw literal)
  ["admission-paths", "detail", PATH],
  ["admission-paths"],
  ["quota-matrix"], // raw literal, not under .all
].map((k) => JSON.stringify(k))

function assertFullSet(spy: ReturnType<typeof vi.spyOn>) {
  const got = spy.mock.calls.map((c: unknown[]) =>
    JSON.stringify((c[0] as { queryKey: unknown }).queryKey),
  )
  for (const key of FULL_SET) expect(got).toContain(key)
}

describe("usePathSubjectGroupConfigs — every mutation invalidates the full set", () => {
  it("create config", async () => {
    const { spy, wrapper } = makeHarness()
    const { result } = renderHook(() => useCreatePathSubjectGroupConfig(), { wrapper })
    await result.current.mutateAsync({ pathId: PATH, data: { subject_group_id: 7 } })
    assertFullSet(spy)
  })

  it("update config", async () => {
    const { spy, wrapper } = makeHarness()
    const { result } = renderHook(() => useUpdatePathSubjectGroupConfig(), { wrapper })
    await result.current.mutateAsync({ pathId: PATH, configId: 5, data: { min_score: 5 } })
    assertFullSet(spy)
  })

  it("delete config", async () => {
    const { spy, wrapper } = makeHarness()
    const { result } = renderHook(() => useDeletePathSubjectGroupConfig(), { wrapper })
    await result.current.mutateAsync({ pathId: PATH, configId: 5 })
    assertFullSet(spy)
  })

  it("add item", async () => {
    const { spy, wrapper } = makeHarness()
    const { result } = renderHook(() => useAddPathSubjectGroupItem(), { wrapper })
    await result.current.mutateAsync({
      pathId: PATH,
      configId: 5,
      data: { subject_group_subject_id: 11 },
    })
    assertFullSet(spy)
  })

  it("update item", async () => {
    const { spy, wrapper } = makeHarness()
    const { result } = renderHook(() => useUpdatePathSubjectGroupItem(), { wrapper })
    await result.current.mutateAsync({
      pathId: PATH,
      configId: 5,
      itemId: 9,
      data: { is_principal: true },
    })
    assertFullSet(spy)
  })

  it("delete item", async () => {
    const { spy, wrapper } = makeHarness()
    const { result } = renderHook(() => useDeletePathSubjectGroupItem(), { wrapper })
    await result.current.mutateAsync({ pathId: PATH, configId: 5, itemId: 9 })
    assertFullSet(spy)
  })
})
