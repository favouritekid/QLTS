/**
 * GĐ2-B F0 — hook lần xét, khoá ở MỨC HOOK (máy chủ giả MSW, QueryClient mang ĐÚNG mặc định của ứng dụng):
 *
 * 1. ĐÍNH CHÍNH 2 §1 (DC-1, CHẶN): E2 / E3 / E7 / E8 mang `config_changed_since_run` (máy chủ tính LÚC GET).
 *    a. Cấu hình đổi KHÔNG qua thao tác ghi (vd sửa bảng chỉ tiêu ở thẻ khác) — rời màn rồi quay lại, lần gọi thứ hai TREO ⇒ hook
 *       KHÔNG trả bản cũ (`data` rỗng, đang tải). Biến thể phá: bỏ `gcTime: 0` (rơi về mặc định 5 phút của ứng dụng) ⇒ ĐỎ.
 *    b. Một thành phần mới gắn vào khi bản cũ còn sống ⇒ gọi lại máy chủ. Biến thể phá: `staleTime > 0` ⇒ ĐỎ.
 *    c. E8 (và E2) đổi khoá (lượt khác / trang khác) khi lần gọi mới treo ⇒ KHÔNG mượn dữ liệu khoá cũ. Biến thể phá: thêm
 *       `placeholderData: keepPreviousData` ⇒ ĐỎ.
 * 2. Làm mới sau MỌI thao tác ghi khi thao tác KẾT THÚC, BẤT KỂ kết quả (thành công / 409 / mất kết nối): E2 (+ E3, E7, E8 với thao
 *    tác trên một lần xét). Biến thể phá: chuyển làm mới từ `onSettled` sang `onSuccess` ⇒ các ca 409 / mất kết nối ĐỎ.
 * 3. E6 tự đặt thời gian chờ > 60 s (KT-11). Biến thể phá: bỏ `timeout` ⇒ ĐỎ.
 */
import type { ReactNode } from "react"
import { QueryClientProvider, type QueryClient, type UseQueryResult } from "@tanstack/react-query"
import { act, renderHook, waitFor } from "@testing-library/react"
import { delay, http, HttpResponse } from "msw"
import { afterEach, describe, expect, it, vi } from "vitest"

import { api } from "@/lib/api/client"
import { REVIEW_RUN_TIMEOUT_MS, createReviewRun } from "@/lib/api/review-sessions"
import { server } from "@/test/mocks/server"
import { appLikeQueryClient } from "@/test/review-sessions-render"
import {
  RS,
  listItemGia,
  pageGia,
  runGia,
  runSummaryGia,
  sessionGia,
} from "@/test/mocks/review-sessions-data"

import {
  useCancelReviewSession,
  useCreateReviewRun,
  useCreateReviewSession,
  usePutReviewFloors,
  useReviewRun,
  useReviewRuns,
  useReviewSession,
  useReviewSessionList,
} from "./use-review-sessions"

/** CÙNG mặc định QueryClient của ứng dụng — xem `src/test/review-sessions-render.tsx`. */
const appLikeClient = appLikeQueryClient

function wrapperFor(qc: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  }
}

const roiMan = () => new Promise((r) => setTimeout(r, 20))

afterEach(() => server.resetHandlers())

interface CaDc1 {
  ten: string
  url: string
  /** thân 200 với cờ `config_changed_since_run` */
  than: (changed: boolean) => Record<string, unknown>
  dung: () => UseQueryResult<unknown>
}

const CA_DC1: CaDc1[] = [
  {
    ten: "E2 danh sách lần xét",
    url: RS,
    than: (c) => pageGia([listItemGia({ latest_run: runSummaryGia({ config_changed_since_run: c }) })]),
    dung: () => useReviewSessionList({ page: 1, page_size: 20 }),
  },
  {
    ten: "E3 chi tiết lần xét",
    url: `${RS}/3`,
    than: (c) => sessionGia({ latest_run: runSummaryGia({ config_changed_since_run: c }) }),
    dung: () => useReviewSession(3),
  },
  {
    ten: "E7 danh sách lượt kiểm",
    url: `${RS}/3/runs`,
    than: (c) => pageGia([runSummaryGia({ config_changed_since_run: c })]),
    dung: () => useReviewRuns(3, { page: 1, page_size: 20 }),
  },
  {
    ten: "E8 chi tiết lượt kiểm",
    url: `${RS}/3/runs/11`,
    than: (c) => runGia({ config_changed_since_run: c }),
    dung: () => useReviewRun(3, 11),
  },
]

