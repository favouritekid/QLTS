/**
 * GĐ2-B F0 — schema lần xét nháp (HĐ4 bản 4 §3, §9; thiết kế giao diện GĐ2-B §6.1, §6.2 F0):
 *  - đọc đúng các ví dụ HĐ4 §9 (E5 đã huỷ + ba dòng E9);
 *  - trường lạ bị BỎ QUA (thêm trường là thay đổi "không phá", HĐ4 §1.8);
 *  - tab / trạng thái / mã / hành động lạ KHÔNG làm hỏng parse (GĐ2-C thêm giá trị);
 *  - điểm GIỮ chuỗi ("18.50" không thành 18.5), điểm dạng số ⇒ lỗi hợp đồng (HĐ3); `null` giữ nguyên `null`;
 *  - thân gửi đi `.strict()` (máy chủ `extra = "forbid"`), lý do huỷ đếm theo KÝ TỰ như `len()` của máy chủ.
 * Dữ liệu giả.
 */
import { describe, expect, it } from "vitest"

import {
  E9_BANG_DIEM_CHO_CUOI,
  E9_MAT_CAU_HINH_GIAY,
  E9_THIEU_GIAY,
  floorGia,
  listItemGia,
  pageGia,
  runGia,
  sessionDaHuyGia,
  sessionGia,
} from "@/test/mocks/review-sessions-data"

import {
  reviewFloorsPutBodySchema,
  reviewRunCreateBodySchema,
  reviewSessionCancelBodySchema,
  reviewSessionCreateBodySchema,
  rowPageSchema,
  rowSchema,
  runSchema,
  sessionPageSchema,
  sessionSchema,
} from "./review-sessions"

describe("HĐ4 §9 — đọc đúng ví dụ của hợp đồng", () => {
  it("E5 đã huỷ: floors rỗng, available_actions rỗng, lý do + người huỷ giữ nguyên", () => {
    const s = sessionSchema.parse(sessionDaHuyGia())
    expect(s.status).toBe("cancelled")
    expect(s.floors).toEqual([])
    expect(s.available_actions).toEqual([])
    expect(s.cancel_reason).toBe("<lý do>")
    expect(s.cancelled_by_user_id).toBe(1)
    expect(s.latest_done_run_id).toBe(11)
  })

  it("E9 dòng mất cấu hình giấy: document_gaps null, mọi trường không áp dụng là null (không thành 0 / rỗng)", () => {
    const r = rowSchema.parse(E9_MAT_CAU_HINH_GIAY)
    expect(r.reason_codes).toEqual(["document_config_missing"])
    expect(r.document_gaps).toBeNull()
    expect(r.review_total).toBeNull()
    expect(r.rank_in_major).toBeNull()
    expect(r.within_seats).toBeNull()
    expect(r.ethnic_priority_state).toBeNull()
    expect(r.considered_choice).toBeNull()
  })

  it("E9 dòng thiếu giấy: document_gaps giữ đúng hai danh sách mã", () => {
    const r = rowSchema.parse(E9_THIEU_GIAY)
    expect(r.document_gaps).toEqual({ missing: ["hoc_ba_thpt"], not_verified: ["giay_khai_sinh"] })
  })

  it("E9 dòng needs_decision: điểm là CHUỖI giữ nguyên, per_choice giữ thứ tự máy chủ", () => {
    const r = rowSchema.parse(E9_BANG_DIEM_CHO_CUOI)
    expect(r.review_total).toBe("18.50")
    expect(typeof r.review_total).toBe("string")
    expect(r.score_parts).toEqual({ subject_total: "17.00", area: "0.50", object: "1.00", priority_total: "1.50" })
    expect(r.floor_score).toBe("15.00")
    expect(r.per_choice.map((c) => c.choice_id)).toEqual([5001, 5002])
    expect(r.per_choice[1].review_total).toBeNull()
  })

  it("E8 lượt đã xong: remaining_after_auto ÂM giữ nguyên (không tự tính lại)", () => {
    const run = runSchema.parse(runGia())
    expect(run.quota_view?.groups[0].remaining_after_auto).toBe(-2)
    expect(run.inputs.floors).toEqual([{ offering_academic_info_id: 41, floor_score: "15.00" }])
  })
})

