/**
 * GĐ2-F1 — xem bảng chỉ tiêu: nút Sửa / Khoá / Mở khoá CHỈ theo `available_actions` của máy chủ (không theo `status`);
 * ô chỉ tiêu `null` hiện "Trống — chưa nhập" (≠ 0); mở khoá BẮT BUỘC lý do (khoảng trắng không tính) và gửi lý do đã cắt;
 * lỗi khoá ⇒ câu theo `reason_code`. Dữ liệu giả.
 */
import { afterEach, describe, expect, it, vi } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { QueryClientProvider } from "@tanstack/react-query"

import { API, renderWithClient } from "@/components/document-review/test-helpers"
import { server } from "@/test/mocks/server"
import type { QuotaTableOut } from "@/lib/zod/quota-tables"

import { QuotaTableView } from "./QuotaTableView"

const P = `${API}/api/admission-config/quota-tables/2026`
const FP = "a".repeat(64)

function bang(over: Partial<QuotaTableOut> = {}): QuotaTableOut {
  return {
    academic_year: 2026,
    status: "draft",
    version: 3,
    locked_by_user_id: null,
    locked_at: null,
    available_actions: ["edit", "lock"],
    quota_fingerprint: FP,
    groups: [
      {
        id: 7,
        code: "N1",
        name: "Nhóm thử",
        ceiling: 120,
        usage: { publish_count: 2, approved_count: 3, used: 3 },
        members: [
          { offering_academic_info_id: 11, offering_id: 1, major_code: "M1", major_name: "Ngành Một", offering_type: null, annual_admission_quota: null },
          { offering_academic_info_id: 12, offering_id: 2, major_code: "M2", major_name: "Ngành Hai", offering_type: null, annual_admission_quota: 0 },
        ],
      },
    ],
    ...over,
  }
}

const labelOf = (id: number) => (id === 11 ? "M1 — Ngành Một" : id === 12 ? "M2 — Ngành Hai" : `Học vụ #${id}`)

function ve(t: QuotaTableOut, onEdit = vi.fn()) {
  return { ...renderWithClient(<QuotaTableView table={t} labelOf={labelOf} onEdit={onEdit} />), onEdit }
}

afterEach(() => server.resetHandlers())

describe("QuotaTableView — nút theo available_actions", () => {
  it("['edit','lock'] ⇒ Sửa + Khoá, KHÔNG Mở khoá", () => {
    ve(bang())
    expect(screen.getByTestId("nut-sua-bang")).toBeInTheDocument()
    expect(screen.getByTestId("nut-khoa-bang")).toBeInTheDocument()
    expect(screen.queryByTestId("nut-mo-khoa-bang")).toBeNull()
  })

  it("['unlock'] ⇒ chỉ Mở khoá", () => {
    ve(bang({ status: "locked", available_actions: ["unlock"] }))
    expect(screen.getByTestId("nut-mo-khoa-bang")).toBeInTheDocument()
    expect(screen.queryByTestId("nut-sua-bang")).toBeNull()
    expect(screen.queryByTestId("nut-khoa-bang")).toBeNull()
  })

  it("bảng 'locked' mà máy chủ KHÔNG cho mở khoá (available_actions rỗng) ⇒ không nút nào (không suy từ status)", () => {
    ve(bang({ status: "locked", available_actions: [] }))
    expect(screen.queryByTestId("nut-mo-khoa-bang")).toBeNull()
    expect(screen.queryByTestId("nut-sua-bang")).toBeNull()
    expect(screen.queryByTestId("nut-khoa-bang")).toBeNull()
  })

  it("bảng 'draft' mà máy chủ không cho sửa / khoá ⇒ không nút", () => {
    ve(bang({ status: "draft", available_actions: [] }))
    expect(screen.queryByTestId("nut-sua-bang")).toBeNull()
    expect(screen.queryByTestId("nut-khoa-bang")).toBeNull()
  })
})

describe("QuotaTableView — hiển thị", () => {
  it("chỉ tiêu null ⇒ 'Trống — chưa nhập'; chỉ tiêu 0 ⇒ '0'", () => {
    ve(bang())
    expect(screen.getByTestId("chi-tieu-11")).toHaveTextContent("Trống — chưa nhập")
    expect(screen.getByTestId("chi-tieu-12")).toHaveTextContent(/^0$/)
  })

  it("hiện số đã dùng (tham khảo) của máy chủ, không tự tính", () => {
    ve(bang())
    expect(screen.getByTestId("da-dung-N1")).toHaveTextContent("3")
    expect(screen.getByTestId("nhom-N1")).toHaveTextContent(/theo công bố 2/)
  })
})

