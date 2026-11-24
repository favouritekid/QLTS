/**
 * GĐ2-B F1 — M2 chi tiết lần xét + M7 huỷ, dựng qua ĐÚNG `[sessionId]/page.tsx` (máy chủ giả MSW theo hình HĐ4 §3.1, QueryClient
 * mang mặc định thật của ứng dụng).
 *
 * Khoá (thiết kế §3.3, §3.8, §6.2 F1; đính chính 2 §1):
 *  - id trên URL kiểm dạng ở trang (sai ⇒ 404 của Next);
 *  - đầu trang "Lần xét số N — năm Y — Đợt"; trạng thái lạ ⇒ chữ máy chủ; băng cảnh báo CHỈ theo cờ máy chủ;
 *  - thanh nút CHỈ theo `available_actions` (`[]` ⇒ không nút; giá trị lạ bỏ qua) — biến thể phá: vẽ nút theo `status === "draft"`
 *    ⇒ ca "trạng thái nháp mà máy chủ không cho huỷ" ĐỎ;
 *  - tải lại lỗi (429) ⇒ hiện LỖI, không vẽ dữ liệu cũ;
 *  - huỷ: lý do trắng / quá 1000 ký tự ⇒ khoá nút; gửi `version` của E3 + lý do đã cắt khoảng trắng; 409 STALE ⇒ GIỮ lý do, E3 tải
 *    lại, bấm lại gửi `version` MỚI; 409 NOT_DRAFT ⇒ đóng hộp + câu máy chủ; 503 đóng băng; 422; mất kết nối ⇒ "chưa rõ", E3 tải lại
 *    (đã huỷ thì hộp tự đóng vì máy chủ thôi trả `cancel`).
 * Dữ liệu giả.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react"
import { delay, http, HttpResponse } from "msw"
import { toast } from "sonner"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  CANCEL_DONE,
  CANCEL_REASON_INVALID,
  CANCEL_STALE,
  CANCELLED_FLOORS_NOTE,
  CONFIG_CHANGED_BANNER,
  FROZEN_MESSAGE,
  NO_DONE_RUN,
  RATE_LIMITED_MESSAGE,
  SESSION_NOT_FOUND_MESSAGE,
  WRITE_UNCERTAIN_MESSAGE,
  quotaTableDraftBanner,
} from "@/lib/review-sessions/messages"
import { server } from "@/test/mocks/server"
import { RS, runSummaryGia, sessionDaHuyGia, sessionGia } from "@/test/mocks/review-sessions-data"
import { renderApp } from "@/test/review-sessions-render"
import { resolveServerTree } from "@/test/server-component"

import ReviewSessionDetailPage from "../[sessionId]/page"

const { push, replace, notFound } = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND")
  }),
}))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/review-sessions/3",
  notFound,
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

afterEach(() => server.resetHandlers())

async function moChiTiet(id = "3") {
  return renderApp(await resolveServerTree(ReviewSessionDetailPage({ params: Promise.resolve({ sessionId: id }) })))
}

/** E3 giả: lần gọi thứ n trả `chuoi[n-1]` (hết chuỗi ⇒ phần tử cuối). Trả bộ đếm. */
function mayChuE3(chuoi: (() => Response | Promise<Response>)[]): { lan: number } {
  const dem = { lan: 0 }
  server.use(
    http.get(`${RS}/3`, () => {
      dem.lan += 1
      return chuoi[Math.min(dem.lan, chuoi.length) - 1]()
    }),
  )
  return dem
}

const json = (body: Record<string, unknown>, status = 200) => () => HttpResponse.json(body, { status })

describe("M2 — trang chi tiết: id trên URL", () => {
  it.each(["abc", "0", "__placeholder__", "1234567890", "-3"])("id %j ⇒ 404 của Next (không gọi máy chủ)", async (id) => {
    const dem = mayChuE3([json(sessionGia())])
    await expect(resolveServerTree(ReviewSessionDetailPage({ params: Promise.resolve({ sessionId: id }) }))).rejects.toThrow(
      "NEXT_NOT_FOUND",
    )
    expect(dem.lan).toBe(0)
  })
})

