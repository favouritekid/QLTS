/**
 * GĐ2-B F1 — M1 hộp "Tạo lần xét" (E1), mở từ ĐÚNG trang `/review-sessions?nam=2026` (máy chủ giả MSW).
 *
 * Khoá (thiết kế §3.2, §6.2 F1; đính chính §2 + đính chính 2 §3; owner G1):
 *  - đợt hiện kèm NHÃN tình trạng (đợt "Tạm dừng" / "Đã lưu trữ" vẫn chọn được — máy chủ là chốt, G1); thân E1 đúng hai trường;
 *    201 ⇒ sang chi tiết lần xét;
 *  - 409 `REVIEW_QUOTA_TABLE_MISSING` ⇒ câu máy chủ + liên kết `/quota-tables?year=<academic_year TRONG THÂN LỖI>` (không
 *    `/admin/quota-tables`) — biến thể phá: lấy năm của ô chọn thay vì thân lỗi, hoặc trỏ `/admin/quota-tables` ⇒ ĐỎ;
 *  - 400 `review_round_invalid` ⇒ câu máy chủ, TẢI LẠI danh sách đợt, giữ hộp;
 *  - 503 đóng băng ⇒ câu đóng băng; mất kết nối / 5xx ⇒ "Chưa rõ đã tạo hay chưa …" + E2 tải lại;
 *  - đợt không tải được (403) ⇒ câu "Chỉ Admin …".
 * Dữ liệu giả.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { afterEach, describe, expect, it, vi } from "vitest"

import { CREATE_UNCERTAIN, FORBIDDEN_MESSAGE, FROZEN_MESSAGE } from "@/lib/review-sessions/messages"
import { server } from "@/test/mocks/server"
import { API, RS, listItemGia, pageGia, roundGia, sessionGia } from "@/test/mocks/review-sessions-data"
import { renderApp } from "@/test/review-sessions-render"
import { resolveServerTree } from "@/test/server-component"

import ReviewSessionsPage from "../page"

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/review-sessions",
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

afterEach(() => server.resetHandlers())

const DOT_2026 = [
  roundGia({ id: 7, round_code: "D2", round_name: "Đợt 2", is_active: true }),
  roundGia({ id: 8, round_code: "D1", round_name: "Đợt 1", is_active: false }),
  roundGia({ id: 9, round_code: "D0", round_name: "Đợt 0", is_active: false, archived_at: "2026-03-01T00:00:00Z" }),
]

interface Dem {
  e2: number
  dot: Record<number, number>
  than: unknown[]
}

/** Máy chủ giả cho trang + hộp: E2, đợt theo năm, E1 trả `taoTra()`. */
function mayChu(taoTra: () => Response, dotTra?: (year: number) => Response): Dem {
  const dem: Dem = { e2: 0, dot: {}, than: [] }
  server.use(
    http.get(RS, () => {
      dem.e2 += 1
      return HttpResponse.json(pageGia([listItemGia()]))
    }),
    http.get(`${API}/api/v2/admin/years/:year/rounds`, ({ params }) => {
      const y = Number(params.year)
      dem.dot[y] = (dem.dot[y] ?? 0) + 1
      if (dotTra) return dotTra(y)
      return HttpResponse.json({ total: y === 2026 ? 3 : 0, items: y === 2026 ? DOT_2026 : [] })
    }),
    http.post(RS, async ({ request }) => {
      dem.than.push(await request.json())
      return taoTra()
    }),
  )
  return dem
}

async function moHop() {
  renderApp(await resolveServerTree(ReviewSessionsPage({ searchParams: Promise.resolve({ nam: "2026" }) })))
  await screen.findByTestId("ds-lan-xet")
  fireEvent.click(screen.getByTestId("nut-tao-lan-xet"))
  return screen.findByTestId("hop-tao-lan-xet")
}

