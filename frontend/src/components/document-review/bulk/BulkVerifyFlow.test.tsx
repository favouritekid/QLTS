/**
 * GĐ1b §5.2 / §5.3 / §5.9 — luồng lô:
 *  - xem trước ⇒ sessionStorage giữ ĐÚNG `batch_id` (một khoá), localStorage rỗng;
 *  - "Duyệt" gửi `execute` ĐÚNG MỘT LẦN; mất mạng / 504 / 409 BATCH_RUNNING ⇒ TRA lô bằng GET, KHÔNG gửi lại `execute`
 *    (kể cả sau khoảng chờ thử lại mặc định của React Query);
 *  - PREVIEW_EXPIRED / 404 ⇒ xem trước lại; 422 TOO_MANY_PROFILES ⇒ câu có số, không tạo lô;
 *  - kết quả tường minh: mục `version_changed` hiện câu §5.9.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { server } from "@/test/mocks/server"
import { LAST_BATCH_ID_KEY } from "@/lib/document-review/batch-session"
import { VERSION_CHANGED_MESSAGE } from "@/lib/document-review/messages"

import { API, B1, loGia, renderWithClient } from "../test-helpers"
import { BulkVerifyFlow } from "./BulkVerifyFlow"

const P = `${API}/api/admissions/documents/bulk-verify`
const PREVIEW = {
  batch_id: B1,
  expires_at: "2026-11-17T08:30:00Z",
  counts: { profiles: 2, documents: 3, required: 3, optional: 0 },
  items: [
    { profile_id: 5, document_row_id: 11, document_type_code: "cccd", expected_row_version: 3, is_mandatory: true },
    { profile_id: 5, document_row_id: 13, document_type_code: "anh_3x4", expected_row_version: 1, is_mandatory: true },
    { profile_id: 6, document_row_id: 12, document_type_code: "hoc_ba_thpt", expected_row_version: 2, is_mandatory: true },
  ],
  excluded: [
    { profile_id: 6, document_row_id: 14, document_type_code: "cccd", reason_code: "own_submission" },
    { profile_id: 6, document_row_id: 15, document_type_code: "giay_khai_sinh", reason_code: "missing_format" },
  ],
}

let soExecute = 0
let soGet = 0
let thanPreview: unknown[] = []
let thanExecute: unknown[] = []

function mayChu(execute: () => Response) {
  server.use(
    http.post(`${P}/preview`, async ({ request }) => {
      thanPreview.push(await request.json())
      return HttpResponse.json(PREVIEW, { status: 201 })
    }),
    http.post(`${P}/${B1}/execute`, async ({ request }) => {
      soExecute++
      thanExecute.push(await request.json())
      return execute()
    }),
    http.get(`${P}/${B1}`, () => {
      soGet++
      return HttpResponse.json(loGia({ status: "completed" }))
    }),
  )
}

async function xemTruocRoiDuyet() {
  const u = userEvent.setup()
  renderWithClient(
    <BulkVerifyFlow
      endpoint={{ mode: "batch" }}
      selection={{ kind: "filter", filter: { status: "submitted" } }}
      scopeLabel="các hồ sơ theo bộ lọc hiện tại"
    />,
  )
  await u.click(screen.getByRole("button", { name: "Xem trước" }))
  await screen.findByTestId("lo-xem-truoc")
  await u.click(screen.getByRole("checkbox"))
  await u.click(screen.getByRole("button", { name: "Duyệt 3 giấy" }))
  return u
}

beforeEach(() => {
  soExecute = 0
  soGet = 0
  thanPreview = []
  thanExecute = []
  sessionStorage.clear()
  localStorage.clear()
})
afterEach(() => server.resetHandlers())

describe("BulkVerifyFlow", () => {
  it("xem trước ⇒ sessionStorage chỉ giữ batch_id; localStorage rỗng; thân {filter, include_optional}", async () => {
    mayChu(() => HttpResponse.json(loGia()))
    const u = userEvent.setup()
    renderWithClient(
      <BulkVerifyFlow
        endpoint={{ mode: "batch" }}
        selection={{ kind: "filter", filter: { status: "submitted" } }}
        scopeLabel="x"
      />,
    )
    await u.click(screen.getByRole("button", { name: "Xem trước" }))
    expect(await screen.findByTestId("so-giay-se-duyet")).toHaveTextContent("3")
    expect(thanPreview).toEqual([{ filter: { status: "submitted" }, include_optional: false }])
    expect(sessionStorage.length).toBe(1)
    expect(sessionStorage.getItem(LAST_BATCH_ID_KEY)).toBe(B1)
    expect(localStorage.length).toBe(0)
    // giấy bị loại nêu lý do tiếng Việt, không mã
    const loai = screen.getByTestId("giay-bi-loai")
    expect(loai).toHaveTextContent("Chưa ghi hình thức lúc nhận")
    expect(loai).not.toHaveTextContent("missing_format")
    // chưa gửi execute
    expect(soExecute).toBe(0)
  })

  it("nút Duyệt khoá cho tới khi tích ô xác nhận; câu xác nhận mang số giấy máy chủ trả", async () => {
    mayChu(() => HttpResponse.json(loGia()))
    const u = userEvent.setup()
    renderWithClient(
      <BulkVerifyFlow endpoint={{ mode: "batch" }} selection={{ kind: "profiles", profileIds: [5, 6] }} scopeLabel="x" />,
    )
    await u.click(screen.getByRole("button", { name: "Xem trước" }))
    const nut = await screen.findByRole("button", { name: "Duyệt 3 giấy" })
    expect(nut).toBeDisabled()
    await u.click(screen.getByRole("checkbox"))
    await u.click(nut)
    await screen.findByTestId("ket-qua-lo")
    expect(thanExecute).toEqual([
      { confirmation_text: "Tôi xác nhận đã đối chiếu giấy thật của 3 giấy này. Phần mềm chỉ ghi lại kết quả kiểm của tôi." },
    ])
  })

  it("200 ⇒ kết quả bốn nhóm; mục version_changed hiện câu §5.9", async () => {
    mayChu(() => HttpResponse.json(loGia()))
    await xemTruocRoiDuyet()
    const kq = await screen.findByTestId("ket-qua-lo")
    expect(screen.getByTestId("dem-recorded")).toHaveTextContent("1")
    expect(screen.getByTestId("dem-error")).toHaveTextContent("1")
    expect(kq).toHaveTextContent(VERSION_CHANGED_MESSAGE)
    expect(soExecute).toBe(1)
  })

  it("mất mạng khi chạy ⇒ 'Chưa rõ kết quả', TRA lô bằng GET, execute ĐÚNG MỘT LẦN (kể cả sau 1,5 s)", async () => {
    mayChu(() => HttpResponse.error())
    await xemTruocRoiDuyet()
    await waitFor(() => expect(soExecute).toBe(1))
    // quá khoảng chờ thử lại đầu tiên của React Query (1 s) — có thử lại thì đếm thành 2
    await new Promise((r) => setTimeout(r, 1500))
    expect(soExecute).toBe(1)
    expect(await screen.findByRole("status")).toHaveTextContent("Chưa rõ kết quả")
    await waitFor(() => expect(soGet).toBeGreaterThanOrEqual(1))
    expect(soExecute).toBe(1)
    expect(screen.queryByRole("button", { name: /Duyệt 3 giấy/ })).toBeNull()
  }, 8000)

  it("504 ⇒ tra lô, không gửi lại", async () => {
    mayChu(() => new HttpResponse("Gateway Timeout", { status: 504 }))
    await xemTruocRoiDuyet()
    await waitFor(() => expect(soGet).toBeGreaterThanOrEqual(1))
    expect(soExecute).toBe(1)
  })

  it("409 BATCH_RUNNING ⇒ tra lô (không coi là lỗi), không gửi lại", async () => {
    mayChu(() => HttpResponse.json({ error_code: "BATCH_RUNNING", detail: "x" }, { status: 409 }))
    await xemTruocRoiDuyet()
    expect(await screen.findByRole("status")).toHaveTextContent("đang tra kết quả")
    await waitFor(() => expect(soGet).toBeGreaterThanOrEqual(1))
    expect(soExecute).toBe(1)
  })

  it("409 PREVIEW_EXPIRED ⇒ 'Bản xem trước đã hết hạn — xem trước lại' + nút Xem trước lại, KHÔNG tra lô", async () => {
    mayChu(() => HttpResponse.json({ error_code: "PREVIEW_EXPIRED", detail: "x" }, { status: 409 }))
    await xemTruocRoiDuyet()
    expect(await screen.findByText("Bản xem trước đã hết hạn — xem trước lại")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Xem trước lại" })).toBeInTheDocument()
    expect(soGet).toBe(0)
  })

  it("404 ⇒ 'Bản xem trước không còn — xem trước lại'", async () => {
    mayChu(() => HttpResponse.json({ detail: "Not found" }, { status: 404 }))
    await xemTruocRoiDuyet()
    expect(await screen.findByText("Bản xem trước không còn — xem trước lại")).toBeInTheDocument()
    expect(soExecute).toBe(1)
  })

  it("xem trước 422 TOO_MANY_PROFILES ⇒ câu có số; không lưu batch_id", async () => {
    server.use(
      http.post(`${P}/preview`, () =>
        HttpResponse.json({ error_code: "TOO_MANY_PROFILES", detail: "x", profile_count: 140, limit: 100 }, { status: 422 }),
      ),
    )
    const u = userEvent.setup()
    renderWithClient(
      <BulkVerifyFlow endpoint={{ mode: "batch" }} selection={{ kind: "filter", filter: {} }} scopeLabel="x" />,
    )
    await u.click(screen.getByRole("button", { name: "Xem trước" }))
    const a = await screen.findByRole("alert")
    expect(a).toHaveTextContent("140")
    expect(a).toHaveTextContent("100")
    expect(sessionStorage.length).toBe(0)
  })
})
