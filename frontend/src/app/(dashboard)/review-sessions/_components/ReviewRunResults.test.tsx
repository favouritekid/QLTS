/**
 * GĐ2-B F4 — M5 thẻ "Kết quả": bốn tab + bộ lọc + phân trang (E9) + ngăn chi tiết M6, dựng qua ĐÚNG `[sessionId]/runs/[runId]/page.tsx`
 * với `searchParams` (máy chủ giả MSW theo HĐ4 §3.5 / §9; QueryClient mang mặc định thật của ứng dụng).
 *
 * Khoá (thiết kế §3.6, §3.7, §6.2 F4; đính chính 1 §1; đính chính 2 §1):
 *  - số trên tab = `tab_counts` của CẢ lượt (không đổi theo bộ lọc); đổi tab ⇒ về trang 1 + gửi `tab` (giữ bộ lọc);
 *  - bộ lọc lấy từ `quota_view` (ứng viên > 0) / `reason_counts` / `flag_counts`, kết hợp VÀ; trạng thái nằm trên URL;
 *  - thứ tự dòng do máy chủ; `null` ⇒ "—" (không thành 0); mã lạ ⇒ câu chung có mã; tab lạ ⇒ chữ máy chủ + cột chung;
 *  - `document_gaps = null` + `document_config_*` ⇒ câu riêng; `per_choice` giữ thứ tự máy chủ; `full_name = null` ⇒ "Hồ sơ không còn.";
 *  - tải lỗi (kể cả 429) ⇒ hiện lỗi, không vẽ dòng cũ; lật trang giữ trang cũ làm chỗ tạm, đổi tab thì không;
 *  - lượt chưa xong ⇒ không gọi E9; E9 409 REVIEW_RUN_NOT_DONE ⇒ câu máy chủ;
 *  - đính chính 1 §1: mở lại M5 sau khi cấu hình đổi ⇒ không vẽ bản cũ, băng "Cấu hình đã đổi" hiện.
 * Dữ liệu giả.
 */
import { QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { delay, http, HttpResponse } from "msw"
import { describe, expect, it, vi } from "vitest"

import { RATE_LIMITED_MESSAGE, RUN_CONFIG_CHANGED_BANNER } from "@/lib/review-sessions/messages"
import { DOCUMENT_CONFIG_UNKNOWN, PROFILE_GONE, profileStatusLabel } from "@/lib/review-sessions/row-labels"
import type { PageSearchParams } from "@/lib/utils/search-params"
import { server } from "@/test/mocks/server"
import {
  E9_BANG_DIEM_CHO_CUOI,
  E9_MAT_CAU_HINH_GIAY,
  E9_THIEU_GIAY,
  RS,
  runGia,
  sessionGia,
} from "@/test/mocks/review-sessions-data"
import { renderApp } from "@/test/review-sessions-render"
import { resolveServerTree } from "@/test/server-component"

import ReviewRunDetailPage from "../[sessionId]/runs/[runId]/page"

const { push, replace, notFound } = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND")
  }),
}))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/review-sessions/3/runs/11",
  notFound,
}))

type Obj = Record<string, unknown>
const choLau = (ms = 100) => new Promise((r) => setTimeout(r, ms))
const M5 = "/review-sessions/3/runs/11"

const cay = (sp: PageSearchParams = {}) =>
  resolveServerTree(
    ReviewRunDetailPage({ params: Promise.resolve({ sessionId: "3", runId: "11" }), searchParams: Promise.resolve(sp) }),
  )

async function moKetQua(sp: PageSearchParams = {}) {
  return renderApp(await cay(sp))
}

/** E3 + E8 giả (E8 mặc định: lượt 11 đã xong). */
function nen(e8: Obj = runGia()) {
  server.use(
    http.get(`${RS}/3`, () => HttpResponse.json(sessionGia())),
    http.get(`${RS}/3/runs/11`, () => HttpResponse.json(e8)),
  )
}

/** E9 giả: ghi chuỗi tham số từng lần gọi; trả `tra(tham số, lần)`. */
function mayChuE9(tra: (sp: URLSearchParams, lan: number) => Response | Promise<Response>): string[] {
  const goi: string[] = []
  server.use(
    http.get(`${RS}/3/runs/11/rows`, ({ request }) => {
      const u = new URL(request.url)
      goi.push(u.search)
      return tra(u.searchParams, goi.length)
    }),
  )
  return goi
}

