/**
 * Test hook xuất danh sách khoản phí (PR-A / H1).
 *
 * Ca quan trọng nhất: **lỗi phải đi qua `blobErrorMessage`**. Vì
 * `responseType:'blob'`, axios bọc body lỗi JSON thành Blob nên đọc thẳng
 * `error.response.data.detail` luôn ra `undefined` — người dùng sẽ chỉ thấy
 * thông báo chung chung thay vì câu "kết quả lọc vượt quá N dòng, hãy thu hẹp
 * bộ lọc", tức mất luôn hướng dẫn để tự xử lý.
 */

import { describe, it, expect, beforeEach, vi } from "vitest"
import { renderHook, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClientProvider } from "@tanstack/react-query"

import { server } from "@/test/mocks/server"
import { createTestQueryClient } from "@/test/utils/test-utils"
import { useTuitionExport } from "./useTuitionExport"

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"

const toastError = vi.fn()
const toastSuccess = vi.fn()
vi.mock("sonner", () => ({
  toast: {
    error: (...args: unknown[]) => toastError(...args),
    success: (...args: unknown[]) => toastSuccess(...args),
  },
}))

const downloadBlobSpy = vi.fn()
const blobErrorMessageSpy = vi.fn()
vi.mock("@/lib/utils/download-blob", async (importOriginal) => {
  const actual = await importOriginal<
    typeof import("@/lib/utils/download-blob")
  >()
  return {
    ...actual,
    downloadBlob: (...args: unknown[]) => downloadBlobSpy(...args),
    blobErrorMessage: (...args: unknown[]) => blobErrorMessageSpy(...args),
  }
})

function createWrapper() {
  const queryClient = createTestQueryClient()
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  Wrapper.displayName = "TestQueryClientWrapper"
  return Wrapper
}

describe("useTuitionExport", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("tải file và lấy tên từ Content-Disposition", async () => {
    server.use(
      http.get(`${API_BASE_URL}/api/invoices/export`, () =>
        HttpResponse.arrayBuffer(new TextEncoder().encode("x").buffer, {
          headers: {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition":
              'attachment; filename="danh_sach_khoan_phi_20260803_101500.csv"',
          },
        }),
      ),
    )

    const { result } = renderHook(() => useTuitionExport(), {
      wrapper: createWrapper(),
    })
    result.current.mutate({ format: "csv", filters: {} })

    await waitFor(() => expect(downloadBlobSpy).toHaveBeenCalled())
    // Tên phải là tên server đặt (có mốc thời gian), không phải tên cứng ở client
    expect(downloadBlobSpy.mock.calls[0][1]).toBe(
      "danh_sach_khoan_phi_20260803_101500.csv",
    )
  })

  it("[N] thiếu Content-Disposition → fallback dùng tên KHOẢN PHÍ", async () => {
    // Tên fallback phải theo bản đổi tên (khoản phí), không phải tên cũ
    // "danh_sach_hoc_phi" — tệp gồm cả lệ phí hồ sơ nên gọi là học phí là sai.
    server.use(
      http.get(`${API_BASE_URL}/api/invoices/export`, () =>
        HttpResponse.arrayBuffer(new TextEncoder().encode("x").buffer, {
          headers: { "Content-Type": "text/csv; charset=utf-8" }, // KHÔNG có Content-Disposition
        }),
      ),
    )

    const { result } = renderHook(() => useTuitionExport(), {
      wrapper: createWrapper(),
    })
    result.current.mutate({ format: "csv", filters: {} })

    await waitFor(() => expect(downloadBlobSpy).toHaveBeenCalled())
    expect(downloadBlobSpy.mock.calls[0][1]).toBe("danh_sach_khoan_phi.csv")
  })

  it("[N] lỗi phải đi qua blobErrorMessage, không đọc thẳng data.detail", async () => {
    // Vì responseType:'blob', axios bọc body lỗi JSON thành Blob nên
    // `error.response.data.detail` luôn undefined. Hook BẮT BUỘC dùng
    // blobErrorMessage — ca này khoá đúng điều đó: bỏ nó đi là spy không được
    // gọi và toast hiện chuỗi khác.
    const detail =
      "Kết quả lọc vượt quá 10.000 dòng cho một lần xuất. " +
      "Hãy thu hẹp bộ lọc (năm học / học kỳ / đơn vị / ngành) rồi xuất lại."
    blobErrorMessageSpy.mockResolvedValue(detail)
    server.use(
      http.get(`${API_BASE_URL}/api/invoices/export`, () =>
        HttpResponse.json({ detail, error_code: "BAD_REQUEST" }, { status: 400 }),
      ),
    )

    const { result } = renderHook(() => useTuitionExport(), {
      wrapper: createWrapper(),
    })
    result.current.mutate({ format: "xlsx", filters: {} })

    await waitFor(() => expect(toastError).toHaveBeenCalled())
    expect(blobErrorMessageSpy).toHaveBeenCalledTimes(1)
    // Fallback truyền vào phải là câu tiếng Việt của tính năng này.
    expect(blobErrorMessageSpy.mock.calls[0][1]).toBe(
      "Không xuất được danh sách khoản phí",
    )
    // Toast hiện ĐÚNG chuỗi mà blobErrorMessage trả về.
    expect(toastError).toHaveBeenCalledWith(detail)
    expect(downloadBlobSpy).not.toHaveBeenCalled()
  })
})
