/**
 * GĐ2-F1 — trang bảng chỉ tiêu năm: năm chưa có bảng (404 mã riêng `quota_table_not_found` + cờ `create`) ⇒ cho tạo với
 * `version` 0; máy chủ 403 ⇒ câu "Chỉ Admin" (không kiểm vai ở giao diện).
 *
 * Rà hợp nhất 23-11 H4 (GĐ2-C C2 mở GET cho Ban thư ký): 404 của cổng Thư ký (thân chung, KHÔNG `reason_code`) không được hiện
 * thành "năm chưa có bảng" + nút tạo; Thư ký xem năm chưa có bảng (cờ rỗng) ⇒ không nút tạo.
 *
 * Codex lượt 3 (rà độc lập, điểm chặn giao diện): danh sách "thêm ngành" + chỉ tiêu ĐIỀN SẴN lấy từ `academic_infos` máy chủ trả
 * KÈM dấu chỉ tiêu (GET bảng; năm chưa có bảng: thân 404) — cùng một lần đọc với dấu. Các ca dưới cố ý cho danh mục học vụ cũ
 * (`/api/offerings/academic-info`, bộ đệm `["academic-infos"]`) trả số KHÁC: trang còn đọc danh mục ấy thì điền số cũ ⇒ đỏ.
 * Dữ liệu giả.
 */
import { afterEach, describe, expect, it } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"

import { API, renderWithClient } from "@/components/document-review/test-helpers"
import { server } from "@/test/mocks/server"

import { buildMemberOptions, QuotaTablesClient } from "./QuotaTablesClient"

const P = `${API}/api/admission-config/quota-tables/2026`
const FP_1 = "1".repeat(64)
const FP_2 = "2".repeat(64)
const NHAN_21 = "Chỉ tiêu năm — M1 — Ngành Một (Chính quy)"

function hocVu(id: number, quota: number | null, is_deleted = false) {
  return {
    offering_academic_info_id: id,
    offering_id: 1,
    major_code: id === 21 ? "M1" : `M${id}`,
    major_name: id === 21 ? "Ngành Một" : `Ngành ${id}`,
    offering_type: "Chính quy",
    annual_admission_quota: quota,
    is_deleted,
  }
}

/** Danh mục học vụ CŨ (bộ đệm khác dấu) — học vụ 21 mang chỉ tiêu `quota`. Trang đúng KHÔNG đọc nguồn này. */
function batDanhMucCu(quota: number | null) {
  server.use(
    http.get(`${API}/api/offerings/academic-info`, () =>
      HttpResponse.json([{ id: 21, offering_id: 1, academic_year: 2026, annual_admission_quota: quota, is_deleted: false }]),
    ),
    http.get(`${API}/api/program-offerings`, () =>
      HttpResponse.json([{ id: 1, offering_type: "Chính quy", program: { code: "M1", name: "Ngành Một" } }]),
    ),
  )
}

function bang(fp: string, quota21: number | null) {
  return {
    academic_year: 2026,
    status: "draft",
    version: 1,
    locked_by_user_id: null,
    locked_at: null,
    available_actions: ["edit", "lock"],
    quota_fingerprint: fp,
    groups: [
      {
        id: 7,
        code: "N1",
        name: "Nhóm thử",
        ceiling: 120,
        usage: { publish_count: 0, approved_count: 0, used: 0 },
        members: [],
      },
    ],
    academic_infos: [hocVu(21, quota21)],
  }
}

type Than = { version: number; quota_fingerprint: string; groups: Array<{ members: unknown[] }> }

afterEach(() => server.resetHandlers())

