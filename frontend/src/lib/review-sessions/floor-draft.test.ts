/**
 * GĐ2-B F2 — hàm thuần của bản soạn điểm sàn (`floor-draft.ts`). Khoá:
 *  - DẠNG điểm theo HĐ4 §1.4 / HĐ3: nhận dấu phẩy, gửi chuỗi dấu chấm ĐÚNG hai chữ số ("15,5" ⇒ "15.50"); ô trống ⇒ không gửi (không
 *    thành 0); sai dạng ⇒ khoá. Biến thể phá: bỏ `padEnd` ⇒ "15.5"; nhận 4 chữ số; ô trống ⇒ "0.00" ⇒ ĐỎ.
 *  - thin client: nhóm "Cần nhập sàn" đọc CỜ `floor_applicable`, dòng gửi đi đọc CỜ `floor_accepted` — biến thể phá: suy nhóm từ
 *    `state` ∈ {ok, floor_missing} / suy "nhận được" từ `!is_deleted` ⇒ ĐỎ (dữ liệu thử cố ý cho cờ NGƯỢC với `state`).
 * Dữ liệu giả.
 */
import { describe, expect, it } from "vitest"

import { floorCandidateGia, floorGia } from "@/test/mocks/review-sessions-data"
import { floorCandidateSchema, floorSchema, type ReviewFloorCandidate } from "@/lib/zod/review-sessions"

import {
  buildFloorsPlan,
  floorDraftConflicts,
  floorIdsFromValidation,
  groupFloorCandidates,
  lastFloorSave,
  normalizeFloorInput,
  type FloorInput,
} from "./floor-draft"

const hv = (over: Record<string, unknown> = {}): ReviewFloorCandidate => floorCandidateSchema.parse(floorCandidateGia(over))

describe("dạng điểm (HĐ4 §1.4, HĐ3) — kiểm DẠNG, không luật", () => {
  it.each<[string, FloorInput]>([
    ["15,5", { kind: "ok", value: "15.50" }],
    ["15.5", { kind: "ok", value: "15.50" }],
    [" 18 ", { kind: "ok", value: "18.00" }],
    ["0", { kind: "ok", value: "0.00" }],
    ["000", { kind: "ok", value: "0.00" }],
    ["015,25", { kind: "ok", value: "15.25" }],
    ["999,99", { kind: "ok", value: "999.99" }],
    ["", { kind: "empty" }],
    ["   ", { kind: "empty" }],
    ["7,", { kind: "invalid" }],
    ["1000", { kind: "invalid" }],
    ["-1", { kind: "invalid" }],
    ["15,555", { kind: "invalid" }],
    ["1e2", { kind: "invalid" }],
    ["abc", { kind: "invalid" }],
    ["１５", { kind: "invalid" }],
  ])("%j ⇒ %j", (vao, ra) => {
    expect(normalizeFloorInput(vao)).toEqual(ra)
  })
})

describe("thân E4 — TOÀN BỘ danh sách, chỉ dòng máy chủ báo nhận được", () => {
  it("ô trống bỏ khỏi danh sách (không thành 0); dòng floor_accepted=false bỏ kể cả còn mức đang lưu; sắp id tăng; ô chưa gõ giữ mức đang lưu", () => {
    const items = [
      hv({ offering_academic_info_id: 50, floor_score: null }),
      hv({ offering_academic_info_id: 41, floor_score: "15.00" }),
      hv({ offering_academic_info_id: 44, floor_score: "16.00" }),
      // state "deleted" nhưng máy chủ nói E4 NHẬN — giao diện theo cờ, không theo state
      hv({ offering_academic_info_id: 60, state: "deleted", is_deleted: true, floor_applicable: false, floor_score: null }),
      // state "ok" nhưng máy chủ nói E4 KHÔNG nhận ⇒ bỏ, ghi vào droppedIds
      hv({ offering_academic_info_id: 70, state: "ok", floor_accepted: false, floor_score: "12.00" }),
    ]
    const plan = buildFloorsPlan(items, { 50: "17,5", 44: "", 60: "9" })
    expect(plan.floors).toEqual([
      { offering_academic_info_id: 41, floor_score: "15.00" },
      { offering_academic_info_id: 50, floor_score: "17.50" },
      { offering_academic_info_id: 60, floor_score: "9.00" },
    ])
    expect(plan.invalidIds).toEqual([])
    expect(plan.droppedIds).toEqual([70])
  })

  it("ô sai dạng ⇒ invalidIds (khoá Lưu), dòng ấy không vào thân", () => {
    const plan = buildFloorsPlan([hv({ offering_academic_info_id: 41 }), hv({ offering_academic_info_id: 42 })], { 42: "15,555" })
    expect(plan.invalidIds).toEqual([42])
    expect(plan.floors).toEqual([{ offering_academic_info_id: 41, floor_score: "15.00" }])
  })
})

