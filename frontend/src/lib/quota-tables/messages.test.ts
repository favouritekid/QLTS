/**
 * GĐ2-F1 — câu cho lỗi bảng chỉ tiêu theo `reason_code` của máy chủ (409 / 400) + vị trí lỗi 422 của thân PUT; nhãn ngành
 * thay cho id; không lộ mã nội bộ.
 */
import { describe, expect, it } from "vitest"
import { AxiosError, AxiosHeaders } from "axios"

import { readApiError } from "@/lib/error-handler"

import type { DraftGroup } from "./draft"
import { describeQuotaTableError, isQuotaTableNotFound, QUOTA_TABLE_NO_ACCESS_MESSAGE, serverAllows } from "./messages"

function loi(status: number, data: Record<string, unknown>): AxiosError {
  const config = { headers: new AxiosHeaders() }
  return new AxiosError("loi", "ERR_BAD_RESPONSE", config, undefined, {
    status,
    statusText: "",
    headers: {},
    config,
    data,
  })
}

const NHAN: Record<number, string> = { 11: "M1 — Ngành Một", 12: "M2 — Ngành Hai" }
const ctx = (draft?: DraftGroup[]) => ({
  year: 2026,
  labelOf: (id: number) => NHAN[id] ?? `Học vụ #${id}`,
  draft,
})

describe("describeQuotaTableError — 409 theo reason_code", () => {
  it.each([
    ["quota_table_stale", { current_version: 4 }, /sửa ở nơi khác \(có thể ở trang Cấu hình tuyển sinh\).*phiên bản hiện tại: 4/],
    ["quota_table_locked", {}, /đã khoá — Admin mở khoá/],
    ["quota_table_already_locked", {}, /đã khoá rồi/],
    ["quota_table_not_locked", {}, /chưa khoá — không có gì để mở khoá/],
  ])("%s ⇒ câu riêng, không lộ mã", (rc, them, mau) => {
    const cau = describeQuotaTableError(loi(409, { reason_code: rc, error_code: rc.toUpperCase(), ...them }), ctx())
    expect(cau).toMatch(mau)
    expect(cau).not.toMatch(new RegExp(rc, "i"))
  })

  it("quota_table_member_quota_missing ⇒ nêu TÊN ngành thiếu chỉ tiêu (không chỉ id)", () => {
    const cau = describeQuotaTableError(
      loi(409, { reason_code: "quota_table_member_quota_missing", offering_academic_info_ids: [12, 99] }),
      ctx(),
    )
    expect(cau).toMatch(/chưa có chỉ tiêu năm/)
    expect(cau).toContain("M2 — Ngành Hai")
    expect(cau).toContain("Học vụ #99")
    expect(cau).toMatch(/0 chỉ khi/)
  })

  it("quota_table_member_deleted ⇒ nêu TÊN ngành đã xoá còn trong nhóm + cách gỡ (Codex lượt 3)", () => {
    const cau = describeQuotaTableError(
      loi(409, {
        reason_code: "quota_table_member_deleted",
        error_code: "QUOTA_TABLE_MEMBER_DELETED",
        offering_academic_info_ids: [11, 77],
      }),
      ctx(),
    )
    expect(cau).toMatch(/đã bị xoá nhưng vẫn nằm trong nhóm/)
    expect(cau).toContain("M1 — Ngành Một")
    expect(cau).toContain("Học vụ #77")
    expect(cau).toMatch(/Gỡ khỏi nhóm \(lưu bảng\) rồi khoá lại/)
    expect(cau).not.toMatch(/quota_table_member_deleted/i)
  })

  it("trigger CSDL (error_code QUOTA_TABLE_LOCKED, không reason_code) ⇒ câu bảng đã khoá", () => {
    expect(describeQuotaTableError(loi(409, { error_code: "QUOTA_TABLE_LOCKED", detail: "x" }), ctx())).toMatch(
      /đã khoá — Admin mở khoá/,
    )
  })

  it("mã lạ ⇒ câu chung, không lộ mã", () => {
    expect(describeQuotaTableError(loi(409, { reason_code: "ma_la_xyz" }), ctx())).not.toMatch(/ma_la_xyz/)
  })
})

