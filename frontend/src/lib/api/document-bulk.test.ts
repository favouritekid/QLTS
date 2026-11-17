/**
 * GĐ1b — API client lô (axios THẬT + MSW): đường dẫn hai tiền tố (lô / lô chéo), thân xem trước đúng một trong
 * bộ lọc / danh sách, thân execute CHỈ có câu xác nhận (không danh sách), danh sách lô theo con trỏ.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { http, HttpResponse } from "msw"

import { server } from "@/test/mocks/server"

import { executeBatch, finalizeBatch, listBatches, previewBulkVerify } from "./document-bulk"

const API = "http://localhost:8000"
const B1 = "3f2b8c1e-5d4a-4c3b-9a1e-0b2c3d4e5f60"
const PREVIEW = {
  batch_id: B1,
  expires_at: "2026-11-17T08:30:00Z",
  counts: { profiles: 1, documents: 1, required: 1, optional: 0 },
  items: [{ profile_id: 5, document_row_id: 11, document_type_code: "cccd", expected_row_version: 3, is_mandatory: true }],
  excluded: [],
}
const VIEW = {
  batch_id: B1,
  status: "completed",
  created_at: "2026-11-17T08:00:00Z",
  started_at: "2026-11-17T08:01:00Z",
  finished_at: "2026-11-17T08:01:05Z",
  finalized_at: null,
  finalized_by_user_id: null,
  finalize_reason: null,
  counts: { profiles: 1, recorded: 1, error: 0, not_processed: 0, pending: 0 },
  items: [{ profile_id: 5, document_row_id: 11, document_type_code: "cccd", result: "recorded", reason_code: null, message: null }],
  can_execute: false,
  can_finalize: false,
}

let than: unknown[] = []
let urls: string[] = []
beforeEach(() => {
  than = []
  urls = []
})
afterEach(() => server.resetHandlers())

describe("lô duyệt giấy — API", () => {
  it("xem trước theo bộ lọc: thân {filter, include_optional}, không profile_ids", async () => {
    server.use(
      http.post(`${API}/api/admissions/documents/bulk-verify/preview`, async ({ request }) => {
        than.push(await request.json())
        return HttpResponse.json(PREVIEW, { status: 201 })
      }),
    )
    const p = await previewBulkVerify({ mode: "batch" }, { kind: "filter", filter: { status: "submitted", academic_year: 2026 } }, true)
    expect(p.batch_id).toBe(B1)
    expect(than).toEqual([{ filter: { status: "submitted", academic_year: 2026 }, include_optional: true }])
  })

  it("lô chéo: tiền tố riêng + grant_id trong thân", async () => {
    server.use(
      http.post(`${API}/api/admissions/cross-review/bulk-verify/preview`, async ({ request }) => {
        than.push(await request.json())
        return HttpResponse.json(PREVIEW, { status: 201 })
      }),
    )
    await previewBulkVerify({ mode: "cross", grantId: 22 }, { kind: "profiles", profileIds: [5, 6] }, false)
    expect(than).toEqual([{ profile_ids: [5, 6], include_optional: false, grant_id: 22 }])
  })

  it("lô chéo thiếu quyền ⇒ ném TRƯỚC khi gửi", async () => {
    await expect(
      previewBulkVerify({ mode: "cross" }, { kind: "profiles", profileIds: [5] }, false),
    ).rejects.toThrow()
  })

  it("execute: thân CHỈ có confirmation_text", async () => {
    server.use(
      http.post(`${API}/api/admissions/documents/bulk-verify/${B1}/execute`, async ({ request }) => {
        than.push(await request.json())
        return HttpResponse.json(VIEW)
      }),
    )
    const v = await executeBatch({ mode: "batch" }, B1, "Tôi xác nhận")
    expect(v.status).toBe("completed")
    expect(than).toEqual([{ confirmation_text: "Tôi xác nhận" }])
  })

  it("finalize không lý do ⇒ thân {}; có lý do ⇒ {reason}", async () => {
    server.use(
      http.post(`${API}/api/admissions/documents/bulk-verify/${B1}/finalize`, async ({ request }) => {
        than.push(await request.json())
        return HttpResponse.json({ batch: { ...VIEW, status: "interrupted" }, finalized_now: true })
      }),
    )
    await finalizeBatch({ mode: "batch" }, B1)
    await finalizeBatch({ mode: "batch" }, B1, "  máy chủ khởi động lại  ")
    expect(than).toEqual([{}, { reason: "máy chủ khởi động lại" }])
  })

  it("danh sách: scope + limit 20 + cursor", async () => {
    server.use(
      http.get(`${API}/api/admissions/documents/bulk-verify`, ({ request }) => {
        urls.push(request.url)
        return HttpResponse.json({ items: [], next_cursor: null })
      }),
    )
    await listBatches({ mode: "batch" }, "mine")
    await listBatches({ mode: "batch" }, "all", "c2")
    const q = urls.map((u) => Object.fromEntries(new URL(u).searchParams))
    expect(q).toEqual([
      { scope: "mine", limit: "20" },
      { scope: "all", limit: "20", cursor: "c2" },
    ])
  })
})