describe("M2 — đầu trang, băng cảnh báo", () => {
  it("đầu trang 'Lần xét số N — năm Y — Đợt' + trạng thái + bảng chỉ tiêu + người tạo; liên kết bảng chỉ tiêu ?year=", async () => {
    mayChuE3([json(sessionGia())])
    await moChiTiet()
    expect(await screen.findByTestId("lan-xet-tieu-de")).toHaveTextContent("Lần xét số 3 — năm 2026 — Đợt 2")
    expect(screen.getByTestId("lan-xet-trang-thai")).toHaveTextContent("Nháp")
    expect(screen.getByTestId("lan-xet-bang-chi-tieu")).toHaveTextContent("Bảng chỉ tiêu năm: Đã khoá (phiên bản 2)")
    expect(screen.getByTestId("lan-xet-lien-ket-bang-chi-tieu")).toHaveAttribute("href", "/quota-tables?year=2026")
    expect(screen.getByTestId("lan-xet-tao")).toHaveTextContent("Tạo bởi Người dùng #1")
    expect(screen.getByTestId("lan-xet-so-san")).toHaveTextContent("1")
    expect(screen.queryByTestId("bang-cau-hinh-doi")).toBeNull()
    expect(screen.queryByTestId("bang-chi-tieu-nhap")).toBeNull()
  })

  it("trạng thái lạ ⇒ chữ máy chủ", async () => {
    mayChuE3([json(sessionGia({ status: "trang_thai_moi", available_actions: [] }))])
    await moChiTiet()
    expect(await screen.findByTestId("lan-xet-trang-thai")).toHaveTextContent("trang_thai_moi")
  })

  it("băng 'Cấu hình đã đổi' khi máy chủ trả cờ; băng bảng chỉ tiêu nháp khi quota_table.status = draft", async () => {
    mayChuE3([
      json(
        sessionGia({
          latest_run: runSummaryGia({ config_changed_since_run: true }),
          quota_table: { status: "draft", version: 1, quota_fingerprint: "a".repeat(64) },
        }),
      ),
    ])
    await moChiTiet()
    expect(await screen.findByTestId("bang-cau-hinh-doi")).toHaveTextContent(CONFIG_CHANGED_BANNER)
    expect(screen.getByTestId("bang-chi-tieu-nhap")).toHaveTextContent(quotaTableDraftBanner(2026))
  })

  it("chưa có lượt xong ⇒ 'Chưa có lượt kiểm nào xong.'", async () => {
    mayChuE3([json(sessionGia({ latest_run: null, latest_done_run_id: null }))])
    await moChiTiet()
    expect(await screen.findByTestId("lan-xet-chua-luot-xong")).toHaveTextContent(NO_DONE_RUN)
  })

  it("đã huỷ ⇒ câu giải phóng sàn + người huỷ + lý do; KHÔNG nút nào", async () => {
    mayChuE3([json(sessionDaHuyGia())])
    await moChiTiet()
    expect(await screen.findByTestId("bang-da-huy")).toHaveTextContent(CANCELLED_FLOORS_NOTE)
    expect(screen.getByTestId("lan-xet-huy")).toHaveTextContent("Huỷ bởi Người dùng #1")
    expect(screen.getByTestId("lan-xet-huy")).toHaveTextContent("Lý do: <lý do>")
    expect(screen.queryByTestId("thanh-nut")).toBeNull()
  })
})

describe("M2 — thanh nút CHỈ theo available_actions", () => {
  it.each([
    { ten: "đủ ba", actions: ["edit_floors", "run_evaluate", "cancel"], nut: ["nut-edit_floors", "nut-run_evaluate", "nut-cancel"] },
    { ten: "rỗng ⇒ không nút", actions: [], nut: [] },
    { ten: "giá trị lạ bỏ qua", actions: ["cancel", "lock"], nut: ["nut-cancel"] },
    { ten: "nháp mà máy chủ không cho huỷ", actions: ["edit_floors"], nut: ["nut-edit_floors"] },
  ])("$ten", async ({ actions, nut }) => {
    mayChuE3([json(sessionGia({ status: "draft", available_actions: actions }))])
    await moChiTiet()
    await screen.findByTestId("lan-xet-tieu-de")
    const co = ["nut-edit_floors", "nut-run_evaluate", "nut-cancel"].filter((t) => screen.queryByTestId(t) !== null)
    expect(co).toEqual(nut)
    if (nut.length === 0) expect(screen.queryByTestId("thanh-nut")).toBeNull()
  })

  it("'Sửa điểm sàn' / 'Kiểm hồ sơ' hiện theo cờ nhưng chưa bấm được ở F1; 'Huỷ lần xét' bấm được", async () => {
    mayChuE3([json(sessionGia())])
    await moChiTiet()
    expect(await screen.findByTestId("nut-edit_floors")).toBeDisabled()
    expect(screen.getByTestId("nut-run_evaluate")).toBeDisabled()
    expect(screen.getByTestId("nut-cancel")).toBeEnabled()
  })

  it("E3 đang tải lại ⇒ khoá nút ghi (thao tác kế phải dùng version mới)", async () => {
    mayChuE3([
      json(sessionGia()),
      async () => {
        await delay("infinite")
        return HttpResponse.json(sessionGia())
      },
    ])
    await moChiTiet()
    expect(await screen.findByTestId("nut-cancel")).toBeEnabled()
    fireEvent.click(screen.getAllByTestId("lan-xet-tai-lai")[0])
    await waitFor(() => expect(screen.getByTestId("nut-cancel")).toBeDisabled())
    expect(screen.getByTestId("lan-xet-dang-tai-lai")).toBeInTheDocument()
  })
})