describe("describeQuotaTableError — 400 / 422 / quyền", () => {
  it("400 quota_table_duplicate ⇒ nêu mã nhóm + tên ngành trùng", () => {
    const cau = describeQuotaTableError(
      loi(400, {
        reason_code: "quota_table_duplicate",
        duplicate_group_codes: ["N1"],
        duplicate_offering_academic_info_ids: [11],
      }),
      ctx(),
    )
    expect(cau).toContain("N1")
    expect(cau).toContain("M1 — Ngành Một")
  })

  it("400 quota_table_bad_member ⇒ nêu năm + tên ngành", () => {
    const cau = describeQuotaTableError(
      loi(400, { reason_code: "quota_table_bad_member", offering_academic_info_ids: [12] }),
      ctx(),
    )
    expect(cau).toMatch(/không thuộc năm 2026/)
    expect(cau).toContain("M2 — Ngành Hai")
  })

  it("422 ở ô chỉ tiêu của một ngành ⇒ câu nêu nhóm + ngành, ô trống", () => {
    const draft: DraftGroup[] = [
      {
        key: "a",
        code: "N1",
        name: "Nhóm",
        ceiling: "5",
        members: [
          { offering_academic_info_id: 11, label: "x", quota: "3" },
          { offering_academic_info_id: 12, label: "y", quota: "" },
        ],
      },
    ]
    const cau = describeQuotaTableError(
      loi(422, {
        error_code: "VALIDATION_ERROR",
        errors: [{ loc: ["body", "groups", 0, "members", 1, "annual_admission_quota"], msg: "Input should be a valid integer" }],
      }),
      ctx(draft),
    )
    expect(cau).toContain("Nhóm N1")
    expect(cau).toContain("M2 — Ngành Hai")
    expect(cau).toMatch(/còn trống/)
  })

  it("422 ở trần nhóm ⇒ câu trần còn trống", () => {
    const draft: DraftGroup[] = [{ key: "a", code: "N2", name: "Nhóm", ceiling: "", members: [] }]
    const cau = describeQuotaTableError(
      loi(422, { errors: [{ loc: ["body", "groups", 0, "ceiling"], msg: "x" }] }),
      ctx(draft),
    )
    expect(cau).toMatch(/Nhóm N2: trần chỉ tiêu còn trống/)
  })

  it("422 thiếu / sai dấu chỉ tiêu ⇒ câu tải lại", () => {
    expect(
      describeQuotaTableError(loi(422, { errors: [{ loc: ["body", "quota_fingerprint"], msg: "x" }] }), ctx()),
    ).toMatch(/Thiếu dấu chỉ tiêu lúc mở bảng — tải lại trang/)
  })

  it("422 lý do mở khoá ⇒ câu lý do bắt buộc", () => {
    expect(describeQuotaTableError(loi(422, { errors: [{ loc: ["body", "reason"], msg: "x" }] }), ctx())).toMatch(
      /Lý do mở khoá là bắt buộc/,
    )
  })

  it("403 ⇒ chỉ Admin", () => {
    expect(describeQuotaTableError(loi(403, { detail: "x" }), ctx())).toMatch(/Chỉ Admin/)
  })

  it("404 mã riêng quota_table_not_found ⇒ năm chưa có bảng", () => {
    expect(describeQuotaTableError(loi(404, { reason_code: "quota_table_not_found", detail: "x" }), ctx())).toBe(
      "Năm 2026 chưa có bảng chỉ tiêu.",
    )
  })

  it("H4: 404 của cổng Thư ký (thân chung, không reason_code) ⇒ KHÔNG nói 'chưa có bảng'", () => {
    const cau = describeQuotaTableError(loi(404, { detail: "Không tìm thấy", error_code: "RESOURCE_NOT_FOUND" }), ctx())
    expect(cau).toBe(QUOTA_TABLE_NO_ACCESS_MESSAGE)
    expect(cau).not.toMatch(/chưa có bảng/)
  })
})

describe("isQuotaTableNotFound / serverAllows", () => {
  it("chỉ 404 + đúng mã riêng là 'năm chưa có bảng'", () => {
    expect(isQuotaTableNotFound(readApiError(loi(404, { reason_code: "quota_table_not_found" })))).toBe(true)
    expect(isQuotaTableNotFound(readApiError(loi(404, { error_code: "RESOURCE_NOT_FOUND" })))).toBe(false)
    expect(isQuotaTableNotFound(readApiError(loi(409, { reason_code: "quota_table_not_found" })))).toBe(false)
    expect(isQuotaTableNotFound(null)).toBe(false)
  })

  it("cờ thao tác: chỉ mảng chứa đúng mã", () => {
    expect(serverAllows(["create"], "create")).toBe(true)
    expect(serverAllows([], "create")).toBe(false)
    expect(serverAllows(undefined, "create")).toBe(false)
    expect(serverAllows("create", "create")).toBe(false)
  })
})
