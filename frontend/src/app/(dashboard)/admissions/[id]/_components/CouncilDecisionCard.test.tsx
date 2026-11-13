/**
 * Thẻ "Quyết định trúng tuyển" trên trang hồ sơ (đặc tả 5.8, 3.9). Ba dạng của bản mẫu + các nhánh phòng thủ:
 * DTO vắng / sai dạng ⇒ KHÔNG hiện thẻ (máy chủ chưa trả ⏳); chữ lấy từ DTO; lý do huỷ chỉ khi máy chủ trả.
 *
 * F279 (Codex lần 18): cán bộ xem được hồ sơ nhưng KHÔNG có quyền xem chi tiết bộ thì không được thấy liên kết mở bộ (bấm ra
 * sẽ bị từ chối). Liên kết hiện theo CỜ `xem_chi_tiet_bo` của máy chủ (`GET /quyen`); 403 / lỗi / đang tải ⇒ mọi cờ tắt ⇒ chỉ
 * hiện mã bộ dạng chữ.
 */
import { afterEach, describe, expect, it } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { server } from "@/test/mocks/server"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"
import { NO_COUNCIL_PERMISSIONS, councilDocumentKeys } from "@/hooks/admin/useCouncilDocuments"
import type { CouncilDocumentPermissions } from "@/lib/zod/council-documents"

import { CouncilDecisionCard } from "./CouncilDecisionCard"

const API = "http://localhost:8000"
const TAT_CA = Object.fromEntries(Object.keys(NO_COUNCIL_PERMISSIONS).map((k) => [k, true])) as CouncilDocumentPermissions
const CHI_XEM_CHI_TIET: CouncilDocumentPermissions = { ...NO_COUNCIL_PERMISSIONS, xem_chi_tiet_bo: true }
const TAT_CA_TRU_CHI_TIET: CouncilDocumentPermissions = { ...TAT_CA, xem_chi_tiet_bo: false }

const VB = { id: 8, loai: "trung_tuyen", so_quyet_dinh: "90", ngay_ky: "2026-10-20", trang_thai: "hieu_luc", set_id: 8 }
const dto = (over: Record<string, unknown> = {}) => ({
  tinh_trang: "co_qd_hieu_luc", van_ban: VB, ly_do_huy_ghi_nhan: null, dau_appsheet: false, dau_appsheet_so_qd: null, ...over,
})

let quyenGoi = 0
let daMoQuyen = false
afterEach(() => {
  quyenGoi = 0
  daMoQuyen = false
})

/** `GET /quyen` giả; mặc định mọi cờ bật. */
function moQuyen(tra: () => Response | Promise<Response> = () => HttpResponse.json({ permissions: TAT_CA })) {
  daMoQuyen = true
  server.use(
    http.get(`${API}${P}/quyen`, async () => {
      quyenGoi++
      return tra()
    }),
  )
}

/**
 * `quyen` cho trước ⇒ nạp sẵn vào cache (quyền đã biết ngay từ lần vẽ đầu): dùng cho khẳng định "KHÔNG có liên kết", để chúng
 * không đúng một cách RỖNG vì quyền còn đang tải. Không cho ⇒ đọc qua MSW (mặc định mọi cờ bật).
 */
function ve(value: unknown, quyen?: CouncilDocumentPermissions) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (quyen) qc.setQueryData(councilDocumentKeys.permissions(), quyen)
  else if (!daMoQuyen) moQuyen()
  const r = render(
    <QueryClientProvider client={qc}>
      <CouncilDecisionCard value={value} />
    </QueryClientProvider>,
  )
  return { ...r, qc }
}

