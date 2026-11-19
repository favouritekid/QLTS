/**
 * GĐ2-F1 — ô chỉ tiêu / trần TRỐNG ≠ 0 (quyết định owner 19-11 câu 4): trống ⇒ `null` ra máy chủ; 0 chỉ khi gõ rõ; giá
 * trị `null` của máy chủ hiện thành ô trống, không thành "0".
 */
import { describe, expect, it } from "vitest"

import type { QuotaTableOut } from "@/lib/zod/quota-tables"

import { countToInput, draftFromTable, draftToPutBody, memberLabel, parseCountInput } from "./draft"

describe("parseCountInput", () => {
  it.each([
    ["", null],
    ["   ", null],
    ["0", 0],
    [" 0 ", 0],
    ["12", 12],
  ])("%j ⇒ %j", (vao, ra) => {
    expect(parseCountInput(vao)).toBe(ra)
  })
})

describe("countToInput", () => {
  it("null / thiếu ⇒ ô trống; 0 ⇒ '0'", () => {
    expect(countToInput(null)).toBe("")
    expect(countToInput(undefined)).toBe("")
    expect(countToInput(0)).toBe("0")
  })
})

const BANG: QuotaTableOut = {
  academic_year: 2026,
  status: "draft",
  version: 3,
  locked_by_user_id: null,
  locked_at: null,
  available_actions: ["edit", "lock"],
  quota_fingerprint: "a".repeat(64),
  groups: [
    {
      id: 7,
      code: "N1",
      name: "Nhóm thử",
      ceiling: 0,
      usage: { publish_count: 0, approved_count: 0, used: 0 },
      members: [
        { offering_academic_info_id: 11, offering_id: 1, major_code: "M1", major_name: "Ngành Một", offering_type: "Chính quy", annual_admission_quota: null },
        { offering_academic_info_id: 12, offering_id: 2, major_code: "M2", major_name: "Ngành Hai", offering_type: null, annual_admission_quota: 0 },
      ],
    },
  ],
}

describe("draftFromTable ⇄ draftToPutBody", () => {
  it("chỉ tiêu null của máy chủ ⇒ ô trống ⇒ gửi lại null (không thành 0); 0 giữ 0; trần 0 giữ 0", () => {
    const nhap = draftFromTable(BANG)
    expect(nhap[0].members.map((m) => m.quota)).toEqual(["", "0"])
    const than = draftToPutBody(BANG.version, BANG.quota_fingerprint, nhap)
    expect(than).toEqual({
      version: 3,
      quota_fingerprint: "a".repeat(64),
      groups: [
        {
          code: "N1",
          name: "Nhóm thử",
          ceiling: 0,
          members: [
            { offering_academic_info_id: 11, annual_admission_quota: null },
            { offering_academic_info_id: 12, annual_admission_quota: 0 },
          ],
        },
      ],
    })
  })

  it("trần nhóm để trống ⇒ null", () => {
    const than = draftToPutBody(0, "b".repeat(64), [{ key: "k", code: "N9", name: "Mới", ceiling: "", members: [] }])
    expect(than.groups[0].ceiling).toBeNull()
  })

  it("năm chưa có bảng ⇒ bản nháp rỗng", () => {
    expect(draftFromTable(null)).toEqual([])
  })
})

describe("memberLabel", () => {
  it("ghép mã — tên (hình thức); thiếu tên ⇒ id học vụ", () => {
    expect(memberLabel(BANG.groups[0].members[0])).toBe("M1 — Ngành Một (Chính quy)")
    expect(
      memberLabel({ offering_academic_info_id: 5, major_code: null, major_name: null, offering_type: null }),
    ).toBe("Học vụ #5")
  })
})