async function chonDotVaTao(id: string) {
  const dot = await screen.findByTestId("tao-dot")
  fireEvent.change(dot, { target: { value: id } })
  await waitFor(() => expect(screen.getByTestId("tao-xac-nhan")).toBeEnabled())
  fireEvent.click(screen.getByTestId("tao-xac-nhan"))
}

describe("M1 — tạo lần xét (E1)", () => {
  it("đợt hiện kèm nhãn tình trạng; đợt Tạm dừng / Đã lưu trữ KHÔNG bị khoá (máy chủ là chốt — G1); 201 ⇒ sang chi tiết", async () => {
    const dem = mayChu(() =>
      HttpResponse.json(sessionGia({ id: 9, version: 1, floors: [], latest_run: null, latest_done_run_id: null }), { status: 201 }),
    )
    await moHop()
    const dot = await screen.findByTestId("tao-dot")
    const nhan = within(dot)
      .getAllByRole("option")
      .map((o) => o.textContent)
    expect(nhan).toEqual([
      "— Chọn đợt —",
      "Đợt 2 (D2) — Đang hoạt động",
      "Đợt 1 (D1) — Tạm dừng",
      "Đợt 0 (D0) — Đã lưu trữ",
    ])
    for (const o of within(dot).getAllByRole("option")) expect(o).not.toBeDisabled()
    expect(screen.getByTestId("tao-xac-nhan")).toBeDisabled()

    await chonDotVaTao("8")
    await waitFor(() => expect(push).toHaveBeenCalledWith("/review-sessions/9"))
    expect(dem.than).toEqual([{ academic_year: 2026, admission_round_id: 8 }])
  })

  it("409 REVIEW_QUOTA_TABLE_MISSING ⇒ câu máy chủ + liên kết /quota-tables?year=<năm TRONG THÂN LỖI>", async () => {
    // Năm trong thân lỗi (2027) cố ý KHÁC năm đang chọn (2026) — chỉ để chứng minh NGUỒN của năm trên liên kết.
    mayChu(() =>
      HttpResponse.json(
        {
          reason_code: "review_quota_table_missing",
          academic_year: 2027,
          detail: "Năm 2027 chưa có bảng chỉ tiêu — tạo bảng chỉ tiêu năm trước khi tạo lần xét.",
          error_code: "REVIEW_QUOTA_TABLE_MISSING",
        },
        { status: 409 },
      ),
    )
    await moHop()
    await chonDotVaTao("7")
    const loi = await screen.findByTestId("tao-loi")
    expect(loi).toHaveTextContent("Năm 2027 chưa có bảng chỉ tiêu — tạo bảng chỉ tiêu năm trước khi tạo lần xét.")
    const lienKet = within(loi).getByTestId("tao-lien-ket-bang-chi-tieu")
    expect(lienKet).toHaveAttribute("href", "/quota-tables?year=2027")
    expect(lienKet).toHaveTextContent("Mở Bảng chỉ tiêu năm 2027")
    expect(lienKet.getAttribute("href")).not.toContain("/admin/")
    expect(push).not.toHaveBeenCalled()
  })

  it("400 review_round_invalid ⇒ câu máy chủ, TẢI LẠI danh sách đợt, giữ hộp", async () => {
    // Đợt 7 vừa bị xoá / chuyển năm ở nơi khác sau khi hộp tải danh sách đợt.
    const dem = mayChu(() =>
      HttpResponse.json(
        {
          reason_code: "review_round_invalid",
          admission_round_id: 7,
          detail: "Đợt tuyển sinh không tồn tại hoặc không thuộc năm của lần xét.",
          error_code: "VALIDATION_ERROR",
        },
        { status: 400 },
      ),
    )
    await moHop()
    await chonDotVaTao("7")
    expect(await screen.findByTestId("tao-loi")).toHaveTextContent("Đợt tuyển sinh không tồn tại hoặc không thuộc năm của lần xét.")
    await waitFor(() => expect(dem.dot[2026]).toBe(2))
    expect(screen.getByTestId("hop-tao-lan-xet")).toBeInTheDocument()
  })

  it("rà F01-5 — 400 review_round_archived (đợt đã lưu trữ, S1) ⇒ câu máy chủ nguyên văn, không câu 'Có lỗi (mã: …)'; tải lại đợt, giữ hộp", async () => {
    const CAU_S1 =
      "Đợt tuyển sinh này đã lưu trữ — không tạo lần xét trên đợt đã lưu trữ. Khôi phục đợt hoặc chọn đợt khác rồi làm lại."
    const dem = mayChu(() =>
      HttpResponse.json(
        { reason_code: "review_round_archived", admission_round_id: 9, detail: CAU_S1, error_code: "VALIDATION_ERROR" },
        { status: 400 },
      ),
    )
    await moHop()
    await chonDotVaTao("9")
    const loi = await screen.findByTestId("tao-loi")
    expect(loi).toHaveTextContent(CAU_S1)
    expect(loi).not.toHaveTextContent("Có lỗi (mã:")
    await waitFor(() => expect(dem.dot[2026]).toBe(2))
    expect(screen.getByTestId("hop-tao-lan-xet")).toBeInTheDocument()
    expect(dem.than).toEqual([{ academic_year: 2026, admission_round_id: 9 }])
  })

  it("503 đóng băng ⇒ câu đóng băng", async () => {
    mayChu(() => HttpResponse.json({ detail: "frozen", code: "NGINX_ADMISSION_FROZEN" }, { status: 503 }))
    await moHop()
    await chonDotVaTao("7")
    expect(await screen.findByTestId("tao-loi")).toHaveTextContent(FROZEN_MESSAGE)
  })

  const CHUA_RO: [string, () => Response][] = [
    ["mất kết nối", () => HttpResponse.error()],
    ["500", () => HttpResponse.json({ detail: "x", error_code: "INTERNAL_ERROR" }, { status: 500 })],
    ["504", () => new HttpResponse("gateway timeout", { status: 504 })],
  ]

  it.each(CHUA_RO)("%s ⇒ 'Chưa rõ đã tạo hay chưa …' + danh sách lần xét được tải lại", async (_ten, tra) => {
    const dem = mayChu(tra)
    await moHop()
    expect(dem.e2).toBe(1)
    await chonDotVaTao("7")
    expect(await screen.findByTestId("tao-loi")).toHaveTextContent(CREATE_UNCERTAIN)
    await waitFor(() => expect(dem.e2).toBe(2))
  })

  it("đợt không tải được (403) ⇒ câu 'Chỉ Admin …', không có nút Tạo bấm được", async () => {
    mayChu(
      () => HttpResponse.json({}, { status: 201 }),
      () => HttpResponse.json({ detail: "Forbidden" }, { status: 403 }),
    )
    await moHop()
    expect(await screen.findByTestId("tao-dot-loi")).toHaveTextContent(FORBIDDEN_MESSAGE)
    expect(screen.getByTestId("tao-xac-nhan")).toBeDisabled()
  })

  it("đổi năm trong hộp ⇒ tải đợt của năm mới, bỏ đợt đã chọn", async () => {
    const dem = mayChu(() => HttpResponse.json({}, { status: 201 }))
    await moHop()
    fireEvent.change(await screen.findByTestId("tao-dot"), { target: { value: "7" } })
    await waitFor(() => expect(screen.getByTestId("tao-xac-nhan")).toBeEnabled())
    const namKhac = String(new Date().getFullYear() + 1)
    fireEvent.change(screen.getByTestId("tao-nam"), { target: { value: namKhac } })
    expect(await screen.findByTestId("tao-dot-rong")).toHaveTextContent(`Năm ${namKhac} chưa có đợt tuyển sinh nào.`)
    expect(dem.dot[Number(namKhac)]).toBe(1)
    expect(screen.getByTestId("tao-xac-nhan")).toBeDisabled()
  })
})