describe("thin client — nhóm theo CỜ máy chủ, FE không tự suy nhóm 'Cần nhập sàn'", () => {
  it("floor_applicable quyết nhóm 'Cần nhập sàn' kể cả khi state nói khác; dòng không áp dụng theo NGUYÊN state; state lạ ⇒ 'khác'", () => {
    const items = [
      hv({ offering_academic_info_id: 1, state: "ok", floor_applicable: false }),
      hv({ offering_academic_info_id: 2, state: "quota_closed", annual_admission_quota: 0, floor_applicable: true }),
      hv({ offering_academic_info_id: 3, state: "floor_missing", floor_applicable: true }),
      hv({ offering_academic_info_id: 4, state: "quota_closed", annual_admission_quota: 0, floor_applicable: false }),
      hv({ offering_academic_info_id: 5, state: "group_missing", floor_applicable: false }),
      hv({ offering_academic_info_id: 6, state: "trang_thai_moi", floor_applicable: false }),
    ]
    const nhom = Object.fromEntries(groupFloorCandidates(items).map((g) => [g.key, g.items.map((i) => i.offering_academic_info_id)]))
    expect(nhom).toEqual({ needs_floor: [2, 3], closed: [4], not_reviewable: [5], other: [1, 6] })
  })
})

describe("409 STALE — bảng so chỉ gồm dòng NGƯỜI DÙNG đã sửa mà khác mức vừa lưu", () => {
  it("so chuỗi đã chuẩn hoá ('15,5' = '15.50'); ô trống ↔ null; dòng không sửa không vào bảng", () => {
    const items = [
      hv({ offering_academic_info_id: 41, floor_score: "15.50" }),
      hv({ offering_academic_info_id: 42, floor_score: "15.50" }),
      hv({ offering_academic_info_id: 43, floor_score: null }),
      hv({ offering_academic_info_id: 44, floor_score: "10.00" }),
      hv({ offering_academic_info_id: 45, floor_score: "10.00" }),
    ]
    const xung = floorDraftConflicts(items, { 41: "15,5", 42: "16", 43: "", 44: "" })
    expect(xung.map((x) => [x.item.offering_academic_info_id, x.mine, x.saved])).toEqual([
      [42, "16", "15.50"],
      [44, "", "10.00"],
    ])
  })
})

describe("đọc thân lỗi E4", () => {
  it("422: loc ['body','floors',i,…] ⇒ id của dòng đã gửi ở vị trí i (readApiError bỏ số nên đọc thẳng errors)", () => {
    const data = {
      errors: [
        { loc: ["body", "floors", 1, "floor_score"], msg: "x" },
        { loc: ["body", "floors", 9, "floor_score"], msg: "ngoài tầm" },
        { loc: ["body", "version"], msg: "khác" },
      ],
    }
    expect(floorIdsFromValidation(data, [41, 50])).toEqual([50])
    expect(floorIdsFromValidation(undefined, [41])).toEqual([])
  })
})

describe("owner G2 — MỘT dòng 'lưu lần cuối'", () => {
  it("lấy người / lúc của lần lưu muộn nhất; danh sách rỗng ⇒ null", () => {
    const floors = [
      floorSchema.parse(floorGia({ offering_academic_info_id: 41, updated_by_user_id: 1, updated_at: "2026-11-24T02:05:00Z" })),
      floorSchema.parse(floorGia({ offering_academic_info_id: 42, updated_by_user_id: 7, updated_at: "2026-11-24T03:00:00Z" })),
    ]
    expect(lastFloorSave(floors)).toEqual({ userId: 7, at: "2026-11-24T03:00:00Z" })
    expect(lastFloorSave([])).toBeNull()
  })
})
