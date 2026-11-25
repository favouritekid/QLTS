/**
 * GĐ2-B F4 — nhãn / định dạng DÒNG kết quả (`row-labels.ts`): chỉ ánh xạ mã máy chủ → câu; mã lạ ⇒ câu chung CÓ mã; `null` ⇒ "—"
 * (KHÔNG thành 0); điểm là chuỗi (chỉ đổi dấu thập phân); từng nguyện vọng giữ ĐÚNG thứ tự máy chủ. Dữ liệu giả.
 */
import { describe, expect, it } from "vitest"

import { E9_BANG_DIEM_CHO_CUOI, E9_MAT_CAU_HINH_GIAY } from "@/test/mocks/review-sessions-data"
import { rowSchema } from "@/lib/zod/review-sessions"

import {
  DOCUMENT_CONFIG_UNKNOWN,
  consideredChoiceLabel,
  documentGapsText,
  ethnicPriorityLabel,
  flagLabel,
  hintLabel,
  numberLabel,
  perChoiceSummary,
  priorYearLine,
  profileStatusLabel,
  reasonLabel,
  scoreLabel,
  unitRef,
  withinSeatsLabel,
} from "./row-labels"

const dong = (over: Record<string, unknown> = {}) => rowSchema.parse({ ...E9_BANG_DIEM_CHO_CUOI, ...over })

describe("F4 — nhãn mã của dòng kết quả (mã lạ ⇒ câu chung có mã)", () => {
  it.each<[string, string]>([
    ["tie_at_last_seat", "Bằng điểm ở chỗ cuối"],
    ["BELOW_MIN_SCORE", "Điểm tổng dưới ngưỡng tối thiểu"],
    ["ELIGIBILITY_FAIL:THPT", "Không đạt điều kiện trình độ văn hoá (THPT)"],
    ["thieu_ma_ho_so", "Lý do khác (mã: thieu_ma_ho_so)"],
  ])("lý do %j ⇒ %j", (ma, cau) => {
    expect(reasonLabel(ma)).toBe(cau)
  })

  it("cờ / gợi ý / ưu tiên dân tộc: mã biết ⇒ Phụ lục A (gợi ý = nhãn lựa chọn C2); lạ ⇒ câu chung có mã; null ⇒ '—'", () => {
    expect(flagLabel("major_inactive")).toBe("Ngành đang ngừng")
    expect(flagLabel("co_moi")).toBe("Cờ khác (mã: co_moi)")
    expect(hintLabel("consider_next_choice")).toBe("Xét nguyện vọng kế")
    expect(hintLabel("goi_y_moi")).toBe("Gợi ý khác (mã: goi_y_moi)")
    expect(ethnicPriorityLabel("provisional_by_commune")).toBe("Tạm cộng theo mã xã (thiếu giấy cư trú)")
    expect(ethnicPriorityLabel("trang_thai_moi")).toBe("Khác (mã: trang_thai_moi)")
    expect(ethnicPriorityLabel(null)).toBe("—")
  })

  it("trạng thái hồ sơ: CÙNG nhãn ứng dụng; lạ ⇒ chữ máy chủ", () => {
    expect(profileStatusLabel("submitted")).toBe("Chờ duyệt")
    expect(profileStatusLabel("trang_thai_moi")).toBe("trang_thai_moi")
  })
})