describe("QuotaTablesClient", () => {
  it("năm chưa có bảng (404) ⇒ nút tạo; tạo ⇒ PUT version 0 + DẤU CHỈ TIÊU trong thân 404", async () => {
    const than: unknown[] = []
    batDanhMucCu(null)
    server.use(
      http.get(P, () =>
        HttpResponse.json(
          {
            detail: "Năm 2026 chưa có bảng chỉ tiêu.",
            reason_code: "quota_table_not_found",
            available_actions: ["create"],
            quota_fingerprint: "c".repeat(64),
            academic_infos: [hocVu(21, null)],
          },
          { status: 404 },
        ),
      ),
      http.put(P, async ({ request }) => {
        than.push(await request.json())
        return HttpResponse.json({ ...bang("d".repeat(64), null), groups: [] })
      }),
    )
    const u = userEvent.setup()
    renderWithClient(<QuotaTablesClient initialYear={2026} />)
    await u.click(await screen.findByTestId("nut-tao-bang"))
    await u.click(screen.getByRole("button", { name: /Thêm nhóm ngành/ }))
    await u.type(screen.getByLabelText("Mã nhóm"), "N1")
    await u.type(screen.getByLabelText("Tên nhóm"), "Nhóm thử")
    await u.type(screen.getByLabelText("Trần chỉ tiêu nhóm"), "10")
    await u.click(screen.getByTestId("luu-bang"))
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({
      version: 0,
      quota_fingerprint: "c".repeat(64),
      groups: [{ code: "N1", name: "Nhóm thử", ceiling: 10, members: [] }],
    })
  })

  it("Codex lượt 3: năm chưa có bảng ⇒ ngành để thêm + chỉ tiêu điền sẵn lấy từ THÂN 404 (cùng lần đọc với dấu), không từ danh mục cũ", async () => {
    const than: Than[] = []
    batDanhMucCu(null) // danh mục cũ: học vụ 21 CHƯA có chỉ tiêu
    server.use(
      http.get(P, () =>
        HttpResponse.json(
          {
            detail: "Năm 2026 chưa có bảng chỉ tiêu.",
            reason_code: "quota_table_not_found",
            available_actions: ["create"],
            quota_fingerprint: "c".repeat(64),
            academic_infos: [hocVu(21, 7), hocVu(23, 9, true)],
          },
          { status: 404 },
        ),
      ),
      http.put(P, async ({ request }) => {
        than.push((await request.json()) as Than)
        return HttpResponse.json(bang("d".repeat(64), 7))
      }),
    )
    const u = userEvent.setup()
    renderWithClient(<QuotaTablesClient initialYear={2026} />)
    await u.click(await screen.findByTestId("nut-tao-bang"))
    await u.click(screen.getByRole("button", { name: /Thêm nhóm ngành/ }))
    await u.type(screen.getByLabelText("Mã nhóm"), "N1")
    await u.type(screen.getByLabelText("Tên nhóm"), "Nhóm thử")
    await u.type(screen.getByLabelText("Trần chỉ tiêu nhóm"), "10")
    const chon = screen.getByLabelText("Thêm ngành vào nhóm")
    // Học vụ đã xoá mềm (23) không nằm trong danh sách chọn.
    expect(chon.querySelector('option[value="23"]')).toBeNull()
    await u.selectOptions(chon, "21")
    expect(screen.getByLabelText(NHAN_21)).toHaveValue(7)
    await u.click(screen.getByTestId("luu-bang"))
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0].quota_fingerprint).toBe("c".repeat(64))
    expect(than[0].groups[0].members).toEqual([{ offering_academic_info_id: 21, annual_admission_quota: 7 }])
  })

  it("Codex lượt 3: 409 rồi tải lại bảng ⇒ mở soạn lại điền chỉ tiêu MỚI của GET bảng với dấu MỚI — không ghi đè bằng số cũ", async () => {
    // Người khác vừa đổi chỉ tiêu học vụ 21 từ 50 lên 60: lần GET đầu (50, dấu 1), các lần sau (60, dấu 2). Danh mục học vụ cũ
    // (bộ đệm không được làm mới) vẫn giữ 50. Trước đây: mở lại trình soạn ⇒ dấu 2 nhưng điền sẵn 50 ⇒ máy chủ nhận ⇒ 60 bị đè.
    let soLanGet = 0
    const than: Than[] = []
    batDanhMucCu(50)
    server.use(
      http.get(P, () => {
        soLanGet += 1
        return HttpResponse.json(soLanGet === 1 ? bang(FP_1, 50) : bang(FP_2, 60))
      }),
      http.put(P, async ({ request }) => {
        than.push((await request.json()) as Than)
        return than.length === 1
          ? HttpResponse.json(
              { reason_code: "quota_table_stale", error_code: "QUOTA_TABLE_STALE", current_version: 1, detail: "x" },
              { status: 409 },
            )
          : HttpResponse.json(bang(FP_2, 60))
      }),
    )
    const u = userEvent.setup()
    renderWithClient(<QuotaTablesClient initialYear={2026} />)
    await u.click(await screen.findByTestId("nut-sua-bang"))
    await u.click(screen.getByTestId("luu-bang"))
    await screen.findByRole("alert")
    await waitFor(() => expect(soLanGet).toBeGreaterThanOrEqual(2)) // 409 ⇒ bảng được tải lại
    await u.click(screen.getByRole("button", { name: "Huỷ" }))
    await u.click(await screen.findByTestId("nut-sua-bang"))
    await u.selectOptions(screen.getByLabelText("Thêm ngành vào nhóm"), "21")
    expect(screen.getByLabelText(NHAN_21)).toHaveValue(60)
    await u.click(screen.getByTestId("luu-bang"))
    await waitFor(() => expect(than).toHaveLength(2))
    expect(than[1].quota_fingerprint).toBe(FP_2)
    expect(than[1].groups[0].members).toEqual([{ offering_academic_info_id: 21, annual_admission_quota: 60 }])
  })

  it.each([
    ["cờ rỗng", { available_actions: [] }],
    ["không có cờ", {}],
  ])(
    "H4: năm chưa có bảng (404 mã riêng) mà máy chủ KHÔNG cho tạo (%s — Thư ký) ⇒ câu 'chưa có bảng', KHÔNG nút tạo",
    async (_ten, co) => {
      batDanhMucCu(null)
      server.use(
        http.get(P, () =>
          HttpResponse.json(
            {
              detail: "Năm 2026 chưa có bảng chỉ tiêu.",
              error_code: "RESOURCE_NOT_FOUND",
              reason_code: "quota_table_not_found",
              quota_fingerprint: "c".repeat(64),
              academic_infos: [hocVu(21, null)],
              ...co,
            },
            { status: 404 },
          ),
        ),
      )
      renderWithClient(<QuotaTablesClient initialYear={2026} />)
      expect(await screen.findByTestId("chua-co-bang")).toHaveTextContent("Năm 2026 chưa có bảng chỉ tiêu.")
      expect(screen.queryByTestId("nut-tao-bang")).toBeNull()
      expect(screen.queryByTestId("loi-tai-bang")).toBeNull()
    },
  )

  it("H4: 404 của cổng Thư ký (thân chung, không reason_code) ⇒ KHÔNG báo 'chưa có bảng', KHÔNG nút tạo; báo không xem được", async () => {
    batDanhMucCu(null)
    server.use(
      http.get(P, () =>
        HttpResponse.json({ detail: "Không tìm thấy", error_code: "RESOURCE_NOT_FOUND" }, { status: 404 }),
      ),
    )
    renderWithClient(<QuotaTablesClient initialYear={2026} />)
    const loi = await screen.findByTestId("loi-tai-bang")
    expect(loi).toHaveTextContent(/chưa được gán quyền Thư ký Hội đồng/)
    expect(loi).not.toHaveTextContent(/chưa có bảng/)
    expect(screen.queryByTestId("chua-co-bang")).toBeNull()
    expect(screen.queryByTestId("nut-tao-bang")).toBeNull()
  })

  it("máy chủ 403 ⇒ câu 'Chỉ Admin', không nút tạo / sửa", async () => {
    batDanhMucCu(null)
    server.use(http.get(P, () => HttpResponse.json({ detail: "x", error_code: "PERMISSION_DENIED" }, { status: 403 })))
    renderWithClient(<QuotaTablesClient initialYear={2026} />)
    expect(await screen.findByTestId("loi-tai-bang")).toHaveTextContent(/Chỉ Admin/)
    expect(screen.queryByTestId("nut-tao-bang")).toBeNull()
    expect(screen.queryByTestId("nut-sua-bang")).toBeNull()
  })
})

describe("buildMemberOptions", () => {
  it("bỏ học vụ đã xoá mềm; giữ chỉ tiêu null là null; nhãn ngành + loại hình", () => {
    const o = buildMemberOptions([hocVu(21, null), hocVu(23, 5, true)])
    expect(o).toEqual([
      { offering_academic_info_id: 21, label: "M1 — Ngành Một (Chính quy)", annual_admission_quota: null },
    ])
  })
})