describe("M2 — lỗi tải", () => {
  it("404 ⇒ câu 'Không tìm thấy lần xét (hoặc bạn không có quyền xem).' + liên kết về danh sách", async () => {
    mayChuE3([json({ reason_code: "review_session_not_found", detail: "x", error_code: "RESOURCE_NOT_FOUND" }, 404)])
    await moChiTiet()
    expect(await screen.findByTestId("lan-xet-loi")).toHaveTextContent(SESSION_NOT_FOUND_MESSAGE)
    expect(screen.getByTestId("ve-danh-sach")).toHaveAttribute("href", "/review-sessions")
  })

  it("đính chính 2 §1: tải lại bị 429 sau khi đã có dữ liệu ⇒ hiện LỖI, KHÔNG vẽ đầu trang / nút cũ", async () => {
    // Biến thể phá: đọc `data` trước `isError` ⇒ đầu trang cũ còn ⇒ ĐỎ.
    mayChuE3([json(sessionGia()), json({ detail: "Rate limit exceeded" }, 429)])
    await moChiTiet()
    await screen.findByTestId("lan-xet-tieu-de")
    fireEvent.click(screen.getByTestId("lan-xet-tai-lai"))
    expect(await screen.findByTestId("lan-xet-loi")).toHaveTextContent(RATE_LIMITED_MESSAGE)
    expect(screen.queryByTestId("lan-xet-tieu-de")).toBeNull()
    expect(screen.queryByTestId("nut-cancel")).toBeNull()
  })
})

// ═══════════════════════════════════════ M7 — huỷ ═══════════════════════════════════════
function mayChuHuy(tra: () => Response): unknown[] {
  const than: unknown[] = []
  server.use(
    http.post(`${RS}/3/cancel`, async ({ request }) => {
      than.push(await request.json())
      return tra()
    }),
  )
  return than
}

async function moHopHuy() {
  fireEvent.click(await screen.findByTestId("nut-cancel"))
  return screen.findByTestId("hop-huy-lan-xet")
}

const goLyDo = (s: string) => fireEvent.change(screen.getByTestId("huy-ly-do"), { target: { value: s } })

