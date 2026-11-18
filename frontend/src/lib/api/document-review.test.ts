/**
 * GĐ1b — API client nút lẻ + lịch sử qua axios THẬT + MSW: thân gửi đúng `expected_row_version` / lý do / cam kết,
 * phản hồi qua Zod (thiếu `row_version` ⇒ ném), 409 giữ nguyên `reason_code`.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { http, HttpResponse } from "msw"

import { server } from "@/test/mocks/server"
import { describeDocumentActionError } from "@/lib/document-review/messages"

import {
  getDocumentHistory,
  rejectDocumentGd1b,
  resetDocumentGd1b,
  verifyDocumentGd1b,
} from "./document-review"

const API = "http://localhost:8000"
let than: unknown[] = []
let urls: string[] = []

beforeEach(() => {
  than = []
  urls = []
})
afterEach(() => server.resetHandlers())

describe("nút lẻ GĐ1b", () => {
  it("verify gửi format + expected_row_version + unknown_submitter_ack, không reason khi không cam kết", async () => {
    server.use(
      http.patch(`${API}/api/admissions/5/documents/hoc_ba_thpt/verify-format`, async ({ request }) => {
        urls.push(request.url)
        than.push(await request.json())
        return HttpResponse.json({ id: 5, status: "submitted" })
      }),
    )
    const r = await verifyDocumentGd1b(5, "hoc_ba_thpt", {
      format: "original",
      expected_row_version: 3,
      unknown_submitter_ack: false,
    })
    expect(r.id).toBe(5)
    expect(than).toEqual([{ format: "original", expected_row_version: 3, unknown_submitter_ack: false }])
    expect(urls[0]).not.toContain("?")
  })

  it("reset gửi lý do trong THÂN (không URL) + expected_row_version", async () => {
    server.use(
      http.post(`${API}/api/admissions/5/documents/cccd/reset`, async ({ request }) => {
        urls.push(request.url)
        than.push(await request.json())
        return HttpResponse.json({ id: 5 })
      }),
    )
    await resetDocumentGd1b(5, "cccd", { reason: "nhầm giấy", expected_row_version: 7, unknown_submitter_ack: true })
    expect(than).toEqual([{ reason: "nhầm giấy", expected_row_version: 7, unknown_submitter_ack: true }])
    expect(urls[0]).toBe(`${API}/api/admissions/5/documents/cccd/reset`)
  })

  it("reject: phản hồi thiếu row_version ⇒ ném (Zod)", async () => {
    server.use(
      http.post(`${API}/api/admissions/5/documents/cccd/reject`, () =>
        HttpResponse.json({ code: "cccd", status: "rejected", rejection_reason: "mờ", rejected_at: null, rejected_by_id: 1, document_row_id: 11 }),
      ),
    )
    await expect(
      rejectDocumentGd1b(5, "cccd", { reason: "mờ", expected_row_version: 2, unknown_submitter_ack: false }),
    ).rejects.toThrow()
  })

  it("409 VERSION_CHANGED ⇒ phân loại version_changed", async () => {
    server.use(
      http.patch(`${API}/api/admissions/5/documents/cccd/verify-format`, () =>
        HttpResponse.json(
          { reason_code: "version_changed", error_code: "VERSION_CHANGED", detail: "x" },
          { status: 409 },
        ),
      ),
    )
    const e = await verifyDocumentGd1b(5, "cccd", {
      format: "photo",
      expected_row_version: 2,
      unknown_submitter_ack: false,
    }).catch((x: unknown) => x)
    expect(describeDocumentActionError(e).kind).toBe("version_changed")
  })

  it("thân sai dạng (thiếu expected_row_version) ⇒ ném TRƯỚC khi gửi", async () => {
    let goi = 0
    server.use(
      http.post(`${API}/api/admissions/5/documents/cccd/reset`, () => {
        goi++
        return HttpResponse.json({ id: 5 })
      }),
    )
    await expect(
      // @ts-expect-error — cố ý thiếu expected_row_version
      resetDocumentGd1b(5, "cccd", { reason: "x", unknown_submitter_ack: false }),
    ).rejects.toThrow()
    expect(goi).toBe(0)
  })
})

describe("lịch sử giấy", () => {
  it("GET theo document_row_id, parse đủ", async () => {
    server.use(
      http.get(`${API}/api/admissions/5/documents/11/history`, () =>
        HttpResponse.json({
          document_row_id: 11,
          document_type_code: "cccd",
          status: "verified",
          row_version: 4,
          entries: [
            {
              id: 1,
              action: "verified",
              at: "2026-11-17T08:00:00Z",
              actor_user_id: 2,
              actor_name: "Quản lý A",
              old_status: "paper_submitted",
              new_status: "verified",
              via: "batch",
              batch_id: "3f2b8c1e-5d4a-4c3b-9a1e-0b2c3d4e5f60",
              grant_id: null,
              reason: null,
              declared_format: "original",
              verified_format: "original",
              unknown_submitter_ack: false,
              file_sha256: null,
            },
          ],
          evidence_files: [],
        }),
      ),
    )
    const h = await getDocumentHistory(5, 11)
    expect(h.entries[0].via).toBe("batch")
    expect(h.row_version).toBe(4)
  })
})
