/**
 * GĐ2-C C2 — ô chọn của Ban thư ký: hiện ĐÚNG các loại máy chủ cho phép (`applicable_kinds`), câu nhắc cờ "đang ngừng", thân ghi
 * đúng hợp đồng (mã băm dòng đang hiện + lựa chọn hiệu lực đang hiện), lý do bắt buộc với "Loại khỏi lần này" / "Chờ bổ sung"
 * (owner C6), câu báo theo `reason_code` của máy chủ (409 cũ / đã đổi), lựa chọn hiện tại + nhãn "đã cũ". Dữ liệu giả.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { API, renderWithClient } from "@/components/document-review/test-helpers"
import { server } from "@/test/mocks/server"
import type { Selection, SelectionRowInput } from "@/lib/zod/review-selections"

import { ReviewSelectionPicker } from "./ReviewSelectionPicker"

const SID = 7
const PID = 4102
const P = `${API}/api/admission-config/review-sessions/${SID}/selections/${PID}`
const BAM = "2".repeat(64)

const DONG_DANG_NGUNG: SelectionRowInput = {
  profile_id: PID,
  row_hash: BAM,
  flags: ["offering_inactive"],
  applicable_kinds: [
    "admit_over_major_quota",
    "consider_next_choice",
    "defer_supplement",
    "admit_without_ethnic_bonus",
    "exclude_this_session",
    "keep_despite_inactive",
  ],
}

const LUA_CHON: Selection = {
  id: 55,
  session_id: SID,
  profile_id: PID,
  kind: "admit_over_major_quota",
  choice_id: 102,
  based_on_run_id: 9,
  based_on_row_hash: BAM,
  decided_by_user_id: 3,
  decided_by_username: "thuky01",
  decided_by_full_name: "Thư Ký Một",
  decided_at: "2026-11-22T02:00:00Z",
  note: null,
  supersedes_id: null,
  is_stale: false,
}

let than: unknown[] = []
beforeEach(() => {
  than = []
})
afterEach(() => server.resetHandlers())

function ghiDuoc() {
  return http.put(P, async ({ request }) => {
    const b = (await request.json()) as { kind: string; note?: string | null; supersedes_id: number | null }
    than.push(b)
    return HttpResponse.json({ ...LUA_CHON, id: 56, kind: b.kind, note: b.note ?? null, supersedes_id: b.supersedes_id })
  })
}

describe("ReviewSelectionPicker", () => {
  it("cờ đang ngừng ⇒ hiện câu nhắc; chỉ hiện đúng các loại máy chủ cho phép", () => {
    renderWithClient(
      <ReviewSelectionPicker
        sessionId={SID}
        row={{ ...DONG_DANG_NGUNG, applicable_kinds: ["defer_supplement", "exclude_this_session"] }}
        current={null}
      />,
    )
    expect(screen.getByTestId("canh-bao-dang-ngung")).toHaveTextContent(
      'Ngành hoặc loại hình của nguyện vọng này đang ngừng — Ban thư ký phải chọn "Vẫn giữ" hoặc "Loại khỏi lần này".',
    )
    expect(screen.getAllByRole("radio").map((r) => r.getAttribute("value"))).toEqual([
      "defer_supplement",
      "exclude_this_session",
    ])
  })

  it("không cờ đang ngừng ⇒ không câu nhắc", () => {
    renderWithClient(
      <ReviewSelectionPicker sessionId={SID} row={{ ...DONG_DANG_NGUNG, flags: [] }} current={null} />,
    )
    expect(screen.queryByTestId("canh-bao-dang-ngung")).toBeNull()
  })

  it("'Vẫn giữ' ⇒ thân đúng hợp đồng: mã băm dòng đang hiện, supersedes_id null, không lý do", async () => {
    server.use(ghiDuoc())
    const u = userEvent.setup()
    renderWithClient(<ReviewSelectionPicker sessionId={SID} row={DONG_DANG_NGUNG} current={null} />)
    await u.click(screen.getByLabelText("Vẫn giữ"))
    await u.click(screen.getByRole("button", { name: "Ghi lựa chọn" }))
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ kind: "keep_despite_inactive", based_on_row_hash: BAM, supersedes_id: null, note: null })
  })

  it("'Loại khỏi lần này' bắt buộc lý do: nút khoá khi trống / chỉ khoảng trắng; có lý do ⇒ gửi lý do đã cắt", async () => {
    server.use(ghiDuoc())
    const u = userEvent.setup()
    renderWithClient(<ReviewSelectionPicker sessionId={SID} row={DONG_DANG_NGUNG} current={null} />)
    await u.click(screen.getByLabelText("Loại khỏi lần này"))
    const nut = screen.getByRole("button", { name: "Ghi lựa chọn" })
    expect(nut).toBeDisabled()
    expect(screen.getByLabelText("Lý do (bắt buộc)")).toBeInTheDocument()
    await u.type(screen.getByLabelText("Lý do (bắt buộc)"), "   ")
    expect(nut).toBeDisabled()
    await u.type(screen.getByLabelText("Lý do (bắt buộc)"), "Ngành ngừng tuyển  ")
    expect(nut).toBeEnabled()
    await u.click(nut)
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toMatchObject({ kind: "exclude_this_session", note: "Ngành ngừng tuyển" })
  })

  it("'Chờ bổ sung' cũng bắt buộc lý do", async () => {
    const u = userEvent.setup()
    renderWithClient(<ReviewSelectionPicker sessionId={SID} row={DONG_DANG_NGUNG} current={null} />)
    await u.click(screen.getByLabelText("Chờ bổ sung"))
    expect(screen.getByRole("button", { name: "Ghi lựa chọn" })).toBeDisabled()
  })

  it("đổi lựa chọn ⇒ supersedes_id = lựa chọn hiệu lực đang hiện", async () => {
    server.use(ghiDuoc())
    const u = userEvent.setup()
    renderWithClient(<ReviewSelectionPicker sessionId={SID} row={DONG_DANG_NGUNG} current={LUA_CHON} />)
    expect(screen.getByTestId("lua-chon-hien-tai")).toHaveTextContent("Đang chọn: Trúng vượt chỉ tiêu ngành")
    await u.click(screen.getByLabelText("Xét nguyện vọng kế"))
    await u.click(screen.getByRole("button", { name: "Đổi lựa chọn" }))
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toMatchObject({ kind: "consider_next_choice", supersedes_id: 55 })
  })

  it("lựa chọn hiện tại đã cũ ⇒ nhãn 'Đã cũ'", () => {
    renderWithClient(
      <ReviewSelectionPicker sessionId={SID} row={DONG_DANG_NGUNG} current={{ ...LUA_CHON, is_stale: true }} />,
    )
    expect(screen.getByTestId("lua-chon-hien-tai")).toHaveTextContent(
      "Đã cũ — kết quả của hồ sơ đã đổi sau lần chọn này",
    )
  })

  it.each([
    ["selection_stale", "SELECTION_STALE", "Kết quả của hồ sơ này đã đổi sau khi bạn mở (có lượt kiểm hồ sơ mới) — tải lại rồi chọn lại."],
    ["selection_changed", "SELECTION_CHANGED", "Lựa chọn của hồ sơ này vừa được người khác đổi — tải lại rồi chọn lại."],
  ])("409 %s ⇒ câu báo theo reason_code", async (reasonCode, errorCode, cau) => {
    server.use(
      http.put(P, () =>
        HttpResponse.json({ detail: "x", error_code: errorCode, reason_code: reasonCode }, { status: 409 }),
      ),
    )
    const u = userEvent.setup()
    renderWithClient(<ReviewSelectionPicker sessionId={SID} row={DONG_DANG_NGUNG} current={null} />)
    await u.click(screen.getByLabelText("Xét nguyện vọng kế"))
    await u.click(screen.getByRole("button", { name: "Ghi lựa chọn" }))
    expect(await screen.findByTestId("loi-lua-chon")).toHaveTextContent(cau)
  })

  it("404 không reason_code (mất quyền Thư ký) ⇒ câu chung, không lộ chuỗi máy chủ", async () => {
    server.use(
      http.put(P, () => HttpResponse.json({ detail: "Không tìm thấy", error_code: "RESOURCE_NOT_FOUND" }, { status: 404 })),
    )
    const u = userEvent.setup()
    renderWithClient(<ReviewSelectionPicker sessionId={SID} row={DONG_DANG_NGUNG} current={null} />)
    await u.click(screen.getByLabelText("Xét nguyện vọng kế"))
    await u.click(screen.getByRole("button", { name: "Ghi lựa chọn" }))
    expect(await screen.findByTestId("loi-lua-chon")).toHaveTextContent(
      "Không tìm thấy (hoặc bạn không còn quyền Thư ký Hội đồng).",
    )
  })
})