describe("M7 — huỷ lần xét", () => {
  it("lý do trắng ⇒ khoá nút; có chữ ⇒ mở; quá 1000 ký tự ⇒ khoá; đúng 1000 ⇒ mở", async () => {
    mayChuE3([json(sessionGia())])
    await moChiTiet()
    await moHopHuy()
    const nut = screen.getByTestId("huy-xac-nhan")
    expect(nut).toBeDisabled()
    goLyDo("   \n  ")
    expect(nut).toBeDisabled()
    goLyDo("lý do")
    expect(nut).toBeEnabled()
    goLyDo("ạ".repeat(1001))
    expect(nut).toBeDisabled()
    goLyDo(`  ${"ạ".repeat(1000)}  `)
    expect(nut).toBeEnabled()
  })

  it("thành công ⇒ gửi version của E3 + lý do đã cắt khoảng trắng; đóng hộp; E3 tải lại; báo đã huỷ", async () => {
    const dem = mayChuE3([json(sessionGia()), json(sessionDaHuyGia())])
    const than = mayChuHuy(json(sessionDaHuyGia()))
    await moChiTiet()
    await moHopHuy()
    goLyDo("  lý do huỷ  ")
    fireEvent.click(screen.getByTestId("huy-xac-nhan"))
    await waitFor(() => expect(screen.queryByTestId("hop-huy-lan-xet")).toBeNull())
    expect(than).toEqual([{ version: 2, reason: "lý do huỷ" }])
    expect(vi.mocked(toast.success)).toHaveBeenCalledWith(CANCEL_DONE)
    await waitFor(() => expect(dem.lan).toBe(2))
    expect(await screen.findByTestId("lan-xet-trang-thai")).toHaveTextContent("Đã huỷ")
  })

  it("409 REVIEW_SESSION_STALE ⇒ GIỮ lý do, câu riêng, E3 tải lại; bấm lại gửi version MỚI", async () => {
    // Biến thể phá: làm mới chỉ ở onSuccess ⇒ E3 không tải lại ⇒ lần bấm hai vẫn gửi version 2 ⇒ ĐỎ.
    const dem = mayChuE3([json(sessionGia({ version: 2 })), json(sessionGia({ version: 5 }))])
    let lan = 0
    const than = mayChuHuy(() => {
      lan += 1
      return lan === 1
        ? HttpResponse.json(
            { reason_code: "review_session_stale", current_version: 5, detail: "x", error_code: "REVIEW_SESSION_STALE" },
            { status: 409 },
          )
        : HttpResponse.json(sessionDaHuyGia({ version: 6 }))
    })
    await moChiTiet()
    await moHopHuy()
    goLyDo("lý do huỷ")
    fireEvent.click(screen.getByTestId("huy-xac-nhan"))
    expect(await screen.findByTestId("huy-loi")).toHaveTextContent(CANCEL_STALE)
    expect(screen.getByTestId("huy-ly-do")).toHaveValue("lý do huỷ")
    await waitFor(() => expect(dem.lan).toBe(2))
    await waitFor(() => expect(screen.getByTestId("huy-xac-nhan")).toBeEnabled())
    fireEvent.click(screen.getByTestId("huy-xac-nhan"))
    await waitFor(() => expect(than).toHaveLength(2))
    expect(than).toEqual([
      { version: 2, reason: "lý do huỷ" },
      { version: 5, reason: "lý do huỷ" },
    ])
  })

  it("409 REVIEW_SESSION_NOT_DRAFT ⇒ đóng hộp, báo câu máy chủ, E3 tải lại", async () => {
    const dem = mayChuE3([json(sessionGia()), json(sessionDaHuyGia())])
    mayChuHuy(
      json(
        {
          reason_code: "review_session_not_draft",
          status: "cancelled",
          detail: "Lần xét không còn ở trạng thái nháp — không sửa điểm sàn, không chạy kiểm hồ sơ và không huỷ được nữa.",
          error_code: "REVIEW_SESSION_NOT_DRAFT",
        },
        409,
      ),
    )
    await moChiTiet()
    await moHopHuy()
    goLyDo("lý do")
    fireEvent.click(screen.getByTestId("huy-xac-nhan"))
    await waitFor(() => expect(screen.queryByTestId("hop-huy-lan-xet")).toBeNull())
    expect(vi.mocked(toast.error)).toHaveBeenCalledWith(
      "Lần xét không còn ở trạng thái nháp — không sửa điểm sàn, không chạy kiểm hồ sơ và không huỷ được nữa.",
    )
    await waitFor(() => expect(dem.lan).toBe(2))
  })

  it("503 đóng băng ⇒ câu đóng băng, GIỮ lý do, hộp còn mở", async () => {
    mayChuE3([json(sessionGia())])
    mayChuHuy(json({ detail: "Admission frozen", code: "ADMISSION_FROZEN", frozen_prefix: "/api/admission-config" }, 503))
    await moChiTiet()
    await moHopHuy()
    goLyDo("lý do")
    fireEvent.click(screen.getByTestId("huy-xac-nhan"))
    expect(await screen.findByTestId("huy-loi")).toHaveTextContent(FROZEN_MESSAGE)
    expect(screen.getByTestId("huy-ly-do")).toHaveValue("lý do")
  })

  it("422 ⇒ 'Lý do không được trống / quá 1000 ký tự'", async () => {
    mayChuE3([json(sessionGia())])
    mayChuHuy(
      json({ detail: "Request validation failed", error_code: "VALIDATION_ERROR", errors: [{ loc: ["body", "reason"], msg: "x" }] }, 422),
    )
    await moChiTiet()
    await moHopHuy()
    goLyDo("lý do")
    fireEvent.click(screen.getByTestId("huy-xac-nhan"))
    expect(await screen.findByTestId("huy-loi")).toHaveTextContent(CANCEL_REASON_INVALID)
  })

  it("mất kết nối, E3 tải lại vẫn nháp ⇒ 'chưa rõ đã ghi', hộp còn mở, E3 đã tải lại", async () => {
    const dem = mayChuE3([json(sessionGia())])
    mayChuHuy(() => HttpResponse.error())
    await moChiTiet()
    await moHopHuy()
    goLyDo("lý do")
    fireEvent.click(screen.getByTestId("huy-xac-nhan"))
    expect(await screen.findByTestId("huy-loi")).toHaveTextContent(WRITE_UNCERTAIN_MESSAGE)
    await waitFor(() => expect(dem.lan).toBe(2))
    expect(screen.getByTestId("hop-huy-lan-xet")).toBeInTheDocument()
  })

  it("mất kết nối, E3 tải lại cho thấy ĐÃ huỷ ⇒ máy chủ thôi trả `cancel` ⇒ hộp tự đóng, trạng thái 'Đã huỷ'", async () => {
    mayChuE3([json(sessionGia()), json(sessionDaHuyGia())])
    mayChuHuy(() => HttpResponse.error())
    await moChiTiet()
    await moHopHuy()
    goLyDo("lý do")
    fireEvent.click(screen.getByTestId("huy-xac-nhan"))
    await waitFor(() => expect(screen.queryByTestId("hop-huy-lan-xet")).toBeNull())
    expect(screen.getByTestId("lan-xet-trang-thai")).toHaveTextContent("Đã huỷ")
  })
})
