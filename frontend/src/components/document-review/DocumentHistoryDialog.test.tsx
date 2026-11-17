/**
 * GĐ1b K2 — hộp Lịch sử giấy: hiện thao tác theo nhãn tiếng Việt, đường gọi (lô / chéo), cam kết; 404 ⇒ "không xem
 * được"; tệp bằng chứng mất ⇒ nhãn; tải bằng chứng 410 ⇒ báo + làm mới lịch sử.
 */
import { afterEach, describe, expect, it, vi } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { server } from "@/test/mocks/server"

import { DocumentHistoryDialog } from "./DocumentHistoryDialog"
import { API, B1, renderWithClient } from "./test-helpers"

const URL_H = `${API}/api/admissions/5/documents/11/history`

const LICH_SU = {
  document_row_id: 11,
  document_type_code: "cccd",
  status: "verified",
  row_version: 4,
  entries: [
    {
      id: 1,
      action: "paper_submitted",
      at: "2026-11-16T01:00:00Z",
      actor_user_id: 3,
      actor_name: "Cán bộ B",
      old_status: "missing",
      new_status: "paper_submitted",
      via: null,
      batch_id: null,
      grant_id: null,
      reason: null,
      declared_format: "original",
      verified_format: null,
      unknown_submitter_ack: null,
      file_sha256: null,
    },
    {
      id: 2,
      action: "verified",
      at: "2026-11-17T01:00:00Z",
      actor_user_id: 2,
      actor_name: "Quản lý A",
      old_status: "paper_submitted",
      new_status: "verified",
      via: "batch",
      batch_id: B1,
      grant_id: null,
      reason: null,
      declared_format: "original",
      verified_format: "original",
      unknown_submitter_ack: false,
      file_sha256: null,
    },
  ],
  evidence_files: [
    { id: 7, verification_audit_id: 2, verified_at: "2026-11-17T01:00:00Z", verified_by_user_id: 2, sha256: "ab".repeat(32), file_missing: false },
    { id: 8, verification_audit_id: 3, verified_at: "2026-11-17T02:00:00Z", verified_by_user_id: 2, sha256: null, file_missing: true },
  ],
}

afterEach(() => {
  server.resetHandlers()
  vi.restoreAllMocks()
})

describe("DocumentHistoryDialog", () => {
  it("hiện thao tác, đường gọi Lô, mã lô; tệp mất có nhãn", async () => {
    server.use(http.get(URL_H, () => HttpResponse.json(LICH_SU)))
    renderWithClient(<DocumentHistoryDialog profileId={5} documentRowId={11} label="CCCD" open onOpenChange={vi.fn()} />)
    const ds = await screen.findByTestId("lich-su-giay")
    expect(ds).toHaveTextContent("Ghi nhận bản giấy")
    expect(ds).toHaveTextContent("Duyệt")
    expect(ds).toHaveTextContent("Lô")
    expect(ds).toHaveTextContent(B1)
    expect(screen.getByTestId("tep-bang-chung")).toHaveTextContent("Tệp không còn")
  })

  it("404 ⇒ 'Không xem được lịch sử giấy này.'", async () => {
    server.use(http.get(URL_H, () => HttpResponse.json({ detail: "Not found" }, { status: 404 })))
    renderWithClient(<DocumentHistoryDialog profileId={5} documentRowId={11} label="CCCD" open onOpenChange={vi.fn()} />)
    expect(await screen.findByRole("alert")).toHaveTextContent("Không xem được lịch sử giấy này.")
  })

  it("tải bằng chứng 410 ⇒ báo tệp không còn + hỏi lại lịch sử", async () => {
    let soLanGet = 0
    server.use(
      http.get(URL_H, () => {
        soLanGet++
        return HttpResponse.json(LICH_SU)
      }),
      http.get(`${API}/api/admissions/5/documents/11/evidence/7/download`, () =>
        HttpResponse.json({ error_code: "EVIDENCE_FILE_MISSING", detail: "x" }, { status: 410 }),
      ),
    )
    const u = userEvent.setup()
    renderWithClient(<DocumentHistoryDialog profileId={5} documentRowId={11} label="CCCD" open onOpenChange={vi.fn()} />)
    await u.click(await screen.findByRole("button", { name: "Tải tệp" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("không còn trên máy chủ")
    await waitFor(() => expect(soLanGet).toBeGreaterThanOrEqual(2))
  })
})