describe("DC-1 — query mang config_changed_since_run không giữ bản cũ", () => {
  it.each(CA_DC1)(
    "$ten: cấu hình đổi KHÔNG qua thao tác ghi, quay lại màn, lần gọi thứ hai treo ⇒ KHÔNG hiện bản cũ",
    async ({ url, than, dung }) => {
      let lan = 0
      server.use(
        http.get(url, async () => {
          lan += 1
          if (lan === 1) return HttpResponse.json(than(false))
          await delay("infinite")
          return HttpResponse.json(than(true))
        }),
      )
      const qc = appLikeClient()
      const dau = renderHook(dung, { wrapper: wrapperFor(qc) })
      await waitFor(() => expect(dau.result.current.isSuccess).toBe(true))
      dau.unmount()
      await roiMan()

      const lai = renderHook(dung, { wrapper: wrapperFor(qc) })
      await waitFor(() => expect(lan).toBe(2))
      expect(lai.result.current.data).toBeUndefined()
      expect(lai.result.current.isPending).toBe(true)
      lai.unmount()
    },
  )

  it.each(CA_DC1)("$ten: thành phần mới gắn vào khi bản cũ còn sống ⇒ gọi lại máy chủ (staleTime 0)", async ({ url, than, dung }) => {
    let lan = 0
    server.use(
      http.get(url, () => {
        lan += 1
        return HttpResponse.json(than(lan > 1))
      }),
    )
    const qc = appLikeClient()
    const dau = renderHook(dung, { wrapper: wrapperFor(qc) })
    await waitFor(() => expect(dau.result.current.isSuccess).toBe(true))
    expect(lan).toBe(1)
    const sau = renderHook(dung, { wrapper: wrapperFor(qc) })
    await waitFor(() => expect(lan).toBe(2))
    dau.unmount()
    sau.unmount()
  })

  it("E8 đổi lượt khi lần gọi mới treo ⇒ không mượn dữ liệu lượt cũ (không placeholderData)", async () => {
    server.use(
      http.get(`${RS}/3/runs/11`, () => HttpResponse.json(runGia({ id: 11 }))),
      http.get(`${RS}/3/runs/12`, async () => {
        await delay("infinite")
        return HttpResponse.json(runGia({ id: 12 }))
      }),
    )
    const qc = appLikeClient()
    const { result, rerender, unmount } = renderHook(({ runId }: { runId: number }) => useReviewRun(3, runId), {
      wrapper: wrapperFor(qc),
      initialProps: { runId: 11 },
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    rerender({ runId: 12 })
    await waitFor(() => expect(result.current.isPending).toBe(true))
    expect(result.current.data).toBeUndefined()
    unmount()
  })

  it("E2 lật trang khi trang mới treo ⇒ không hiện dòng của trang cũ", async () => {
    server.use(
      http.get(RS, async ({ request }) => {
        if (new URL(request.url).searchParams.get("page") === "2") await delay("infinite")
        return HttpResponse.json(pageGia([listItemGia()], { total: 21, total_pages: 2 }))
      }),
    )
    const qc = appLikeClient()
    const { result, rerender, unmount } = renderHook(({ page }: { page: number }) => useReviewSessionList({ page, page_size: 20 }), {
      wrapper: wrapperFor(qc),
      initialProps: { page: 1 },
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    rerender({ page: 2 })
    await waitFor(() => expect(result.current.isPending).toBe(true))
    expect(result.current.data).toBeUndefined()
    unmount()
  })
})

// ═══════════════════════ làm mới sau MỌI thao tác ghi, bất kể kết quả ═══════════════════════
interface ThaoTac {
  goi: () => void
  xong: boolean
}

interface CaGhi {
  ten: string
  method: "post" | "put"
  url: string
  /** thao tác trên MỘT lần xét (3) ⇒ làm mới cả E3 / E7 / E8; tạo lần xét ⇒ chỉ E2 */
  theoLanXet: boolean
  thanhCong: () => Response
  dung: () => ThaoTac
}

const CA_GHI: CaGhi[] = [
  {
    ten: "E1 tạo lần xét",
    method: "post",
    url: RS,
    theoLanXet: false,
    thanhCong: () => HttpResponse.json(sessionGia({ id: 9, version: 1, floors: [], latest_run: null, latest_done_run_id: null }), { status: 201 }),
    dung: () => {
      const m = useCreateReviewSession()
      return { goi: () => m.mutate({ academic_year: 2026, admission_round_id: 7 }), xong: m.isSuccess || m.isError }
    },
  },
  {
    ten: "E4 lưu điểm sàn",
    method: "put",
    url: `${RS}/3/floors`,
    theoLanXet: true,
    thanhCong: () => HttpResponse.json(sessionGia({ version: 3 })),
    dung: () => {
      const m = usePutReviewFloors(3)
      return { goi: () => m.mutate({ version: 2, floors: [] }), xong: m.isSuccess || m.isError }
    },
  },
  {
    ten: "E5 huỷ lần xét",
    method: "post",
    url: `${RS}/3/cancel`,
    theoLanXet: true,
    thanhCong: () => HttpResponse.json(sessionGia({ status: "cancelled", version: 3, floors: [], available_actions: [] })),
    dung: () => {
      const m = useCancelReviewSession(3)
      return { goi: () => m.mutate({ version: 2, reason: "lý do" }), xong: m.isSuccess || m.isError }
    },
  },
  {
    ten: "E6 kiểm hồ sơ",
    method: "post",
    url: `${RS}/3/runs`,
    theoLanXet: true,
    thanhCong: () => HttpResponse.json(runGia({ id: 12 }), { status: 202 }),
    dung: () => {
      const m = useCreateReviewRun(3)
      return { goi: () => m.mutate({ kind: "evaluate", session_version: 2 }), xong: m.isSuccess || m.isError }
    },
  },
]

const KET_QUA: [string, (ca: CaGhi) => Response][] = [
  ["thành công", (ca) => ca.thanhCong()],
  [
    "409 REVIEW_SESSION_STALE",
    () =>
      HttpResponse.json(
        { reason_code: "review_session_stale", current_version: 5, detail: "x", error_code: "REVIEW_SESSION_STALE" },
        { status: 409 },
      ),
  ],
  ["mất kết nối (chưa rõ đã ghi)", () => HttpResponse.error()],
]

const MA_TRAN = CA_GHI.flatMap((ca) => KET_QUA.map(([kq, tra]) => ({ ten: `${ca.ten} — ${kq}`, ca, tra })))

describe("làm mới E2 / E3 / E7 / E8 khi thao tác ghi KẾT THÚC, bất kể kết quả", () => {
  it.each(MA_TRAN)("$ten", async ({ ca, tra }) => {
    const dem = { e2: 0, e3: 0, e7: 0, e8: 0 }
    const ghi = ca.method === "put" ? http.put(ca.url, () => tra(ca)) : http.post(ca.url, () => tra(ca))
    server.use(
      ghi,
      http.get(RS, () => {
        dem.e2 += 1
        return HttpResponse.json(pageGia([listItemGia()]))
      }),
      http.get(`${RS}/3`, () => {
        dem.e3 += 1
        return HttpResponse.json(sessionGia())
      }),
      http.get(`${RS}/3/runs`, () => {
        dem.e7 += 1
        return HttpResponse.json(pageGia([runSummaryGia()]))
      }),
      http.get(`${RS}/3/runs/11`, () => {
        dem.e8 += 1
        return HttpResponse.json(runGia())
      }),
    )
    const qc = appLikeClient()
    const { result, unmount } = renderHook(
      () => ({
        e2: useReviewSessionList({ page: 1, page_size: 20 }),
        e3: useReviewSession(3),
        e7: useReviewRuns(3, { page: 1, page_size: 20 }),
        e8: useReviewRun(3, 11),
        tt: ca.dung(),
      }),
      { wrapper: wrapperFor(qc) },
    )
    await waitFor(() => {
      expect(result.current.e2.isSuccess && result.current.e3.isSuccess).toBe(true)
      expect(result.current.e7.isSuccess && result.current.e8.isSuccess).toBe(true)
    })
    expect(dem).toEqual({ e2: 1, e3: 1, e7: 1, e8: 1 })

    act(() => result.current.tt.goi())
    await waitFor(() => expect(result.current.tt.xong).toBe(true))
    await waitFor(() => expect(dem.e2).toBe(2))
    if (ca.theoLanXet) {
      await waitFor(() => expect({ e3: dem.e3, e7: dem.e7, e8: dem.e8 }).toEqual({ e3: 2, e7: 2, e8: 2 }))
    }
    unmount()
  })
})

describe("E6 — thời gian chờ riêng > 60 s (nginx cắt 60 s)", () => {
  it("createReviewRun gửi đúng thân + timeout riêng", async () => {
    const spy = vi.spyOn(api, "post").mockResolvedValue({ data: runGia({ id: 12 }) } as never)
    await createReviewRun(3, { kind: "evaluate", session_version: 2 })
    expect(spy).toHaveBeenCalledWith(
      "/api/admission-config/review-sessions/3/runs",
      { kind: "evaluate", session_version: 2 },
      { timeout: REVIEW_RUN_TIMEOUT_MS },
    )
    expect(REVIEW_RUN_TIMEOUT_MS).toBeGreaterThan(60_000)
  })
})
