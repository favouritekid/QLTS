/**
 * Văn bản Hội đồng — hooks (lượt F).
 *
 * QueryClient của test mang ĐÚNG mặc định của app (`src/app/providers.tsx`:
 * staleTime / gcTime 5 phút) — để phép đo "dữ liệu mã không nằm lại trong cache"
 * đo chính `gcTime: 0` + gỡ-khi-unmount của hook, không phải mặc định của test.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, renderHook, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"

import { server } from "@/test/mocks/server"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"
import {
  NO_COUNCIL_PERMISSIONS,
  councilDocumentKeys,
  useCouncilDocumentPermissions,
  useCouncilSetInputCodes,
  useCreateCouncilSet,
} from "./useCouncilDocuments"

const API = "http://localhost:8000"
const maGia = (n: number) => "099" + "999" + String(n).padStart(6, "0")
const MA = [maGia(12), maGia(4), maGia(8)]

/** Mặc định của `src/app/providers.tsx` (retry tắt cho test — mọi ca ở đây là 2xx / 4xx). */
function qcNhuApp() {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 5 * 60 * 1000, gcTime: 5 * 60 * 1000, refetchOnWindowFocus: false, retry: false },
      mutations: { retry: false },
    },
  })
}

function boc(qc: QueryClient) {
  const W = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  W.displayName = "Boc"
  return W
}

/** Mọi dữ liệu + biến số còn trong QueryCache / MutationCache, dạng chuỗi. */
function cacheThanhChuoi(qc: QueryClient): string {
  const q = qc.getQueryCache().getAll().map((x) => ({ k: x.queryKey, d: x.state.data }))
  const m = qc.getMutationCache().getAll().map((x) => ({ v: x.state.variables, d: x.state.data }))
  return JSON.stringify({ q, m })
}

let consoleSpies: ReturnType<typeof vi.spyOn>[] = []
beforeEach(() => {
  consoleSpies = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
    vi.spyOn(console, m).mockImplementation(() => undefined),
  )
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => {
  vi.useRealTimers()
})

function khongMaNgoaiBoNho() {
  const ngoai = JSON.stringify({
    c: consoleSpies.map((s) => s.mock.calls),
    l: { ...localStorage },
    s: { ...sessionStorage },
    u: window.location.href,
  })
  for (const m of MA) expect(ngoai.includes(m), "mã giả lọt ra console / storage / URL").toBe(false)
}

describe("useCouncilDocumentPermissions — view model cờ", () => {
  it("200 ⇒ ready, đúng cờ máy chủ", async () => {
    const co = { ...NO_COUNCIL_PERMISSIONS, xem_danh_sach_bo: true, tai_tep: true }
    server.use(http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: co })))
    const { result } = renderHook(() => useCouncilDocumentPermissions(), { wrapper: boc(qcNhuApp()) })
    await waitFor(() => expect(result.current.state).toBe("ready"))
    expect(result.current.permissions).toEqual(co)
  })

  it("403 ⇒ forbidden, MỌI cờ tắt", async () => {
    server.use(
      http.get(`${API}${P}/quyen`, () =>
        HttpResponse.json({ detail: "x", error_code: "PERMISSION_DENIED" }, { status: 403 }),
      ),
    )
    const { result } = renderHook(() => useCouncilDocumentPermissions(), { wrapper: boc(qcNhuApp()) })
    await waitFor(() => expect(result.current.state).toBe("forbidden"))
    expect(result.current.permissions).toEqual(NO_COUNCIL_PERMISSIONS)
  })

  it("500 / phản hồi sai dạng ⇒ error, MỌI cờ tắt (fail-closed)", async () => {
    server.use(http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: { xem_mau: true } })))
    const { result } = renderHook(() => useCouncilDocumentPermissions(), { wrapper: boc(qcNhuApp()) })
    await waitFor(() => expect(result.current.state).toBe("error"))
    expect(result.current.permissions).toEqual(NO_COUNCIL_PERMISSIONS)
  })
})

describe("danh sách mã đầu vào — không nằm lại trong bộ nhớ trang", () => {
  it("query `gcTime: 0` ⇒ rời khỏi cache ngay sau unmount (dù mặc định app 5 phút)", async () => {
    server.use(
      http.get(`${API}${P}/sets/5/ma-ho-so`, () =>
        HttpResponse.json({ set_id: 5, so_ho_so: 3, ma_ho_so: MA }),
      ),
    )
    const qc = qcNhuApp()
    const { result, unmount } = renderHook(() => useCouncilSetInputCodes(5, true), { wrapper: boc(qc) })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.ma_ho_so).toEqual(MA)
    const q = qc.getQueryCache().find({ queryKey: councilDocumentKeys.inputCodes(5) })
    expect(q?.options.gcTime).toBe(0)
    unmount()
    await waitFor(() =>
      expect(qc.getQueryCache().find({ queryKey: councilDocumentKeys.inputCodes(5) })).toBeUndefined(),
    )
    for (const m of MA) expect(cacheThanhChuoi(qc).includes(m)).toBe(false)
    khongMaNgoaiBoNho()
  })
})

describe("dựng bộ — biến số mutation không nằm lại trong MutationCache", () => {
  it("thành công rồi unmount ⇒ không còn mã trong cache", async () => {
    server.use(
      http.post(`${API}${P}/sets`, () =>
        HttpResponse.json(
          {
            id: 11, nguoi_tao_id: 1, tao_luc: "2026-11-05T01:00:00Z", moc_chup: "2026-11-05T01:00:00Z",
            unit_id: null, trinh_do: "Cao đẳng", so_ho_so: 3, so_tep: 1, kich_thuoc_tong: 1, nam_hoc: 2026,
            tham_so_quyet_dinh: null, thong_tin_dung: {}, tep: [],
          },
          { status: 201 },
        ),
      ),
      http.get(`${API}${P}/sets`, () => HttpResponse.json([])),
    )
    const qc = qcNhuApp()
    const { result, unmount } = renderHook(() => useCreateCouncilSet(), { wrapper: boc(qc) })
    act(() => {
      result.current.mutate({ ma_ho_so: MA, academic_year: 2026 })
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    unmount()
    await waitFor(() => expect(qc.getMutationCache().getAll()).toHaveLength(0))
    for (const m of MA) expect(cacheThanhChuoi(qc).includes(m)).toBe(false)
    khongMaNgoaiBoNho()
  })

  it("lỗi 400 rồi unmount ⇒ không còn mã trong cache, không console", async () => {
    server.use(
      http.post(`${API}${P}/sets`, () =>
        HttpResponse.json({ detail: "Dòng 2: mã hồ sơ rỗng.", error_code: "DATA_VALIDATION_ERROR" }, { status: 400 }),
      ),
    )
    const qc = qcNhuApp()
    const { result, unmount } = renderHook(() => useCreateCouncilSet(), { wrapper: boc(qc) })
    act(() => {
      result.current.mutate({ ma_ho_so: MA, academic_year: 2026 })
    })
    await waitFor(() => expect(result.current.isError).toBe(true))
    unmount()
    await waitFor(() => expect(qc.getMutationCache().getAll()).toHaveLength(0))
    for (const m of MA) expect(cacheThanhChuoi(qc).includes(m)).toBe(false)
    khongMaNgoaiBoNho()
  })
})
