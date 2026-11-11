/**
 * Bước 5 — Đối chiếu bản ký (đặc tả 5.5): chỉ gọi khi BẤM; hiện SỐ DÒNG + TÊN trường đổi, không giá trị cũ / mới; lỗi máy
 * chủ hiện nguyên văn; không có quyền ghi nhận ⇒ không có nút "Tiếp: Ghi nhận".
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { server } from "@/test/mocks/server"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"
import type { CouncilSetDetail } from "@/lib/zod/council-documents"

import { CouncilCompareStep } from "./CouncilCompareStep"

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))

const API = "http://localhost:8000"
const BO = {
  id: 7, nguoi_tao_id: 1, tao_luc: "2026-11-05T01:00:00Z", moc_chup: "2026-11-05T00:59:00Z", unit_id: 2, trinh_do: "Cao đẳng",
  so_ho_so: 3, so_tep: 2, kich_thuoc_tong: 20, nam_hoc: 2026, tham_so_quyet_dinh: null, thong_tin_dung: {}, tep: [],
} as unknown as CouncilSetDetail

let goi = 0
function dung(tra: () => Response) {
  goi = 0
  server.use(http.get(`${API}${P}/sets/7/so-voi-hien-tai`, () => { goi++; return tra() }))
}
function ve(onTiep: (() => void) | null = () => undefined) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <CouncilCompareStep bo={BO} onQuayLai={() => undefined} onTiep={onTiep} />
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.spyOn(console, "error").mockImplementation(() => undefined))

describe("CouncilCompareStep", () => {
  it("KHÔNG tự gọi máy chủ khi mở bước; chỉ gọi khi bấm", async () => {
    dung(() => HttpResponse.json({ set_id: 7, so_dong: 3, dong_khac: [], khong_dung_lai_duoc: [], mat_ho_so: [] }))
    ve()
    await new Promise((r) => setTimeout(r, 30))
    expect(goi).toBe(0)
    fireEvent.click(screen.getByTestId("so-sanh"))
    expect(await screen.findByTestId("khong-doi")).toBeTruthy()
    expect(goi).toBe(1)
  })

  it("có dòng đổi ⇒ SỐ DÒNG + TÊN trường (không giá trị); thêm dòng không dựng lại được / mất hồ sơ", async () => {
    dung(() =>
      HttpResponse.json({
        set_id: 7, so_dong: 3,
        dong_khac: [{ stt: 14, truong: ["ho", "diem_in"] }],
        khong_dung_lai_duoc: [{ stt: 2, ma: ["thieu_nganh"] }],
        mat_ho_so: [3],
      }),
    )
    ve()
    fireEvent.click(screen.getByTestId("so-sanh"))
    const co = await screen.findByTestId("co-doi")
    expect(co.textContent).toContain("3 dòng đã đổi so với lúc dựng")
    expect(screen.getByTestId("dong-doi-14").textContent).toBe("Dòng 14 — đổi: Họ, diem_in") // khoá đã biết ⇒ nhãn; khoá lạ ⇒ in nguyên
    expect(screen.getByTestId("dong-khong-dung-lai-2").textContent).toContain("thieu_nganh")
    expect(screen.getByTestId("dong-mat-ho-so-3").textContent).toBe("Dòng 3 — hồ sơ không còn")
    expect(co.textContent).toContain("vẫn ghi nhận được") // giấy in theo bộ vẫn ghi nhận
    expect(co.textContent).toContain("dựng bộ mới và trình ký lại")
  })

  it("lỗi máy chủ ⇒ hiện nguyên văn; chưa có kết quả", async () => {
    dung(() => HttpResponse.json({ detail: "Bộ dựng trước khi có dòng bộ — không so được.", error_code: "DATA_VALIDATION_ERROR" }, { status: 400 }))
    ve()
    fireEvent.click(screen.getByTestId("so-sanh"))
    expect((await screen.findByTestId("so-sanh-loi")).textContent).toContain("Bộ dựng trước khi có dòng bộ")
    expect(screen.queryByTestId("khong-doi")).toBeNull()
    expect(screen.queryByTestId("co-doi")).toBeNull()
  })

  it("không có bước kế (không quyền ghi nhận) ⇒ ẩn nút Tiếp; có quyền ⇒ hiện", () => {
    const { unmount } = ve(null)
    expect(screen.queryByTestId("doi-chieu-tiep")).toBeNull()
    unmount()
    ve(() => undefined)
    expect(screen.getByTestId("doi-chieu-tiep")).toBeTruthy()
  })
})
