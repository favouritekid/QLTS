/**
 * GĐ2-F1 — soạn bảng chỉ tiêu: ô TRỐNG gửi `null` (KHÔNG BAO GIỜ 0); 0 chỉ khi gõ rõ; giữ phiên bản lúc mở; lỗi 422 ⇒ câu
 * nêu nhóm + ngành. Dữ liệu giả.
 */
import { afterEach, describe, expect, it, vi } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { QueryClientProvider } from "@tanstack/react-query"

import { API, renderWithClient } from "@/components/document-review/test-helpers"
import { server } from "@/test/mocks/server"
import type { DraftGroup } from "@/lib/quota-tables/draft"

import { QuotaTableEditor, type MemberOption } from "./QuotaTableEditor"

const P = `${API}/api/admission-config/quota-tables/2026`
const FP = "a".repeat(64)
const FP_MOI = "b".repeat(64)

const NHOM: DraftGroup[] = [
  {
    key: "nhom-7",
    code: "N1",
    name: "Nhóm thử",
    ceiling: "120",
    members: [
      { offering_academic_info_id: 11, label: "M1 — Ngành Một", quota: "" },
      { offering_academic_info_id: 12, label: "M2 — Ngành Hai", quota: "40" },
    ],
  },
]

const LUA_CHON: MemberOption[] = [
  { offering_academic_info_id: 13, label: "M3 — Ngành Ba", annual_admission_quota: null },
  { offering_academic_info_id: 14, label: "M4 — Ngành Bốn", annual_admission_quota: 25 },
]

const labelOf = (id: number) =>
  ({ 11: "M1 — Ngành Một", 12: "M2 — Ngành Hai", 13: "M3 — Ngành Ba", 14: "M4 — Ngành Bốn" })[id] ?? `Học vụ #${id}`

let than: Array<Record<string, unknown>> = []
function batPut(status = 200, body: Record<string, unknown> = {}) {
  than = []
  server.use(
    http.put(P, async ({ request }) => {
      than.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(
        status === 200
          ? { academic_year: 2026, status: "draft", version: 4, locked_by_user_id: null, locked_at: null, available_actions: ["edit", "lock"], groups: [] }
          : body,
        { status },
      )
    }),
  )
}

function ve(over: Partial<Parameters<typeof QuotaTableEditor>[0]> = {}) {
  const onSaved = vi.fn()
  renderWithClient(
    <QuotaTableEditor
      year={2026}
      version={3}
      quotaFingerprint={FP}
      initialGroups={NHOM}
      options={LUA_CHON}
      labelOf={labelOf}
      onCancel={vi.fn()}
      onSaved={onSaved}
      {...over}
    />,
  )
  return { onSaved }
}

const thanhVien = (t: Record<string, unknown>) =>
  (t.groups as Array<{ members: Array<{ offering_academic_info_id: number; annual_admission_quota: unknown }> }>)[0].members

afterEach(() => server.resetHandlers())

describe("QuotaTableEditor — trống ≠ 0", () => {
  it("ô chỉ tiêu đang trống, lưu nguyên ⇒ gửi null (không 0); ô có số giữ số; đúng phiên bản", async () => {
    batPut()
    const u = userEvent.setup()
    const { onSaved } = ve()
    expect(screen.getByTestId("o-trong-11")).toHaveTextContent("Trống — chưa nhập")
    await u.click(screen.getByTestId("luu-bang"))
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    expect(than[0].version).toBe(3)
    expect(than[0].quota_fingerprint).toBe(FP)
    expect(thanhVien(than[0])).toEqual([
      { offering_academic_info_id: 11, annual_admission_quota: null },
      { offering_academic_info_id: 12, annual_admission_quota: 40 },
    ])
  })

  it("xoá hết số trong ô ⇒ null; gõ rõ 0 ⇒ 0", async () => {
    batPut()
    const u = userEvent.setup()
    ve()
    await u.clear(screen.getByLabelText("Chỉ tiêu năm — M2 — Ngành Hai"))
    await u.type(screen.getByLabelText("Chỉ tiêu năm — M1 — Ngành Một"), "0")
    await u.click(screen.getByTestId("luu-bang"))
    await waitFor(() => expect(than).toHaveLength(1))
    expect(thanhVien(than[0])).toEqual([
      { offering_academic_info_id: 11, annual_admission_quota: 0 },
      { offering_academic_info_id: 12, annual_admission_quota: null },
    ])
  })

  it("nhóm mới chưa nhập trần ⇒ trần null (không 0)", async () => {
    batPut()
    const u = userEvent.setup()
    ve({ initialGroups: [], version: 0 })
    await u.click(screen.getByRole("button", { name: /Thêm nhóm ngành/ }))
    await u.type(screen.getByLabelText("Mã nhóm"), "N9")
    await u.type(screen.getByLabelText("Tên nhóm"), "Nhóm mới")
    await u.click(screen.getByTestId("luu-bang"))
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({
      version: 0,
      quota_fingerprint: FP,
      groups: [{ code: "N9", name: "Nhóm mới", ceiling: null, members: [] }],
    })
  })

  it("thêm ngành chưa có chỉ tiêu năm ⇒ ô trống ⇒ null; ngành đã có chỉ tiêu ⇒ điền đúng số máy chủ", async () => {
    batPut()
    const u = userEvent.setup()
    ve()
    const chon = screen.getByLabelText("Thêm ngành vào nhóm")
    await u.selectOptions(chon, "13")
    await u.selectOptions(screen.getByLabelText("Thêm ngành vào nhóm"), "14")
    await u.click(screen.getByTestId("luu-bang"))
    await waitFor(() => expect(than).toHaveLength(1))
    expect(thanhVien(than[0]).slice(2)).toEqual([
      { offering_academic_info_id: 13, annual_admission_quota: null },
      { offering_academic_info_id: 14, annual_admission_quota: 25 },
    ])
  })
})