const TAB_COUNTS = { auto: 120, needs_decision: 8, not_passed: 31, ineligible: 57 }
const trangDong = (items: Obj[], over: Obj = {}): Obj => ({
  items,
  total: items.length,
  page: 1,
  page_size: 50,
  total_pages: items.length ? 1 : 0,
  tab_counts: TAB_COUNTS,
  ...over,
})

/** Dòng tab "Đạt — máy đề xuất" (dựng từ ví dụ HĐ4 §9). */
const DONG_AUTO: Obj = {
  ...E9_BANG_DIEM_CHO_CUOI,
  profile_id: 1005,
  tab: "auto",
  reason_codes: [],
  decision_hints: [],
  within_seats: true,
  flags: [],
}
const DONG_AUTO_2: Obj = {
  ...DONG_AUTO,
  profile_id: 1002,
  review_total: "17.25",
  rank_in_major: 41,
  ethnic_priority_state: null,
  flags: ["major_inactive"],
}

const cell = (id: number, col: string) => screen.getByTestId(`dong-${id}-${col}`)
const optionTexts = (testId: string) =>
  within(screen.getByTestId(testId))
    .getAllByRole("option")
    .map((o) => o.textContent)

describe("F4 — bốn tab: số máy chủ, tab mặc định, cột, thứ tự", () => {
  it("mặc định: tab đầu tiên máy chủ trả (auto) được gửi; cột tab 'Đạt'; thứ tự dòng NGUYÊN máy chủ; ô đúng nhãn; có 'Tải lúc HH:MM'", async () => {
    nen()
    const goi = mayChuE9(() => HttpResponse.json(trangDong([DONG_AUTO, DONG_AUTO_2])))
    await moKetQua()
    expect(await screen.findByTestId("dong-1005")).toBeInTheDocument()
    expect(goi).toEqual(["?tab=auto&page=1&page_size=50"])
    expect(screen.getByTestId("kq-tab-auto")).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByTestId("kq-tab-auto")).toHaveTextContent("Đạt — máy đề xuất 120")
    const thuTu = within(screen.getByTestId("kq-bang"))
      .getAllByTestId(/^dong-\d+$/)
      .map((r) => r.getAttribute("data-testid"))
    expect(thuTu).toEqual(["dong-1005", "dong-1002"])
    const lk = within(cell(1005, "name")).getByRole("link")
    expect(lk).toHaveAttribute("href", "/admissions/1005")
    expect(lk).toHaveAttribute("target", "_blank")
    expect(cell(1005, "unit")).toHaveTextContent("Đơn vị #4")
    expect(cell(1005, "choice")).toHaveTextContent("NV1 · <mã> — <tên ngành> · <loại hình>")
    expect(cell(1005, "total")).toHaveTextContent(/^18,50$/)
    expect(cell(1005, "floor")).toHaveTextContent(/^15,00$/)
    expect(cell(1005, "rank")).toHaveTextContent(/^40$/)
    expect(cell(1005, "ethnic")).toHaveTextContent("Đủ minh chứng")
    expect(cell(1005, "flags")).toHaveTextContent(/^—$/)
    expect(cell(1002, "ethnic")).toHaveTextContent(/^—$/)
    expect(cell(1002, "flags")).toHaveTextContent("Ngành đang ngừng")
    expect(screen.queryByTestId("dong-1005-reasons")).toBeNull()
    expect(screen.getByTestId("luot-tai-luc").textContent).toMatch(/^Tải lúc \d{2}:\d{2}$/)
  })

  it("số trên tab = tab_counts của CẢ lượt — KHÔNG đổi theo bộ lọc; có 'Đang lọc: {total} dòng'", async () => {
    // Biến thể phá: số trên tab lấy `total` của trang đang lọc ⇒ "… 3" ⇒ ĐỎ.
    nen()
    mayChuE9(() => HttpResponse.json(trangDong([DONG_AUTO], { total: 3 })))
    await moKetQua({ "ly-do": "tie_at_last_seat" })
    expect(await screen.findByTestId("kq-dang-loc")).toHaveTextContent("Đang lọc: 3 dòng")
    expect(screen.getByTestId("kq-tab-auto")).toHaveTextContent("Đạt — máy đề xuất 120")
    expect(screen.getByTestId("kq-tab-ineligible")).toHaveTextContent("Chưa đủ điều kiện 57")
  })

  it("đổi tab ⇒ URL về trang 1, GIỮ bộ lọc; trang dựng lại với URL mới ⇒ E9 gửi tab mới + page 1", async () => {
    nen()
    const goi = mayChuE9(() => HttpResponse.json(trangDong([DONG_AUTO], { page: 3, total: 120, total_pages: 3 })))
    const { queryClient, rerender } = await moKetQua({ trang: "3", "ly-do": "tie_at_last_seat" })
    await screen.findByTestId("dong-1005")
    fireEvent.click(screen.getByTestId("kq-tab-needs_decision"))
    expect(replace).toHaveBeenLastCalledWith(`${M5}?tab=needs_decision&ly-do=tie_at_last_seat`)
    rerender(
      <QueryClientProvider client={queryClient}>{await cay({ tab: "needs_decision", "ly-do": "tie_at_last_seat" })}</QueryClientProvider>,
    )
    await waitFor(() => expect(goi).toHaveLength(2))
    expect(goi[1]).toBe("?tab=needs_decision&reason_code=tie_at_last_seat&page=1&page_size=50")
  })

  it("tab 'Cần Ban thư ký quyết': thêm cột lý do / trong số chỗ / gợi ý (nhãn C2)", async () => {
    nen()
    mayChuE9(() => HttpResponse.json(trangDong([E9_BANG_DIEM_CHO_CUOI])))
    await moKetQua({ tab: "needs_decision" })
    await screen.findByTestId("dong-1001")
    expect(cell(1001, "reasons")).toHaveTextContent("Bằng điểm ở chỗ cuối")
    expect(cell(1001, "seats")).toHaveTextContent("Ngoài số chỗ")
    expect(cell(1001, "hints")).toHaveTextContent("Trúng vượt chỉ tiêu ngành; Xét nguyện vọng kế")
  })

  it("tab 'Chưa đủ điều kiện': trạng thái hồ sơ + giấy; document_gaps null + document_config_* ⇒ câu riêng; không cột NV", async () => {
    // Biến thể phá: bỏ nhánh `document_config_*` ⇒ "—" ⇒ ĐỎ.
    nen()
    mayChuE9(() => HttpResponse.json(trangDong([E9_MAT_CAU_HINH_GIAY, E9_THIEU_GIAY])))
    await moKetQua({ tab: "ineligible" })
    await screen.findByTestId("dong-1003")
    expect(cell(1003, "docs")).toHaveTextContent(DOCUMENT_CONFIG_UNKNOWN)
    expect(cell(1004, "docs")).toHaveTextContent("Thiếu: hoc_ba_thpt · Chưa duyệt: giay_khai_sinh")
    expect(cell(1003, "profileStatus")).toHaveTextContent(profileStatusLabel("submitted"))
    expect(cell(1004, "profileStatus")).toHaveTextContent(profileStatusLabel("resubmitted"))
    expect(cell(1003, "reasons")).toHaveTextContent("Hồ sơ thiếu cấu hình giấy tờ bắt buộc")
    expect(screen.queryByTestId("dong-1003-choice")).toBeNull()
  })

  it("tab 'Chưa đạt': tóm tắt từng NV theo ĐÚNG thứ tự máy chủ", async () => {
    nen()
    const dong: Obj = {
      ...E9_BANG_DIEM_CHO_CUOI,
      profile_id: 1006,
      tab: "not_passed",
      reason_codes: ["all_choices_failed"],
      decision_hints: [],
      considered_choice: null,
      within_seats: null,
      rank_in_major: null,
      per_choice: [
        { choice_id: 6002, display_order: 2, offering_academic_info_id: 57, status: "below_floor", reason_codes: [], review_total: "14.00", floor_score: "15.00" },
        { choice_id: 6001, display_order: 1, offering_academic_info_id: 41, status: "failed_gate", reason_codes: ["BELOW_MIN_SCORE"], review_total: null, floor_score: null },
      ],
    }
    mayChuE9(() => HttpResponse.json(trangDong([dong])))
    await moKetQua({ tab: "not_passed" })
    await screen.findByTestId("dong-1006")
    expect(cell(1006, "perChoice")).toHaveTextContent("NV2: Dưới điểm sàn · NV1: Không đạt điều kiện nguyện vọng")
    expect(cell(1006, "reasons")).toHaveTextContent("Không nguyện vọng nào đạt")
  })

  it("full_name null ⇒ 'Hồ sơ không còn.' (không liên kết); mọi ô null ⇒ '—' (không thành 0)", async () => {
    nen()
    const dong: Obj = {
      ...DONG_AUTO,
      profile_id: 1007,
      full_name: null,
      review_total: null,
      floor_score: null,
      rank_in_major: null,
      considered_choice: null,
      unit_id: null,
    }
    mayChuE9(() => HttpResponse.json(trangDong([dong])))
    await moKetQua()
    await screen.findByTestId("dong-1007")
    expect(cell(1007, "name")).toHaveTextContent(PROFILE_GONE)
    expect(within(cell(1007, "name")).queryByRole("link")).toBeNull()
    for (const col of ["total", "floor", "rank", "choice", "unit"]) expect(cell(1007, col)).toHaveTextContent(/^—$/)
  })

  it("tab lạ (GĐ2-C) ⇒ chữ máy chủ + cột chung; lý do / cờ lạ ⇒ câu chung CÓ mã", async () => {
    const g = runGia() as { summary: Obj }
    nen(runGia({ summary: { ...g.summary, tab_counts: { auto: 1, excluded: 2 } } }))
    const dong: Obj = { ...DONG_AUTO, profile_id: 1008, tab: "excluded", reason_codes: ["thieu_ma_ho_so"], flags: ["co_moi"] }
    mayChuE9(() => HttpResponse.json(trangDong([dong], { tab_counts: { auto: 1, excluded: 2 } })))
    await moKetQua({ tab: "excluded" })
    await screen.findByTestId("dong-1008")
    expect(screen.getByTestId("kq-tab-excluded")).toHaveTextContent("excluded 2")
    expect(screen.getByTestId("kq-tab-excluded")).toHaveAttribute("aria-pressed", "true")
    expect(cell(1008, "reasons")).toHaveTextContent("Lý do khác (mã: thieu_ma_ho_so)")
    expect(cell(1008, "flags")).toHaveTextContent("Cờ khác (mã: co_moi)")
    expect(screen.queryByTestId("dong-1008-choice")).toBeNull()
  })
})

