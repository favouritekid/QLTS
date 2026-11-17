/**
 * GĐ1b §2.2 — trang duyệt chéo. Ca BẮT BUỘC Codex 69 (phía giao diện): cùng cán bộ, cùng đơn vị, hai quyền — G1 chỉ
 * `reject` (hạn xa), G2 chỉ `verify` (hạn gần) — hàng đợi trả `{verify: G2, reject: G1}` ⇒ "Duyệt" gửi ĐÚNG G2, "Từ
 * chối" gửi ĐÚNG G1; giao diện không tự chọn một quyền cho cả hai. `null` ⇒ không nút. 409 actor_not_authorized ⇒
 * làm mới hàng đợi. Không có quyền ⇒ không gọi hàng đợi.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { server } from "@/test/mocks/server"

import { API, renderWithClient } from "../test-helpers"
import { CrossReviewClient } from "./CrossReviewClient"

const C = `${API}/api/admissions/cross-review`
const G1 = 11 // chỉ từ chối, hạn xa hơn
const G2 = 22 // chỉ duyệt, hạn gần hơn

const QUYEN = {
  eligible: true,
  grants: [
    { grant_id: G1, unit_id: 3, allow_verify: false, allow_reject: true, expires_at: "2026-11-30T10:00:00Z" },
    { grant_id: G2, unit_id: 3, allow_verify: true, allow_reject: false, expires_at: "2026-11-20T10:00:00Z" },
  ],
}

function muc(over: Record<string, unknown>) {
  return {
    profile_id: 5,
    document_row_id: 101,
    document_type_code: "cccd",
    row_version: 4,
    actual_submission_format: "original",
    profile_status: "submitted",
    grant_id_by_action: { verify: G2, reject: G1 },
    ...over,
  }
}

let soQueue = 0
let trangHoi: Record<string, string>[] = []
let thanVerify: unknown[] = []
let thanReject: unknown[] = []

function hangDoi(items: unknown[]) {
  server.use(
    http.get(`${C}/eligibility`, () => HttpResponse.json(QUYEN)),
    http.get(`${C}/queue`, ({ request }) => {
      soQueue++
      trangHoi.push(Object.fromEntries(new URL(request.url).searchParams))
      return HttpResponse.json({ items, page: 1, page_size: 20, total_count: items.length })
    }),
    http.get(`${C}/bulk-verify`, () => HttpResponse.json({ items: [], next_cursor: null, can_view_all: false })),
  )
}

beforeEach(() => {
  soQueue = 0
  trangHoi = []
  thanVerify = []
  thanReject = []
  server.use(
    http.post(`${C}/verify`, async ({ request }) => {
      thanVerify.push(await request.json())
      return HttpResponse.json({ profile_id: 5, document_row_id: 101, action: "verify", new_status: "verified", row_version: 5 })
    }),
    http.post(`${C}/reject`, async ({ request }) => {
      thanReject.push(await request.json())
      return HttpResponse.json({ profile_id: 5, document_row_id: 101, action: "reject", new_status: "rejected", row_version: 5 })
    }),
  )
})
afterEach(() => server.resetHandlers())

describe("CrossReviewClient", () => {
  it("không có quyền còn hiệu lực ⇒ báo, KHÔNG gọi hàng đợi", async () => {
    server.use(
      http.get(`${C}/eligibility`, () => HttpResponse.json({ eligible: false, grants: [] })),
      http.get(`${C}/queue`, () => {
        soQueue++
        return HttpResponse.json({ items: [], page: 1, page_size: 20, total_count: 0 })
      }),
    )
    renderWithClient(<CrossReviewClient />)
    expect(await screen.findByTestId("khong-co-quyen-cheo")).toBeInTheDocument()
    expect(soQueue).toBe(0)
  })

  it("Codex 69: {verify: G2, reject: G1} ⇒ Duyệt gửi G2, Từ chối gửi G1 (kèm expected_row_version, lý do)", async () => {
    hangDoi([muc({})])
    const u = userEvent.setup()
    renderWithClient(<CrossReviewClient />)
    await u.click(await screen.findByRole("button", { name: "Duyệt giấy cccd của hồ sơ #5" }))
    await waitFor(() => expect(thanVerify).toHaveLength(1))
    expect(thanVerify[0]).toEqual({ grant_id: G2, profile_id: 5, document_row_id: 101, expected_row_version: 4 })
    // hàng đợi hỏi theo SỐ TRANG (bản 5 B2)
    expect(trangHoi[0]).toEqual({ page: "1", page_size: "20" })

    await u.click(screen.getByRole("button", { name: "Từ chối giấy cccd của hồ sơ #5" }))
    const hop = await screen.findByRole("dialog")
    await u.type(within(hop).getByLabelText(/Lý do từ chối/), "giấy mờ")
    await u.click(within(hop).getByRole("button", { name: "Từ chối" }))
    await waitFor(() => expect(thanReject).toHaveLength(1))
    expect(thanReject[0]).toEqual({
      grant_id: G1,
      profile_id: 5,
      document_row_id: 101,
      expected_row_version: 4,
      reason: "giấy mờ",
    })
  })

  it("verify = null ⇒ không nút Duyệt; reject = null ⇒ không nút Từ chối", async () => {
    hangDoi([
      muc({ document_row_id: 101, grant_id_by_action: { verify: null, reject: G1 } }),
      muc({ document_row_id: 102, document_type_code: "hoc_ba_thpt", grant_id_by_action: { verify: G2, reject: null } }),
    ])
    renderWithClient(<CrossReviewClient />)
    await screen.findByTestId("hang-doi-cheo")
    expect(screen.queryByRole("button", { name: "Duyệt giấy cccd của hồ sơ #5" })).toBeNull()
    expect(screen.getByRole("button", { name: "Từ chối giấy cccd của hồ sơ #5" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Duyệt giấy hoc_ba_thpt của hồ sơ #5" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Từ chối giấy hoc_ba_thpt của hồ sơ #5" })).toBeNull()
  })

  it("409 actor_not_authorized ⇒ làm mới hàng đợi", async () => {
    hangDoi([muc({})])
    server.use(
      http.post(`${C}/verify`, () =>
        HttpResponse.json(
          { reason_code: "actor_not_authorized", error_code: "ACTOR_NOT_AUTHORIZED", detail: "x" },
          { status: 409 },
        ),
      ),
    )
    const u = userEvent.setup()
    renderWithClient(<CrossReviewClient />)
    await u.click(await screen.findByRole("button", { name: "Duyệt giấy cccd của hồ sơ #5" }))
    await waitFor(() => expect(soQueue).toBeGreaterThanOrEqual(2))
  })

  it("phân trang theo số trang: total_count 45 ⇒ Trang 1/3; 'Trang sau' hỏi page=2", async () => {
    server.use(
      http.get(`${C}/eligibility`, () => HttpResponse.json(QUYEN)),
      http.get(`${C}/queue`, ({ request }) => {
        const q = Object.fromEntries(new URL(request.url).searchParams)
        trangHoi.push(q)
        return HttpResponse.json({ items: [muc({})], page: Number(q.page), page_size: 20, total_count: 45 })
      }),
      http.get(`${C}/bulk-verify`, () => HttpResponse.json({ items: [], next_cursor: null, can_view_all: false })),
    )
    const u = userEvent.setup()
    renderWithClient(<CrossReviewClient />)
    expect(await screen.findByTestId("phan-trang-cheo")).toHaveTextContent("Trang 1/3")
    await u.click(screen.getByRole("button", { name: "Trang sau" }))
    await waitFor(() => expect(trangHoi.at(-1)).toEqual({ page: "2", page_size: "20" }))
  })

  it("hàng đợi 403 ⇒ báo không có quyền gọn (bản 5 B7)", async () => {
    server.use(
      http.get(`${C}/eligibility`, () => HttpResponse.json(QUYEN)),
      http.get(`${C}/queue`, () => HttpResponse.json({ detail: "Forbidden" }, { status: 403 })),
      http.get(`${C}/bulk-verify`, () => HttpResponse.json({ items: [], next_cursor: null, can_view_all: false })),
    )
    renderWithClient(<CrossReviewClient />)
    expect(await screen.findByText("Bạn không có quyền xem hàng đợi duyệt chéo.")).toBeInTheDocument()
  })

  it("nút lô theo TỪNG quyền duyệt của hàng đợi", async () => {
    hangDoi([muc({ profile_id: 5 }), muc({ profile_id: 6, document_row_id: 103 })])
    renderWithClient(<CrossReviewClient />)
    expect(await screen.findByRole("button", { name: /Duyệt lô theo quyền #22/ })).toHaveTextContent("2 hồ sơ")
    expect(screen.queryByRole("button", { name: /Duyệt lô theo quyền #11/ })).toBeNull()
  })
})