describe("QuotaTableEditor — lỗi máy chủ", () => {
  it("422 ô chỉ tiêu trống ⇒ câu nêu nhóm + ngành, không gọi onSaved", async () => {
    batPut(422, {
      error_code: "VALIDATION_ERROR",
      errors: [{ loc: ["body", "groups", 0, "members", 0, "annual_admission_quota"], msg: "Input should be a valid integer" }],
    })
    const u = userEvent.setup()
    const { onSaved } = ve()
    await u.click(screen.getByTestId("luu-bang"))
    const loi = await screen.findByRole("alert")
    expect(loi).toHaveTextContent(/Nhóm N1 — M1 — Ngành Một: chỉ tiêu năm còn trống/)
    expect(onSaved).not.toHaveBeenCalled()
  })

  it("bảng được làm mới sau lỗi (phiên bản mới) ⇒ bấm Lưu lần nữa VẪN gửi phiên bản lúc mở (không đè bản chưa xem)", async () => {
    batPut(409, { reason_code: "quota_table_stale", error_code: "QUOTA_TABLE_STALE", current_version: 5, detail: "x" })
    const u = userEvent.setup()
    const props = {
      year: 2026, initialGroups: NHOM, options: LUA_CHON, labelOf, onCancel: vi.fn(), onSaved: vi.fn(),
    }
    const { queryClient, rerender } = renderWithClient(<QuotaTableEditor version={3} quotaFingerprint={FP} {...props} />)
    await u.click(screen.getByTestId("luu-bang"))
    await screen.findByRole("alert")
    rerender(
      <QueryClientProvider client={queryClient}>
        <QuotaTableEditor version={5} quotaFingerprint={FP} {...props} />
      </QueryClientProvider>,
    )
    await u.click(screen.getByTestId("luu-bang"))
    await waitFor(() => expect(than).toHaveLength(2))
    expect(than.map((t) => t.version)).toEqual([3, 3])
  })

  it("GĐ2-F1: dấu chỉ tiêu mới sau khi bảng làm mới ⇒ Lưu lần nữa VẪN gửi DẤU LÚC MỞ (không đè chỉ tiêu sửa ở trang khác)", async () => {
    batPut(409, { reason_code: "quota_table_stale", error_code: "QUOTA_TABLE_STALE", current_version: 3, detail: "x" })
    const u = userEvent.setup()
    const props = {
      year: 2026, version: 3, initialGroups: NHOM, options: LUA_CHON, labelOf, onCancel: vi.fn(), onSaved: vi.fn(),
    }
    const { queryClient, rerender } = renderWithClient(<QuotaTableEditor quotaFingerprint={FP} {...props} />)
    await u.click(screen.getByTestId("luu-bang"))
    await screen.findByRole("alert")
    rerender(
      <QueryClientProvider client={queryClient}>
        <QuotaTableEditor quotaFingerprint={FP_MOI} {...props} />
      </QueryClientProvider>,
    )
    await u.click(screen.getByTestId("luu-bang"))
    await waitFor(() => expect(than).toHaveLength(2))
    expect(than.map((t) => t.quota_fingerprint)).toEqual([FP, FP])
  })

  it("409 quota_table_stale ⇒ câu tải lại, giữ bản nháp", async () => {
    batPut(409, { reason_code: "quota_table_stale", error_code: "QUOTA_TABLE_STALE", current_version: 5, detail: "x" })
    const u = userEvent.setup()
    ve()
    await u.click(screen.getByTestId("luu-bang"))
    const loi = await screen.findByRole("alert")
    expect(loi).toHaveTextContent(/sửa ở nơi khác/)
    expect(screen.getByLabelText("Chỉ tiêu năm — M2 — Ngành Hai")).toHaveValue(40)
  })
})