describe("F4 — bộ lọc, URL, phân trang", () => {
  it("URL ⇒ đúng tham số E9 (VÀ) + ô lọc hiện đúng giá trị", async () => {
    nen()
    const goi = mayChuE9(() => HttpResponse.json(trangDong([E9_MAT_CAU_HINH_GIAY], { page: 2, total: 51, total_pages: 2 })))
    await moKetQua({ tab: "ineligible", nganh: "41", "ly-do": "document_config_missing", co: "quota_closed", trang: "2", "co-trang": "100" })
    await screen.findByTestId("dong-1003")
    expect(goi).toEqual([
      "?tab=ineligible&offering_academic_info_id=41&reason_code=document_config_missing&flag=quota_closed&page=2&page_size=100",
    ])
    expect(screen.getByTestId("kq-loc-nganh")).toHaveValue("41")
    expect(screen.getByTestId("kq-loc-ly-do")).toHaveValue("document_config_missing")
    expect(screen.getByTestId("kq-loc-co")).toHaveValue("quota_closed")
    expect(screen.getByTestId("kq-co-trang")).toHaveValue("100")
  })

  it("lựa chọn lọc lấy từ quota_view (ứng viên > 0) / reason_counts / flag_counts kèm số; đổi lọc ⇒ URL về trang 1", async () => {
    // Biến thể phá: danh sách ngành không lọc `candidates > 0` ⇒ có thêm ngành 42 ⇒ ĐỎ.
    const g = runGia() as { summary: Obj; quota_view: { majors: Obj[]; groups: Obj[] } }
    const m41 = g.quota_view.majors[0]
    nen(
      runGia({
        summary: { ...g.summary, reason_counts: { tie_at_last_seat: 3, document_config_missing: 2 }, flag_counts: { quota_closed: 1 } },
        quota_view: {
          ...g.quota_view,
          majors: [m41, { ...m41, offering_academic_info_id: 42, major_code: "<mã 2>", candidates: 0, auto: 0, needs_decision: 0 }],
        },
      }),
    )
    mayChuE9(() => HttpResponse.json(trangDong([DONG_AUTO], { page: 2, total: 60, total_pages: 2 })))
    await moKetQua({ trang: "2" })
    await screen.findByTestId("dong-1005")
    expect(optionTexts("kq-loc-nganh")).toEqual(["Tất cả", "<mã> — <tên ngành> · <loại hình>"])
    expect(optionTexts("kq-loc-ly-do")).toEqual([
      "Tất cả",
      "Bằng điểm ở chỗ cuối (3)",
      "Hồ sơ thiếu cấu hình giấy tờ bắt buộc (2)",
    ])
    expect(optionTexts("kq-loc-co")).toEqual(["Tất cả", "Có nguyện vọng vào ngành đã đóng tuyển (1)"])
    fireEvent.change(screen.getByTestId("kq-loc-ly-do"), { target: { value: "document_config_missing" } })
    expect(replace).toHaveBeenLastCalledWith(`${M5}?tab=auto&ly-do=document_config_missing`)
    fireEvent.change(screen.getByTestId("kq-loc-nganh"), { target: { value: "41" } })
    expect(replace).toHaveBeenLastCalledWith(`${M5}?tab=auto&nganh=41`)
  })

  it("phân trang: 'Trang 1 / 2'; 'Trang sau' ⇒ URL trang 2; 'Trang trước' khoá ở trang 1", async () => {
    nen()
    mayChuE9(() => HttpResponse.json(trangDong([DONG_AUTO], { total: 60, total_pages: 2 })))
    await moKetQua()
    expect(await screen.findByTestId("kq-trang-hien-tai")).toHaveTextContent("Trang 1 / 2")
    expect(screen.getByTestId("kq-trang-truoc")).toBeDisabled()
    fireEvent.click(screen.getByTestId("kq-trang-sau"))
    expect(replace).toHaveBeenLastCalledWith(`${M5}?tab=auto&trang=2`)
  })

  it("trang vượt cuối (máy chủ trả items: []) ⇒ quay về trang cuối", async () => {
    nen()
    mayChuE9(() => HttpResponse.json(trangDong([], { page: 5, total: 60, total_pages: 2 })))
    await moKetQua({ trang: "5" })
    await waitFor(() => expect(replace).toHaveBeenCalledWith(`${M5}?tab=auto&trang=2`))
  })

  it("lật trang khi trang mới đang tải ⇒ giữ dòng trang cũ + 'Đang tải trang…'; đổi tab khi đang tải ⇒ KHÔNG vẽ dòng tab cũ", async () => {
    nen()
    mayChuE9(async (sp) => {
      if (sp.get("page") !== "1" || sp.get("tab") !== "auto") await delay("infinite")
      return HttpResponse.json(trangDong([DONG_AUTO], { total: 60, total_pages: 2 }))
    })
    const { queryClient, rerender } = await moKetQua()
    await screen.findByTestId("dong-1005")
    rerender(<QueryClientProvider client={queryClient}>{await cay({ trang: "2" })}</QueryClientProvider>)
    expect(await screen.findByTestId("kq-dang-tai-trang")).toBeInTheDocument()
    expect(screen.getByTestId("dong-1005")).toBeInTheDocument()
    rerender(<QueryClientProvider client={queryClient}>{await cay({ tab: "ineligible" })}</QueryClientProvider>)
    expect(await screen.findByTestId("kq-dang-tai")).toBeInTheDocument()
    expect(screen.queryByTestId("dong-1005")).toBeNull()
  })
})

