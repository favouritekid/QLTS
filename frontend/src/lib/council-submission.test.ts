/**
 * Giải nghĩa giao thức lượt gửi — bảng quyết định thuần (đặc tả bản 2 mục 3.7.5). Các ca "đường dài" (mở lượt → gửi →
 * phân xử qua mạng giả) ở `hooks/admin/useRecordDecision.test.tsx`; ở đây khoá TỪNG mã HTTP và từng giá trị `ket_qua`.
 */
import { AxiosError } from "axios"
import { describe, expect, it } from "vitest"

import {
  explainAdjudication,
  submissionErrorHandling,
  pendingSubmission,
  recordedSubmission,
  classifySubmissionError,
  UNDETERMINED_LABEL,
} from "./council-submission"
import type { CouncilSubmission } from "@/lib/zod/council-documents"

function loiHttp(status: number, data: Record<string, unknown> = {}) {
  return new AxiosError("loi", "ERR_BAD_RESPONSE", undefined, undefined, {
    status,
    statusText: "",
    data,
    headers: {},
    config: {} as never,
  })
}

describe("phanLoaiLoiGui — chỉ mã đã định mới là 'bị từ chối'; còn lại LUÔN 'chưa xác định'", () => {
  it.each([400, 403, 409, 413, 422, 429])("%i ⇒ bi_tu_choi (yêu cầu bị chặn trước khi ghi)", (s) => {
    expect(classifySubmissionError(loiHttp(s))).toBe("bi_tu_choi")
  })

  it.each([401, 404, 408, 500, 501, 502, 503, 504, 520])("%i ⇒ chua_xac_dinh (không suy)", (s) => {
    expect(classifySubmissionError(loiHttp(s))).toBe("chua_xac_dinh")
  })

  it("503 + ADMISSION_FROZEN (middleware chặn TRƯỚC handler) ⇒ bi_tu_choi", () => {
    expect(classifySubmissionError(loiHttp(503, { code: "ADMISSION_FROZEN" }))).toBe("bi_tu_choi")
  })

  it("không có phản hồi (mất mạng) ⇒ chua_xac_dinh", () => {
    expect(classifySubmissionError(new AxiosError("Network Error", "ERR_NETWORK"))).toBe("chua_xac_dinh")
  })

  it("lỗi không phải axios (vd Zod nổ vì thân 2xx sai dạng) ⇒ chua_xac_dinh", () => {
    expect(classifySubmissionError(new Error("zod"))).toBe("chua_xac_dinh")
    expect(classifySubmissionError(undefined)).toBe("chua_xac_dinh")
    expect(classifySubmissionError("chuoi")).toBe("chua_xac_dinh")
  })
})

describe("huongXuLyLoiGui — rẽ nhánh theo ma_loi, không theo chữ", () => {
  it.each([
    ["luot_da_chan", "mo_luot_moi"],
    ["luot_da_dung_noi_dung_khac", "phan_xu"],
    ["luot_khong_hop_le", "tai_lai_bo"],
    ["ma_loi_la", "sua_va_gui_lai"],
  ])("%s ⇒ %s", (ma_loi, huong) => {
    expect(submissionErrorHandling(loiHttp(409, { ma_loi }))).toBe(huong)
  })

  it("không có ma_loi (400 nghiệp vụ) ⇒ sua_va_gui_lai; chữ trong detail KHÔNG đổi nhánh", () => {
    expect(submissionErrorHandling(loiHttp(400, { detail: "Lượt gửi đã bị chặn." }))).toBe("sua_va_gui_lai")
  })
})

describe("giaiNghiaPhanXu — bốn kết quả + lạ", () => {
  const dto = {
    id: 1, loai: "trung_tuyen", trang_thai: "hieu_luc", can_bo: false, so_quyet_dinh: "1", ngay_ky: "2026-01-01",
    pham_vi_so: 2026, so_ho_so: 1, ghi_nhan_boi_id: 1, ghi_nhan_luc: "x", canh_bao_vuot_chi_tieu: [], lap_lai: false,
  }
  it("da_ghi + DTO", () => {
    expect(explainAdjudication({ ket_qua: "da_ghi", quyet_dinh: dto })).toEqual({ kind: "da_ghi", decision: dto })
  })
  it("da_ghi thiếu DTO ⇒ da_ghi_thieu_chi_tiet (vẫn 'đã ghi')", () => {
    expect(explainAdjudication({ ket_qua: "da_ghi" })).toEqual({ kind: "da_ghi_thieu_chi_tiet" })
    expect(explainAdjudication({ ket_qua: "da_ghi", quyet_dinh: null })).toEqual({ kind: "da_ghi_thieu_chi_tiet" })
  })
  it("chua_ghi_da_chan", () => {
    expect(explainAdjudication({ ket_qua: "chua_ghi_da_chan" })).toEqual({ kind: "chua_ghi_da_chan" })
  })
  it("dang_xu_ly", () => {
    expect(explainAdjudication({ ket_qua: "dang_xu_ly" })).toEqual({ kind: "dang_xu_ly" })
  })
  it.each(["", "chua_ghi", "DA_GHI", "da_ghi ", "khac"])("ket_qua lạ %j ⇒ van_chua_ro (đặc biệt 'chua_ghi' KHÔNG được hiểu là chưa ghi)", (k) => {
    expect(explainAdjudication({ ket_qua: k })).toEqual({ kind: "van_chua_ro" })
  })
})

describe("đọc danh sách lượt", () => {
  const l = (ma: string, trang_thai: string, tao_luc: string, decision_id: number | null = null): CouncilSubmission => ({
    ma, trang_thai, tao_luc, ket_thuc_luc: null, decision_id,
  })
  it("luotDangCho: chỉ trang_thai đúng 'cho_gui'", () => {
    expect(pendingSubmission([l("a", "da_chan", "1"), l("b", "cho_gui", "2")])?.ma).toBe("b")
    expect(pendingSubmission([l("a", "CHO_GUI", "1"), l("b", "cho_gui_moi", "2")])).toBeUndefined()
    expect(pendingSubmission([])).toBeUndefined()
  })
  it("luotDaGhi: lượt da_ghi CÓ decision_id, mới nhất", () => {
    expect(recordedSubmission([l("a", "da_ghi", "2026-01-01", 1), l("b", "da_ghi", "2026-02-01", 2)])?.decision_id).toBe(2)
    expect(recordedSubmission([l("a", "da_ghi", "2026-01-01", null)])).toBeUndefined()
  })
})

it("nhãn khi lượt chưa rõ KHÔNG chứa 'chưa ghi nhận' (đặc tả 5.6.1)", () => {
  expect(UNDETERMINED_LABEL).toBe("Chưa xác định")
  expect(UNDETERMINED_LABEL.toLowerCase()).not.toContain("chưa ghi")
})
