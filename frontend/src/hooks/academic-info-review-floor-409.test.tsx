/**
 * GĐ2-B F2 — M8 (thiết kế giao diện GĐ2-B §3.9, R9): dời năm một học vụ đang có điểm sàn ở lần xét NHÁP ⇒ máy chủ trả 409
 * `ACADEMIC_INFO_IN_REVIEW_FLOOR` (KHÔNG `reason_code`, HĐ4 §5) với câu chỉ tới hai thao tác làm được. Toast phải hiện ĐÚNG câu `detail`
 * của máy chủ ở CẢ HAI hook sửa học vụ có sẵn (nhánh anh em — CLAUDE.md §6):
 *  - `hooks/useOrganization.ts` `useUpdateOfferingAcademicInfo` — PATCH `/api/admin/academic-info/{id}`;
 *  - `hooks/admissions/useProgramData.ts` `useUpdateOfferingAcademicInfo` — PATCH `/api/academic-info/{id}`.
 * Không sửa giao diện (thiết kế §3.9). Biến thể phá: một hook thay câu máy chủ bằng câu cố định ⇒ ca của hook ấy ĐỎ.
 * Câu dưới đây là câu máy chủ `MESSAGE_ACADEMIC_INFO_IN_REVIEW_FLOOR` (`admission_review_errors.py`) điền số giả.
 */
import type { ReactNode } from "react"
import { QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { toast } from "sonner"
import { afterEach, describe, expect, it, vi } from "vitest"

import { server } from "@/test/mocks/server"
import { chanRequestRo } from "@/test/review-sessions-msw"
import { API } from "@/test/mocks/review-sessions-data"
import { appLikeQueryClient } from "@/test/review-sessions-render"

import { useUpdateOfferingAcademicInfo as useUpdateProgramAcademicInfo } from "./admissions/useProgramData"
import { useUpdateOfferingAcademicInfo as useUpdateOrganizationAcademicInfo } from "./useOrganization"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

afterEach(() => server.resetHandlers())

const CAU_MAY_CHU =
  "Học vụ đang có điểm sàn ở lần xét nháp số 3 năm 2026 — bỏ học vụ này khỏi danh sách sàn (lưu lại sàn) hoặc huỷ lần xét nháp đó, rồi làm lại."

interface CaHook {
  ten: string
  url: string
  dung: () => { goi: () => void; xong: boolean }
}

const CA: CaHook[] = [
  {
    ten: "useOrganization — PATCH /api/admin/academic-info/{id}",
    url: `${API}/api/admin/academic-info/41`,
    dung: () => {
      const m = useUpdateOrganizationAcademicInfo()
      return { goi: () => m.mutate({ id: 41, data: { academic_year: 2027 } }), xong: m.isError || m.isSuccess }
    },
  },
  {
    ten: "useProgramData — PATCH /api/academic-info/{id}",
    url: `${API}/api/academic-info/41`,
    dung: () => {
      const m = useUpdateProgramAcademicInfo()
      // Kiểu thân của hook này không khai `academic_year`, nhưng schema máy chủ của route nhận trường ấy (dời năm) — ép kiểu cho ca thử.
      return { goi: () => m.mutate({ id: 41, data: { academic_year: 2027 } as never }), xong: m.isError || m.isSuccess }
    },
  },
]

// Chặn request rò (đối chiếu CI F4; quyết định điều phối 25-11): request không handler ⇒ in lỗi MSW, KHÔNG ra mạng, ca ĐỎ.
chanRequestRo()

describe("M8 — 409 ACADEMIC_INFO_IN_REVIEW_FLOOR khi dời năm học vụ: toast hiện ĐÚNG câu máy chủ", () => {
  it.each(CA)("$ten", async ({ url, dung }) => {
    server.use(
      http.patch(url, () =>
        HttpResponse.json({ detail: CAU_MAY_CHU, error_code: "ACADEMIC_INFO_IN_REVIEW_FLOOR" }, { status: 409 }),
      ),
    )
    const qc = appLikeQueryClient()
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    const { result, unmount } = renderHook(dung, { wrapper })
    act(() => result.current.goi())
    await waitFor(() => expect(result.current.xong).toBe(true))
    await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalled())
    expect(JSON.stringify(vi.mocked(toast.error).mock.calls)).toContain(CAU_MAY_CHU)
    unmount()
  })
})