describe("F4 — lỗi / lượt chưa xong / bản cũ", () => {
  it("đính chính 2 §1: E9 lật trang bị 429 ⇒ hiện LỖI, KHÔNG vẽ dòng cũ", async () => {
    // Biến thể phá: đọc `data` trước `isError` ⇒ dòng chỗ tạm của trang 1 còn ⇒ ĐỎ.
    nen()
    mayChuE9((sp) =>
      sp.get("page") === "1"
        ? HttpResponse.json(trangDong([DONG_AUTO], { total: 60, total_pages: 2 }))
        : HttpResponse.json({ detail: "Rate limit exceeded" }, { status: 429 }),
    )
    const { queryClient, rerender } = await moKetQua()
    await screen.findByTestId("dong-1005")
    rerender(<QueryClientProvider client={queryClient}>{await cay({ trang: "2" })}</QueryClientProvider>)
    expect(await screen.findByTestId("kq-loi")).toHaveTextContent(RATE_LIMITED_MESSAGE)
    expect(screen.queryByTestId("dong-1005")).toBeNull()
  })

  it("E9 409 REVIEW_RUN_NOT_DONE ⇒ câu máy chủ", async () => {
    const cau = "Lượt kiểm hồ sơ chưa xong — chưa có dòng kết quả để xem."
    nen()
    mayChuE9(() =>
      HttpResponse.json(
        { reason_code: "review_run_not_done", status: "running", detail: cau, error_code: "REVIEW_RUN_NOT_DONE" },
        { status: 409 },
      ),
    )
    await moKetQua()
    expect(await screen.findByTestId("kq-loi")).toHaveTextContent(cau)
  })

  it("lượt chưa xong (running) ⇒ KHÔNG gọi E9", async () => {
    nen(runGia({ status: "running", finished_at: null, duration_ms: null, summary: null, quota_view: null }))
    const goi = mayChuE9(() => HttpResponse.json(trangDong([DONG_AUTO])))
    await moKetQua()
    await screen.findByTestId("bang-luot-chua-xong")
    await choLau()
    expect(goi).toEqual([])
    expect(screen.queryByTestId("kq")).toBeNull()
  })

  it("đính chính 1 §1: rời M5, cấu hình đổi KHÔNG qua thao tác ghi, mở lại M5 khi E8 còn đang tải ⇒ KHÔNG vẽ bản cũ; xong ⇒ băng 'Cấu hình đã đổi'", async () => {
    // Biến thể phá: E8 giữ bản đệm (gcTime / staleTime > 0) ⇒ đầu trang cũ (không băng) hiện ngay khi mở lại ⇒ ĐỎ.
    let moCong: () => void = () => undefined
    const cong = new Promise<void>((r) => {
      moCong = () => r()
    })
    let lan = 0
    server.use(
      http.get(`${RS}/3`, () => HttpResponse.json(sessionGia())),
      http.get(`${RS}/3/runs/11`, async () => {
        lan += 1
        if (lan === 1) return HttpResponse.json(runGia({ config_changed_since_run: false }))
        await cong
        return HttpResponse.json(runGia({ config_changed_since_run: true }))
      }),
    )
    mayChuE9(() => HttpResponse.json(trangDong([DONG_AUTO])))
    const { queryClient, unmount } = await moKetQua()
    await screen.findByTestId("luot-tieu-de")
    expect(screen.queryByTestId("bang-luot-cau-hinh-doi")).toBeNull()
    unmount()
    await choLau(20)
    render(<QueryClientProvider client={queryClient}>{await cay()}</QueryClientProvider>)
    await waitFor(() => expect(lan).toBe(2))
    expect(screen.queryByTestId("luot-tieu-de")).toBeNull()
    expect(screen.getByTestId("luot-dang-tai")).toBeInTheDocument()
    moCong()
    expect(await screen.findByTestId("bang-luot-cau-hinh-doi")).toHaveTextContent(RUN_CONFIG_CHANGED_BANNER)
  })
})