describe("QuotaTableView — mở khoá bắt buộc lý do", () => {
  it("lý do trống / toàn khoảng trắng ⇒ nút Mở khoá khoá; có lý do ⇒ gửi {version, reason đã cắt}", async () => {
    const than: unknown[] = []
    server.use(
      http.post(`${P}/unlock`, async ({ request }) => {
        than.push(await request.json())
        return HttpResponse.json(bang({ status: "draft", version: 5 }))
      }),
    )
    const u = userEvent.setup()
    ve(bang({ status: "locked", version: 4, available_actions: ["unlock"] }))
    await u.click(screen.getByTestId("nut-mo-khoa-bang"))
    const nut = screen.getByTestId("xac-nhan-mo-khoa-bang")
    expect(nut).toBeDisabled()
    await u.type(screen.getByLabelText(/Lý do mở khoá \(bắt buộc\)/), "    ")
    expect(nut).toBeDisabled()
    expect(than).toEqual([])
    await u.type(screen.getByLabelText(/Lý do mở khoá \(bắt buộc\)/), " Có văn bản điều chỉnh ")
    expect(nut).toBeEnabled()
    await u.click(nut)
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ version: 4, reason: "Có văn bản điều chỉnh" })
  })
})

describe("QuotaTableView — khoá bảng", () => {
  it("GĐ2-F1: bảng làm mới (dấu chỉ tiêu mới) khi hộp khoá đang mở ⇒ vẫn gửi DẤU LÚC MỞ hộp", async () => {
    const than: unknown[] = []
    server.use(
      http.post(`${P}/lock`, async ({ request }) => {
        than.push(await request.json())
        return HttpResponse.json(
          { reason_code: "quota_table_stale", error_code: "QUOTA_TABLE_STALE", current_version: 3, detail: "x" },
          { status: 409 },
        )
      }),
    )
    const u = userEvent.setup()
    const { queryClient, rerender } = renderWithClient(<QuotaTableView table={bang()} labelOf={labelOf} onEdit={vi.fn()} />)
    await u.click(screen.getByTestId("nut-khoa-bang"))
    await u.click(screen.getByTestId("xac-nhan-khoa-bang"))
    await screen.findByRole("alert")
    rerender(
      <QueryClientProvider client={queryClient}>
        <QuotaTableView table={bang({ quota_fingerprint: "b".repeat(64) })} labelOf={labelOf} onEdit={vi.fn()} />
      </QueryClientProvider>,
    )
    await u.click(screen.getByTestId("xac-nhan-khoa-bang"))
    await waitFor(() => expect(than).toHaveLength(2))
    expect(than).toEqual([
      { version: 3, quota_fingerprint: FP },
      { version: 3, quota_fingerprint: FP },
    ])
  })


  it("gửi {version}; 409 thiếu chỉ tiêu ⇒ câu nêu TÊN ngành, giữ hộp", async () => {
    const than: unknown[] = []
    server.use(
      http.post(`${P}/lock`, async ({ request }) => {
        than.push(await request.json())
        return HttpResponse.json(
          { reason_code: "quota_table_member_quota_missing", error_code: "QUOTA_TABLE_MEMBER_QUOTA_MISSING", offering_academic_info_ids: [11], detail: "x" },
          { status: 409 },
        )
      }),
    )
    const u = userEvent.setup()
    ve(bang())
    await u.click(screen.getByTestId("nut-khoa-bang"))
    await u.click(screen.getByTestId("xac-nhan-khoa-bang"))
    const loi = await screen.findByRole("alert")
    expect(than).toEqual([{ version: 3, quota_fingerprint: FP }])
    expect(loi).toHaveTextContent("M1 — Ngành Một")
    expect(loi).toHaveTextContent(/chưa có chỉ tiêu năm/)
    expect(loi.textContent).not.toMatch(/quota_table_member_quota_missing/i)
    expect(screen.getByTestId("hop-khoa-bang")).toBeInTheDocument()
  })
})