describe("F4 — null ≠ 0, điểm là chuỗi máy chủ", () => {
  it("điểm / số / chỗ / đơn vị: null ⇒ '—'; '0.00' ⇒ '0,00'; 0 ⇒ '0' (không giấu số 0, không bịa 0)", () => {
    // Biến thể phá: `score ?? "0.00"` / `n ?? 0` ⇒ ĐỎ.
    expect(scoreLabel(null)).toBe("—")
    expect(scoreLabel("0.00")).toBe("0,00")
    expect(scoreLabel("18.50")).toBe("18,50")
    expect(numberLabel(null)).toBe("—")
    expect(numberLabel(0)).toBe("0")
    expect(withinSeatsLabel(null)).toBe("—")
    expect(withinSeatsLabel(true)).toBe("Trong số chỗ (giữ chỗ tạm)")
    expect(withinSeatsLabel(false)).toBe("Ngoài số chỗ")
    expect(unitRef(null, null)).toBe("—")
    expect(unitRef(4, null)).toBe("Đơn vị #4")
  })

  it("S7 (phụ lục S3/S7): unitRef hiện `unit_name` máy chủ trả; tên null / trắng ⇒ 'Đơn vị #id'; unit_id null ⇒ '—'", () => {
    expect(unitRef(4, "Khoa Giả Một")).toBe("Khoa Giả Một")
    expect(unitRef(4, "   ")).toBe("Đơn vị #4")
    expect(unitRef(null, "Khoa Giả Một")).toBe("—")
  })

  it("NV được xếp: 'NV{số} · <mã> — <tên> · <loại hình>'; null ⇒ '—'", () => {
    expect(consideredChoiceLabel(dong().considered_choice)).toBe("NV1 · <mã> — <tên ngành> · <loại hình>")
    expect(consideredChoiceLabel(null)).toBe("—")
  })

  it("từng nguyện vọng giữ ĐÚNG thứ tự máy chủ (không sắp theo số NV); trạng thái lạ ⇒ chữ máy chủ", () => {
    // Biến thể phá: sắp lại theo `display_order` ⇒ "NV1 … · NV2 …" ⇒ ĐỎ.
    const r = dong({
      per_choice: [
        { choice_id: 2, display_order: 2, offering_academic_info_id: 57, status: "below_floor", reason_codes: [], review_total: null, floor_score: null },
        { choice_id: 1, display_order: 1, offering_academic_info_id: 41, status: "trang_thai_moi", reason_codes: [], review_total: null, floor_score: null },
      ],
    })
    expect(perChoiceSummary(r.per_choice)).toBe("NV2: Dưới điểm sàn · NV1: trang_thai_moi")
    expect(perChoiceSummary([])).toBe("—")
  })
})

describe("F4 — giấy thiếu / chưa duyệt (document_gaps)", () => {
  it.each<[string, Record<string, unknown>, string]>([
    ["null + document_config_missing ⇒ câu riêng", { document_gaps: null, reason_codes: ["document_config_missing"] }, DOCUMENT_CONFIG_UNKNOWN],
    ["null + document_config_invalid ⇒ câu riêng", { document_gaps: null, reason_codes: ["document_config_invalid"] }, DOCUMENT_CONFIG_UNKNOWN],
    ["null + lý do khác ⇒ '—'", { document_gaps: null, reason_codes: ["tie_at_last_seat"] }, "—"],
    [
      "có danh sách ⇒ 'Thiếu: … · Chưa duyệt: …'",
      { document_gaps: { missing: ["hoc_ba_thpt"], not_verified: ["giay_khai_sinh"] }, reason_codes: [] },
      "Thiếu: hoc_ba_thpt · Chưa duyệt: giay_khai_sinh",
    ],
  ])("%s", (_ten, over, ky_vong) => {
    expect(documentGapsText(rowSchema.parse({ ...E9_MAT_CAU_HINH_GIAY, ...over }))).toBe(ky_vong)
  })

  it("năm trước (A13): năm + căn cứ + trạng thái (null ⇒ '—'); căn cứ lạ ⇒ chữ máy chủ", () => {
    expect(priorYearLine({ year: 2025, basis: "admission_decision", status: null })).toBe(
      "Năm 2025 — Có Quyết định trúng tuyển — trạng thái —",
    )
    expect(priorYearLine({ year: 2025, basis: "can_cu_moi", status: "submitted" })).toBe("Năm 2025 — can_cu_moi — trạng thái Chờ duyệt")
  })
})
