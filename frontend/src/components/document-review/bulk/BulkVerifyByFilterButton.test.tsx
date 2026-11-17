/**
 * Bản 6 C2.2 / đặc tả §5.9 — nút "Duyệt giấy theo bộ lọc hiện tại":
 *  - hiện CHỈ khi cờ C1 `eligible = true`; `false` / lỗi ⇒ không có nút;
 *  - xem trước gửi `filter` = ĐÚNG bộ lọc đang áp (bỏ phân trang / sắp xếp), KHÔNG `profile_ids`;
 *  - 422 quá trần ⇒ câu của máy chủ kèm số đếm, không tự cắt.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { server } from "@/test/mocks/server"
import type { AdmissionListParams } from "@/lib/zod/admissions"

import { API, B1, renderWithClient } from "../test-helpers"
import { BulkVerifyByFilterButton } from "./BulkVerifyByFilterButton"

const P = `${API}/api/admissions/documents/bulk-verify`

/** Bộ lọc đang áp như `useAdmissionsFilter().apiFilters` (kèm phân trang + sắp xếp). */
const DANG_AP: AdmissionListParams = {
  page: 3,
  page_size: 20,
  sort_by: "created_at",
  order: "desc",
  status: "submitted,resubmitted",
  search: "thí sinh mẫu",
  academic_year: 2026,
  unit_id: 3,
  assigned_officer_id: "7,9",
  unassigned: false,
}

let than: unknown[] = []
beforeEach(() => {
  than = []
  sessionStorage.clear()
})
afterEach(() => server.resetHandlers())

function coCo(tra: () => Response) {
  server.use(http.get(`${P}/eligibility`, tra))
}

describe("BulkVerifyByFilterButton", () => {
  it("cờ eligible = false ⇒ KHÔNG có nút", async () => {
    let hoi = 0
    coCo(() => {
      hoi++
      return HttpResponse.json({ eligible: false })
    })
    renderWithClient(<BulkVerifyByFilterButton filter={DANG_AP} />)
    await waitFor(() => expect(hoi).toBe(1))
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByTestId("nut-duyet-theo-bo-loc")).toBeNull()
  })

  it("endpoint cờ lỗi (403) ⇒ KHÔNG có nút", async () => {
    let hoi = 0
    coCo(() => {
      hoi++
      return HttpResponse.json({ detail: "x" }, { status: 403 })
    })
    renderWithClient(<BulkVerifyByFilterButton filter={DANG_AP} />)
    await waitFor(() => expect(hoi).toBe(1))
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByTestId("nut-duyet-theo-bo-loc")).toBeNull()
  })

  it("eligible = true ⇒ có nút; xem trước gửi ĐÚNG bộ lọc đang áp, không phân trang, KHÔNG profile_ids", async () => {
    coCo(() => HttpResponse.json({ eligible: true }))
    server.use(
      http.post(`${P}/preview`, async ({ request }) => {
        than.push(await request.json())
        return HttpResponse.json(
          {
            batch_id: B1,
            expires_at: "2026-11-18T08:30:00Z",
            counts: { profiles: 0, documents: 0, required: 0, optional: 0 },
            items: [],
            excluded: [],
          },
          { status: 201 },
        )
      }),
    )
    const u = userEvent.setup()
    renderWithClient(<BulkVerifyByFilterButton filter={DANG_AP} />)
    await u.click(await screen.findByTestId("nut-duyet-theo-bo-loc"))
    const hop = await screen.findByRole("dialog")
    await u.click(within(hop).getByRole("button", { name: "Xem trước" }))
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({
      filter: {
        status: "submitted,resubmitted",
        search: "thí sinh mẫu",
        academic_year: 2026,
        unit_id: 3,
        assigned_officer_id: "7,9",
      },
      include_optional: false,
    })
    expect(than[0]).not.toHaveProperty("profile_ids")
  })

  it("422 TOO_MANY_PROFILES ⇒ câu của máy chủ kèm số đếm, không tự cắt (không tạo lô)", async () => {
    coCo(() => HttpResponse.json({ eligible: true }))
    server.use(
      http.post(`${P}/preview`, () =>
        HttpResponse.json(
          {
            error_code: "TOO_MANY_PROFILES",
            detail: "Bộ lọc chọn 140 hồ sơ, vượt trần 100 hồ sơ mỗi lô",
            profile_count: 140,
            limit: 100,
          },
          { status: 422 },
        ),
      ),
    )
    const u = userEvent.setup()
    renderWithClient(<BulkVerifyByFilterButton filter={DANG_AP} />)
    await u.click(await screen.findByTestId("nut-duyet-theo-bo-loc"))
    const hop = await screen.findByRole("dialog")
    await u.click(within(hop).getByRole("button", { name: "Xem trước" }))
    expect(await within(hop).findByRole("alert")).toHaveTextContent("Bộ lọc chọn 140 hồ sơ, vượt trần 100 hồ sơ mỗi lô")
    expect(sessionStorage.length).toBe(0)
  })
})
