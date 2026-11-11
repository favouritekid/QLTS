/**
 * Thẻ "Quyết định trúng tuyển" trên trang hồ sơ (đặc tả 5.8, 3.9). Ba dạng của bản mẫu + các nhánh phòng thủ:
 * DTO vắng / sai dạng ⇒ KHÔNG hiện thẻ (máy chủ chưa trả ⏳); chữ lấy từ DTO; lý do huỷ chỉ khi máy chủ trả.
 */
import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"

import { CouncilDecisionCard } from "./CouncilDecisionCard"

const VB = { id: 8, loai: "trung_tuyen", so_quyet_dinh: "90", ngay_ky: "2026-10-20", trang_thai: "hieu_luc", set_id: 8 }
const dto = (over: Record<string, unknown> = {}) => ({
  tinh_trang: "co_qd_hieu_luc", van_ban: VB, ly_do_huy_ghi_nhan: null, dau_appsheet: false, dau_appsheet_so_qd: null, ...over,
})

describe("CouncilDecisionCard", () => {
  it.each([["vắng", undefined], ["null", null], ["chuỗi", "x"], ["thiếu trường", { tinh_trang: "co_qd_hieu_luc" }], ["sai kiểu", { ...dto(), dau_appsheet: "co" }]])(
    "DTO %s ⇒ không hiện thẻ",
    (_t, v) => {
      const { container } = render(<CouncilDecisionCard value={v} />)
      expect(container.innerHTML).toBe("")
    },
  )

  it("dạng 1 — còn hiệu lực + đã đối chiếu sổ: số, ngày, bộ (liên kết), nhãn", () => {
    render(<CouncilDecisionCard value={dto()} />)
    expect(screen.getByTestId("qd-co-van-ban").textContent).toContain("Quyết định trúng tuyển số 90 ngày 20/10/2026")
    expect(screen.getByTestId("qd-nhan-trang-thai").textContent).toBe("Còn hiệu lực")
    expect(screen.getByTestId("qd-doi-chieu-so").textContent).toBe("Đã đối chiếu sổ Quyết định")
    expect(screen.getByTestId("qd-bo-link").getAttribute("href")).toBe("/admin/council-documents/8")
  })

  it("dạng 2 — chỉ dấu AppSheet: tách riêng 'chưa đối chiếu', nói rõ hồ sơ bị chặn khi vào bộ mới", () => {
    render(<CouncilDecisionCard value={dto({ tinh_trang: "chua_co_qd", van_ban: null, dau_appsheet: true, dau_appsheet_so_qd: "1234" })} />)
    expect(screen.getByTestId("qd-chua-co").textContent).toContain("Chưa có trong sổ Quyết định của phần mềm")
    const ap = screen.getByTestId("qd-dau-appsheet").textContent ?? ""
    expect(ap).toContain("Quyết định số 1234")
    expect(ap).toContain("Chỉ có dấu AppSheet — chưa đối chiếu")
    expect(ap).toContain("hồ sơ bị chặn khi đưa vào bộ mới")
    expect(screen.queryByTestId("qd-doi-chieu-so")).toBeNull() // không trông giống đã đối chiếu
  })

  it("dấu AppSheet nhưng không đọc được số ⇒ không bịa số", () => {
    render(<CouncilDecisionCard value={dto({ tinh_trang: "chua_co_qd", van_ban: null, dau_appsheet: true, dau_appsheet_so_qd: null })} />)
    expect(screen.getByTestId("qd-dau-appsheet").textContent).toContain("Dữ liệu nhập từ AppSheet ghi: Quyết định")
    expect(screen.getByTestId("qd-dau-appsheet").textContent).not.toMatch(/số \d/)
  })

  it("dạng 3 — đã huỷ ghi nhận: nhãn Đã huỷ ghi nhận; lý do CHỈ khi máy chủ trả (admin)", () => {
    const { rerender } = render(
      <CouncilDecisionCard value={dto({ tinh_trang: "da_cho_xet_lai", van_ban: { ...VB, trang_thai: "huy_ghi_nhan" }, ly_do_huy_ghi_nhan: "nhập sai số" })} />,
    )
    expect(screen.getByTestId("qd-nhan-trang-thai").textContent).toBe("Đã huỷ ghi nhận")
    expect(screen.getByTestId("qd-ly-do-huy").textContent).toBe("Lý do: nhập sai số")
    rerender(<CouncilDecisionCard value={dto({ van_ban: { ...VB, trang_thai: "huy_ghi_nhan" }, ly_do_huy_ghi_nhan: null })} />)
    expect(screen.queryByTestId("qd-ly-do-huy")).toBeNull() // người không phải admin: máy chủ không trả ⇒ không hiện
  })

  it("tình trạng / trạng thái LẠ ⇒ in nguyên (không suy)", () => {
    render(<CouncilDecisionCard value={dto({ tinh_trang: "tinh_trang_moi", van_ban: { ...VB, trang_thai: "trang_thai_moi" } })} />)
    expect(screen.getByTestId("qd-tinh-trang").textContent).toBe("tinh_trang_moi")
    expect(screen.getByTestId("qd-nhan-trang-thai").textContent).toBe("trang_thai_moi")
  })

  it("không có bộ (set_id null) ⇒ không liên kết", () => {
    render(<CouncilDecisionCard value={dto({ van_ban: { ...VB, set_id: null } })} />)
    expect(screen.queryByTestId("qd-bo-link")).toBeNull()
  })
})