describe("F4 — ngăn chi tiết một em (M6)", () => {
  it("bấm 'Xem' ⇒ ngăn hiện ĐÚNG dòng E9: điểm thành phần NGUYÊN chuỗi (không cộng), NV theo thứ tự máy chủ, nhãn ngành ghép theo id", async () => {
    nen()
    mayChuE9(() => HttpResponse.json(trangDong([E9_BANG_DIEM_CHO_CUOI])))
    await moKetQua({ tab: "needs_decision" })
    fireEvent.click(await screen.findByTestId("dong-1001-xem"))
    const ngan = await screen.findByTestId("ngan-chi-tiet")
    expect(within(ngan).getByTestId("ngan-ten")).toHaveTextContent("<họ tên>")
    expect(within(ngan).getByTestId("ngan-dau")).toHaveTextContent(profileStatusLabel("submitted"))
    expect(within(ngan).getByTestId("ngan-dau")).toHaveTextContent("Đơn vị #4")
    expect(within(ngan).getByTestId("ngan-dau")).toHaveTextContent("Cần Ban thư ký quyết")
    expect(within(ngan).getByTestId("ngan-mo-ho-so")).toHaveAttribute("href", "/admissions/1001")
    expect(within(ngan).getByTestId("ngan-tong")).toHaveTextContent(/^18,50$/)
    expect(within(ngan).getByTestId("ngan-tong-mon")).toHaveTextContent(/^17,00$/)
    expect(within(ngan).getByTestId("ngan-kv")).toHaveTextContent(/^0,50$/)
    expect(within(ngan).getByTestId("ngan-doi-tuong")).toHaveTextContent(/^1,00$/)
    expect(within(ngan).getByTestId("ngan-uu-tien")).toHaveTextContent(/^1,50$/)
    expect(within(ngan).getByTestId("ngan-san")).toHaveTextContent(/^15,00$/)
    expect(within(ngan).getByTestId("ngan-hang")).toHaveTextContent(/^40$/)
    expect(within(ngan).getByTestId("ngan-so-cho")).toHaveTextContent("Ngoài số chỗ")
    expect(within(ngan).getByTestId("ngan-dan-toc")).toHaveTextContent("Đủ minh chứng")
    expect(within(ngan).getByTestId("ngan-ly-do")).toHaveTextContent("Bằng điểm ở chỗ cuối")
    expect(within(ngan).getByTestId("ngan-goi-y")).toHaveTextContent("Trúng vượt chỉ tiêu ngành; Xét nguyện vọng kế")
    const nv = within(within(ngan).getByTestId("ngan-nv"))
      .getAllByTestId(/^ngan-nv-\d+$/)
      .map((r) => r.getAttribute("data-testid"))
    expect(nv).toEqual(["ngan-nv-5001", "ngan-nv-5002"])
    expect(within(ngan).getByTestId("ngan-nv-5001")).toHaveTextContent("<mã> — <tên ngành>")
    expect(within(ngan).getByTestId("ngan-nv-5001")).toHaveTextContent("Đạt sàn (nguyện vọng được xếp)")
    expect(within(ngan).getByTestId("ngan-nv-5002")).toHaveTextContent("Học vụ #57")
    expect(within(ngan).getByTestId("ngan-nv-5002")).toHaveTextContent("Không xét (đã xếp nguyện vọng trước)")
    expect(within(ngan).getByTestId("ngan-nam-truoc")).toHaveTextContent("(không có)")
  })

  it("ngăn: document_gaps null + document_config_missing ⇒ câu riêng; null ⇒ '—'; năm trước (A13) hiện năm + căn cứ", async () => {
    nen()
    const dong: Obj = {
      ...E9_MAT_CAU_HINH_GIAY,
      prior_year_findings: [{ year: 2025, basis: "admission_decision", status: null }],
    }
    mayChuE9(() => HttpResponse.json(trangDong([dong])))
    await moKetQua({ tab: "ineligible" })
    fireEvent.click(await screen.findByTestId("dong-1003-xem"))
    const ngan = await screen.findByTestId("ngan-chi-tiet")
    expect(within(ngan).getByTestId("ngan-giay")).toHaveTextContent(DOCUMENT_CONFIG_UNKNOWN)
    expect(within(ngan).getByTestId("ngan-tong")).toHaveTextContent(/^—$/)
    expect(within(ngan).getByTestId("ngan-dan-toc")).toHaveTextContent(/^—$/)
    expect(within(ngan).getByTestId("ngan-nam-truoc")).toHaveTextContent("Năm 2025 — Có Quyết định trúng tuyển — trạng thái —")
  })
})