describe("CouncilDecisionCard", () => {
  it.each([["vắng", undefined], ["null", null], ["chuỗi", "x"], ["thiếu trường", { tinh_trang: "co_qd_hieu_luc" }], ["sai kiểu", { ...dto(), dau_appsheet: "co" }]])(
    "DTO %s ⇒ không hiện thẻ",
    (_t, v) => {
      const { container } = ve(v, TAT_CA)
      expect(container.innerHTML).toBe("")
    },
  )

  it("dạng 1 — còn hiệu lực + đã đối chiếu sổ: số, ngày, bộ (liên kết), nhãn", async () => {
    ve(dto())
    expect(screen.getByTestId("qd-co-van-ban").textContent).toContain("Quyết định trúng tuyển số 90 ngày 20/10/2026")
    expect(screen.getByTestId("qd-nhan-trang-thai").textContent).toBe("Còn hiệu lực")
    expect(screen.getByTestId("qd-doi-chieu-so").textContent).toBe("Đã đối chiếu sổ Quyết định")
    expect((await screen.findByTestId("qd-bo-link")).getAttribute("href")).toBe("/admin/council-documents/8")
  })

  it("dạng 2 — chỉ dấu AppSheet: tách riêng 'chưa đối chiếu', nói rõ hồ sơ bị chặn khi vào bộ mới", () => {
    ve(dto({ tinh_trang: "chua_co_qd", van_ban: null, dau_appsheet: true, dau_appsheet_so_qd: "1234" }), TAT_CA)
    expect(screen.getByTestId("qd-chua-co").textContent).toContain("Chưa có trong sổ Quyết định của phần mềm")
    const ap = screen.getByTestId("qd-dau-appsheet").textContent ?? ""
    expect(ap).toContain("Quyết định số 1234")
    expect(ap).toContain("Chỉ có dấu AppSheet — chưa đối chiếu")
    expect(ap).toContain("hồ sơ bị chặn khi đưa vào bộ mới")
    expect(screen.queryByTestId("qd-doi-chieu-so")).toBeNull() // không trông giống đã đối chiếu
  })

  it("dấu AppSheet nhưng không đọc được số ⇒ không bịa số", () => {
    ve(dto({ tinh_trang: "chua_co_qd", van_ban: null, dau_appsheet: true, dau_appsheet_so_qd: null }), TAT_CA)
    expect(screen.getByTestId("qd-dau-appsheet").textContent).toContain("Dữ liệu nhập từ AppSheet ghi: Quyết định")
    expect(screen.getByTestId("qd-dau-appsheet").textContent).not.toMatch(/số \d/)
  })

  it("dạng 3 — đã huỷ ghi nhận: nhãn Đã huỷ ghi nhận; lý do CHỈ khi máy chủ trả (admin)", () => {
    const { unmount } = ve(
      dto({ tinh_trang: "da_cho_xet_lai", van_ban: { ...VB, trang_thai: "huy_ghi_nhan" }, ly_do_huy_ghi_nhan: "nhập sai số" }),
      TAT_CA,
    )
    expect(screen.getByTestId("qd-nhan-trang-thai").textContent).toBe("Đã huỷ ghi nhận")
    expect(screen.getByTestId("qd-ly-do-huy").textContent).toBe("Lý do: nhập sai số")
    unmount()
    ve(dto({ van_ban: { ...VB, trang_thai: "huy_ghi_nhan" }, ly_do_huy_ghi_nhan: null }), TAT_CA)
    expect(screen.queryByTestId("qd-ly-do-huy")).toBeNull() // người không phải admin: máy chủ không trả ⇒ không hiện
  })

  it("tình trạng / trạng thái LẠ ⇒ in nguyên (không suy)", () => {
    ve(dto({ tinh_trang: "tinh_trang_moi", van_ban: { ...VB, trang_thai: "trang_thai_moi" } }), TAT_CA)
    expect(screen.getByTestId("qd-tinh-trang").textContent).toBe("tinh_trang_moi")
    expect(screen.getByTestId("qd-nhan-trang-thai").textContent).toBe("trang_thai_moi")
  })

  it("không có bộ (set_id null) ⇒ không liên kết, không mã bộ (quyền đã biết sẵn nên không đúng rỗng)", () => {
    ve(dto({ van_ban: { ...VB, set_id: null } }), TAT_CA)
    expect(screen.getByTestId("qd-co-van-ban")).toBeTruthy()
    expect(screen.queryByTestId("qd-bo-link")).toBeNull()
    expect(screen.queryByTestId("qd-bo-ma")).toBeNull()
    expect(screen.getByTestId("qd-co-van-ban").textContent).not.toMatch(/bộ #/)
  })
})

describe("F279 — liên kết mở bộ theo cờ máy chủ xem_chi_tiet_bo", () => {
  it("có cờ xem_chi_tiet_bo (chỉ cờ này bật) ⇒ liên kết tới bộ", () => {
    ve(dto(), CHI_XEM_CHI_TIET)
    const lk = screen.getByTestId("qd-bo-link")
    expect(lk.getAttribute("href")).toBe("/admin/council-documents/8")
    expect(lk.textContent).toBe("bộ #8")
  })

  it("thiếu cờ xem_chi_tiet_bo (các cờ khác BẬT hết) ⇒ KHÔNG liên kết; vẫn hiện mã bộ dạng chữ", () => {
    ve(dto(), TAT_CA_TRU_CHI_TIET)
    expect(screen.queryByTestId("qd-bo-link")).toBeNull()
    expect(screen.queryByRole("link", { name: /bộ #8/ })).toBeNull()
    expect(screen.getByTestId("qd-bo-ma").textContent).toBe("bộ #8")
    expect(screen.getByTestId("qd-co-van-ban").textContent).toContain("Quyết định trúng tuyển số 90 ngày 20/10/2026")
  })

  it.each([
    ["403 (không có quyền module — mọi cờ tắt)", () => HttpResponse.json({ detail: "x" }, { status: 403 })],
    ["500 (không đọc được quyền ⇒ không đoán)", () => HttpResponse.json({ detail: "x" }, { status: 500 })],
  ] as const)("/quyen %s ⇒ KHÔNG liên kết, chỉ mã bộ dạng chữ", async (_ten, tra) => {
    moQuyen(tra)
    const { qc } = ve(dto())
    // đợi tới khi cache quyền ĐÃ ở trạng thái lỗi (nếu không, "không có liên kết" đúng một cách rỗng vì quyền còn đang tải)
    await waitFor(() => expect(qc.getQueryState(councilDocumentKeys.permissions())?.status).toBe("error"))
    expect(quyenGoi).toBe(1)
    expect(screen.queryByTestId("qd-bo-link")).toBeNull()
    expect(screen.getByTestId("qd-bo-ma").textContent).toBe("bộ #8")
  })

  it("quyền đang tải ⇒ chưa có liên kết (không chớp liên kết rồi mất); tải xong có cờ ⇒ liên kết hiện", async () => {
    let thaCong!: () => void
    const cho = new Promise<void>((r) => {
      thaCong = r
    })
    moQuyen(async () => {
      await cho
      return HttpResponse.json({ permissions: TAT_CA })
    })
    ve(dto())
    await waitFor(() => expect(quyenGoi).toBe(1)) // yêu cầu quyền đã đi và đang treo
    expect(screen.queryByTestId("qd-bo-link")).toBeNull()
    expect(screen.getByTestId("qd-bo-ma").textContent).toBe("bộ #8")
    thaCong()
    expect(await screen.findByTestId("qd-bo-link")).toBeTruthy()
  })
})
