/**
 * Bản 6 C2.2 — bộ lọc đang áp của danh sách ⇒ `BulkVerifyFilter`: chép đúng khoá lọc, bỏ phân trang / sắp xếp, không bao
 * giờ có `profile_ids`; giá trị lạ ⇒ null (không bỏ bớt khoá — bỏ khoá là mở rộng tập hồ sơ).
 */
import { describe, expect, it } from "vitest"

import { toBulkVerifyFilter } from "./bulk-filter"

describe("toBulkVerifyFilter", () => {
  it("chép mọi khoá lọc, bỏ page / page_size / sort_by / order", () => {
    expect(
      toBulkVerifyFilter({
        page: 2,
        page_size: 20,
        sort_by: "full_name",
        order: "asc",
        status: "submitted",
        search: "abc",
        major_id: "4,5",
        academic_year: 2026,
        degree_level: "cao_dang",
        payment_status: "unpaid",
        date_from: "2026-11-01",
        date_to: "2026-11-18",
        assigned_officer_id: "7",
        unit_id: 3,
        assigned_reviewer_id: "8",
        unassigned: true,
      }),
    ).toEqual({
      status: "submitted",
      search: "abc",
      major_id: "4,5",
      academic_year: 2026,
      degree_level: "cao_dang",
      payment_status: "unpaid",
      date_from: "2026-11-01",
      date_to: "2026-11-18",
      assigned_officer_id: "7",
      unit_id: 3,
      assigned_reviewer_id: "8",
      unassigned: true,
    })
  })

  it("bộ lọc mặc định (chỉ phân trang) ⇒ filter rỗng, không có profile_ids", () => {
    const f = toBulkVerifyFilter({ page: 1, page_size: 20 })
    expect(f).toEqual({})
    expect(f).not.toHaveProperty("profile_ids")
  })

  it("payment_status ngoài enum ⇒ null (không gửi, không bỏ bớt khoá)", () => {
    expect(toBulkVerifyFilter({ payment_status: "la" })).toBeNull()
  })
})
