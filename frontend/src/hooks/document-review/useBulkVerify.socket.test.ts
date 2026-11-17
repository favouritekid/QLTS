/**
 * Bản 6 C2.3 — `onBulkVerifyFinished` (sự kiện socket `bulk_verify_finished {batch_id}`): làm mới danh sách hồ sơ, bộ
 * đếm, danh sách lô, trang lô đang mở, và chi tiết ĐÚNG các hồ sơ thuộc lô (profile_id lấy từ GET lô; 403 / 404 ở
 * đường Quản lý ⇒ thử đường chéo). CHỈ đọc — không gửi lệnh nào (không POST). Payload sai dạng ⇒ bỏ qua.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { waitFor } from "@testing-library/react"
import { QueryClient } from "@tanstack/react-query"
import { http, HttpResponse } from "msw"

import { server } from "@/test/mocks/server"
import { admissionsKeys } from "@/hooks/admissions/useAdmissions"

import { bulkVerifyKeys, onBulkVerifyFinished } from "./useBulkVerify"

const API = "http://localhost:8000"
const B1 = "3f2b8c1e-5d4a-4c3b-9a1e-0b2c3d4e5f60"

function lo(profileIds: number[]) {
  return {
    batch_id: B1,
    status: "completed",
    created_at: "2026-11-18T08:00:00Z",
    started_at: "2026-11-18T08:01:00Z",
    finished_at: "2026-11-18T08:01:05Z",
    finalized_at: null,
    finalized_by_user_id: null,
    finalize_reason: null,
    counts: { profiles: profileIds.length, recorded: profileIds.length, error: 0, not_processed: 0, pending: 0 },
    items: profileIds.map((p, i) => ({
      profile_id: p,
      document_row_id: 100 + i,
      document_type_code: "cccd",
      result: "recorded",
      reason_code: null,
      message: null,
    })),
    can_execute: false,
    can_finalize: false,
    finalize_requires_reason: false,
  }
}

let post = 0
const demPost = ({ request }: { request: Request }) => {
  if (request.method !== "GET") post++
}

beforeEach(() => {
  post = 0
  server.events.on("request:start", demPost)
})
afterEach(() => {
  server.events.removeListener("request:start", demPost)
  server.resetHandlers()
  vi.restoreAllMocks()
})

function khoaDaLamMoi(spy: { mock: { calls: unknown[][] } }): string[] {
  return spy.mock.calls.map((c) => {
    const a = c[0]
    return JSON.stringify(a && typeof a === "object" && "queryKey" in a ? a.queryKey : null)
  })
}

describe("onBulkVerifyFinished", () => {
  it("làm mới danh sách, bộ đếm, danh sách lô, trang lô, và chi tiết ĐÚNG các hồ sơ thuộc lô; không gửi lệnh nào", async () => {
    server.use(http.get(`${API}/api/admissions/documents/bulk-verify/${B1}`, () => HttpResponse.json(lo([5, 6]))))
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, "invalidateQueries")
    await onBulkVerifyFinished(qc, { batch_id: B1 })
    const k = khoaDaLamMoi(spy)
    for (const can of [
      admissionsKeys.lists(),
      [...admissionsKeys.all, "status-counts"],
      bulkVerifyKeys.lists("batch"),
      bulkVerifyKeys.batch("batch", B1),
      bulkVerifyKeys.batch("cross", B1),
      admissionsKeys.detail(5),
      admissionsKeys.detail(6),
    ]) {
      expect(k, JSON.stringify(can)).toContain(JSON.stringify(can))
    }
    expect(k).not.toContain(JSON.stringify(admissionsKeys.detail(7)))
    expect(post).toBe(0)
  })

  it("đường Quản lý 403 ⇒ đọc lô qua đường chéo, vẫn làm mới chi tiết hồ sơ của lô", async () => {
    server.use(
      http.get(`${API}/api/admissions/documents/bulk-verify/${B1}`, () =>
        HttpResponse.json({ detail: "Forbidden" }, { status: 403 }),
      ),
      http.get(`${API}/api/admissions/cross-review/bulk-verify/${B1}`, () => HttpResponse.json(lo([8]))),
    )
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, "invalidateQueries")
    await onBulkVerifyFinished(qc, { batch_id: B1 })
    await waitFor(() => expect(khoaDaLamMoi(spy)).toContain(JSON.stringify(admissionsKeys.detail(8))))
    expect(post).toBe(0)
  })

  it("payload sai dạng ⇒ bỏ qua, không làm mới gì", async () => {
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, "invalidateQueries")
    await onBulkVerifyFinished(qc, { batch_id: "12,13" })
    await onBulkVerifyFinished(qc, null)
    expect(spy).not.toHaveBeenCalled()
  })
})