describe("HĐ4 §1.8 — trường lạ bị bỏ qua, giá trị lạ không làm hỏng parse", () => {
  it("trường lạ ở SessionOut, ở dòng E9 và ở trang ⇒ parse được, trường lạ bị bỏ", () => {
    const s = sessionSchema.parse({ ...sessionGia(), truong_moi_cua_gd2c: 1 }) as Record<string, unknown>
    expect(s).not.toHaveProperty("truong_moi_cua_gd2c")
    const r = rowSchema.parse({ ...E9_BANG_DIEM_CHO_CUOI, unit_name: "<đơn vị>", effective_selection: null }) as Record<string, unknown>
    expect(r).not.toHaveProperty("unit_name")
    const p = sessionPageSchema.parse({ ...pageGia([listItemGia()]), them: true }) as Record<string, unknown>
    expect(p).not.toHaveProperty("them")
  })

  it("trạng thái / hành động lạ (GĐ2-C `locked`, `lock`) ⇒ parse được, giữ nguyên chữ máy chủ", () => {
    const s = sessionSchema.parse(sessionGia({ status: "trang_thai_moi", available_actions: ["cancel", "lock"] }))
    expect(s.status).toBe("trang_thai_moi")
    expect(s.available_actions).toEqual(["cancel", "lock"])
  })

  it("tab / mã lý do / cờ / gợi ý lạ (GĐ2-C `excluded`) ⇒ parse được", () => {
    const r = rowSchema.parse({
      ...E9_MAT_CAU_HINH_GIAY,
      tab: "excluded",
      reason_codes: ["ma_ly_do_moi"],
      flags: ["co_moi"],
      decision_hints: ["goi_y_moi"],
      ethnic_priority_state: "gia_tri_moi",
    })
    expect(r.tab).toBe("excluded")
    expect(r.reason_codes).toEqual(["ma_ly_do_moi"])
    const page = rowPageSchema.parse({ ...pageGia([]), tab_counts: { auto: 0, excluded: 3 } })
    expect(page.tab_counts).toEqual({ auto: 0, excluded: 3 })
  })
})

describe("HĐ3 — điểm là chuỗi hai chữ số", () => {
  it("điểm dạng SỐ ⇒ lỗi hợp đồng (không lặng lẽ nhận 18.5)", () => {
    expect(rowSchema.safeParse({ ...E9_BANG_DIEM_CHO_CUOI, review_total: 18.5 }).success).toBe(false)
    expect(sessionSchema.safeParse(sessionGia({ floors: [floorGia({ floor_score: 15 })] })).success).toBe(false)
  })

  it("chuỗi điểm sai dạng (một chữ số thập phân) ⇒ lỗi hợp đồng", () => {
    expect(rowSchema.safeParse({ ...E9_BANG_DIEM_CHO_CUOI, floor_score: "15.5" }).success).toBe(false)
  })
})

describe("thân gửi đi `.strict()` (máy chủ extra = forbid)", () => {
  it("E1: khoá lạ ⇒ không gửi", () => {
    expect(reviewSessionCreateBodySchema.safeParse({ academic_year: 2026, admission_round_id: 7 }).success).toBe(true)
    expect(reviewSessionCreateBodySchema.safeParse({ academic_year: 2026, admission_round_id: 7, x: 1 }).success).toBe(false)
  })

  it("E4: khoá lạ ở dòng sàn (kiểu `bypass_quota`) ⇒ không gửi; điểm chuỗi dấu chấm ≤ 2 chữ số thập phân", () => {
    const ok = { version: 2, floors: [{ offering_academic_info_id: 41, floor_score: "15.50" }] }
    expect(reviewFloorsPutBodySchema.safeParse(ok).success).toBe(true)
    expect(
      reviewFloorsPutBodySchema.safeParse({ ...ok, floors: [{ offering_academic_info_id: 41, floor_score: "15.50", bypass_quota: true }] })
        .success,
    ).toBe(false)
    expect(reviewFloorsPutBodySchema.safeParse({ ...ok, floors: [{ offering_academic_info_id: 41, floor_score: "15,5" }] }).success).toBe(
      false,
    )
  })

  it("E5: lý do trắng ⇒ không gửi; đếm theo KÝ TỰ (1000 ký tự có dấu / emoji vẫn hợp lệ, 1001 thì không)", () => {
    expect(reviewSessionCancelBodySchema.safeParse({ version: 2, reason: "   \n " }).success).toBe(false)
    expect(reviewSessionCancelBodySchema.safeParse({ version: 2, reason: "lý do" }).success).toBe(true)
    const emoji = "😀".repeat(1000) // 2000 đơn vị UTF-16, 1000 ký tự — máy chủ (len của Python) nhận
    expect(reviewSessionCancelBodySchema.safeParse({ version: 2, reason: emoji }).success).toBe(true)
    expect(reviewSessionCancelBodySchema.safeParse({ version: 2, reason: "ạ".repeat(1001) }).success).toBe(false)
    expect(reviewSessionCancelBodySchema.safeParse({ version: 2, reason: "x", ghi_chu: "" }).success).toBe(false)
  })

  it("E6: chỉ `evaluate` + session_version; kind khác hoặc khoá lạ ⇒ không gửi", () => {
    expect(reviewRunCreateBodySchema.safeParse({ kind: "evaluate", session_version: 2 }).success).toBe(true)
    expect(reviewRunCreateBodySchema.safeParse({ kind: "lock", session_version: 2 }).success).toBe(false)
    expect(reviewRunCreateBodySchema.safeParse({ kind: "evaluate", session_version: 2, bypass_floor: true }).success).toBe(false)
  })
})
