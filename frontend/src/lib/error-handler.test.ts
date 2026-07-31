// src/lib/error-handler.test.ts
/**
 * Unit tests for handleApiError function
 *
 * Tests the centralized error handling pattern (ADR-FE-004)
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import type { AxiosError, InternalAxiosRequestConfig } from "axios"
import { handleApiError, isErrorType, type ApiErrorResponse, type HandleErrorOptions } from "./error-handler"

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
  }
}))

import { toast } from "sonner"

function createAxiosError(
  status: number,
  data: ApiErrorResponse = {}
): AxiosError<ApiErrorResponse> {
  return {
    response: {
      status,
      data,
      statusText: "Error",
      headers: {},
      config: {} as InternalAxiosRequestConfig,
    },
    isAxiosError: true,
    name: "AxiosError",
    message: "Request failed",
    config: {} as InternalAxiosRequestConfig,
    toJSON: () => ({}),
  }
}

describe("handleApiError", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe("409 Conflict (STATE_CONFLICT)", () => {
    // Regression: audit prod 2026-07-30 — 20 lần 409 "trùng số điện thoại" trong
    // 6 phút vì toast hiện thông báo optimistic-lock cứng và ném đi `detail` thật.
    it("hiện detail của DUPLICATE_RESOURCE (message viết cho người dùng)", () => {
      const detail =
        "Số điện thoại này đã được sử dụng. Lead: Quỳnh Anh (SĐT: 0972159242) - Đơn vị: Phòng Tuyển Sinh"
      const error = createAxiosError(409, { detail, error_code: "DUPLICATE_RESOURCE" })

      handleApiError(error, { context: "cập nhật hồ sơ" })

      expect(toast.error).toHaveBeenCalledWith(
        "Không thể cập nhật hồ sơ",
        expect.objectContaining({ description: detail, duration: 10000 })
      )
    })

    it("DUPLICATE_RESOURCE vẫn background-invalidate và không có nút Làm mới", () => {
      const mockQueryClient = { invalidateQueries: vi.fn() }
      const onConflict = vi.fn()
      const error = createAxiosError(409, {
        detail: "Số điện thoại này đã được sử dụng.",
        error_code: "DUPLICATE_RESOURCE",
      })

      handleApiError(error, {
        queryClient: mockQueryClient as unknown as HandleErrorOptions["queryClient"],
        invalidateKeys: [["admissions", "detail", 1]],
        onConflict,
      })

      const toastCall = vi.mocked(toast.error).mock.calls[0]
      const options = toastCall[1] as { action?: unknown } | undefined

      // Nút "Làm mới" chỉ refetch rồi để user bấm Lưu lại y nguyên → vòng lặp.
      expect(options?.action).toBeUndefined()
      // …nhưng refetch vẫn phải xảy ra, im lặng.
      expect(mockQueryClient.invalidateQueries).toHaveBeenCalledWith({
        queryKey: ["admissions", "detail", 1],
      })
      expect(onConflict).toHaveBeenCalled()
    })

    // CONFLICT dùng chung cho version mismatch, xung đột trạng thái VÀ các lỗi
    // nội bộ ("Technical user 'system' is not configured") → không pass-through.
    it("CONFLICT có message nội bộ: KHÔNG pass-through, nhưng vẫn invalidate", () => {
      const mockQueryClient = { invalidateQueries: vi.fn() }
      const error = createAxiosError(409, {
        detail: "Inconsistent application fee ledger: payment method",
        error_code: "CONFLICT",
      })

      handleApiError(error, {
        queryClient: mockQueryClient as unknown as HandleErrorOptions["queryClient"],
        invalidateKeys: [["admissions", "detail", 1]],
        context: "thu lệ phí",
      })

      const toastCall = vi.mocked(toast.error).mock.calls[0]
      const description = (toastCall[1] as { description?: string } | undefined)?.description

      expect(description).not.toContain("Inconsistent application fee ledger")
      expect(description).toContain("trùng hoặc đã thay đổi")
      expect(mockQueryClient.invalidateQueries).toHaveBeenCalled()
    })

    it("tiêu đề 409 không trùng tiêu đề của 422 khi thiếu context", () => {
      const error = createAxiosError(409)

      handleApiError(error)

      expect(toast.error).toHaveBeenCalledWith(
        "Dữ liệu bị trùng hoặc đã thay đổi",
        expect.objectContaining({
          description: expect.stringContaining("trùng hoặc đã thay đổi"),
        })
      )
    })
  })

  describe("400 Validation Error (VALIDATION_FAILED)", () => {
    it("should show validation error with field errors", () => {
      const error = createAxiosError(400, {
        field_errors: {
          email: ["Email không hợp lệ"],
          phone: ["Số điện thoại không đúng định dạng"],
        }
      })
      const onValidation = vi.fn()

      handleApiError(error, { onValidation })

      expect(onValidation).toHaveBeenCalledWith({
        email: ["Email không hợp lệ"],
        phone: ["Số điện thoại không đúng định dạng"],
      })
      expect(toast.error).toHaveBeenCalledWith(
        "Vui lòng kiểm tra lại thông tin",
        expect.objectContaining({
          description: expect.stringContaining("Email không hợp lệ")
        })
      )
    })

    it("should show generic validation error when no field errors", () => {
      const error = createAxiosError(400, {
        detail: "Dữ liệu không đúng định dạng"
      })

      handleApiError(error)

      expect(toast.error).toHaveBeenCalledWith(
        "Dữ liệu không hợp lệ",
        expect.objectContaining({
          description: "Dữ liệu không đúng định dạng"
        })
      )
    })
  })

  describe("403 Forbidden (PERMISSION_DENIED)", () => {
    it("should show permission denied message", () => {
      const error = createAxiosError(403)

      handleApiError(error)

      expect(toast.error).toHaveBeenCalledWith(
        "Bạn không có quyền thực hiện thao tác này"
      )
    })
  })

  describe("404 Not Found (RESOURCE_NOT_FOUND)", () => {
    it("should show not found message", () => {
      const error = createAxiosError(404)

      handleApiError(error)

      expect(toast.error).toHaveBeenCalledWith(
        "Không tìm thấy dữ liệu",
        expect.objectContaining({
          description: expect.stringContaining("đã bị xóa")
        })
      )
    })
  })

  describe("422 Business Rule Violation", () => {
    it("should show business rule error with message", () => {
      const error = createAxiosError(422, {
        detail: "GPA không đạt chuẩn tối thiểu"
      })

      handleApiError(error)

      expect(toast.error).toHaveBeenCalledWith(
        "Không thể thực hiện",
        expect.objectContaining({
          description: "GPA không đạt chuẩn tối thiểu"
        })
      )
    })
  })

  describe("429 Rate Limited", () => {
    it("should show rate limit warning", () => {
      const error = createAxiosError(429)

      handleApiError(error)

      expect(toast.warning).toHaveBeenCalledWith(
        "Vui lòng thử lại sau",
        expect.objectContaining({
          description: expect.stringContaining("nhiều yêu cầu")
        })
      )
    })
  })

  describe("500 Server Error", () => {
    it("should show server error message", () => {
      const error = createAxiosError(500)

      handleApiError(error)

      expect(toast.error).toHaveBeenCalledWith(
        "Lỗi hệ thống",
        expect.objectContaining({
          description: expect.stringContaining("thử lại sau")
        })
      )
    })
  })

  describe("Unknown Error", () => {
    it("should show generic error for unknown status", () => {
      const error = createAxiosError(418, { message: "I'm a teapot" }) // Unsupported status

      handleApiError(error)

      expect(toast.error).toHaveBeenCalledWith(
        "Đã có lỗi xảy ra",
        expect.objectContaining({
          description: "I'm a teapot"
        })
      )
    })

    it("should use context in generic error message", () => {
      const error = createAxiosError(418)

      handleApiError(error, { context: "cập nhật hồ sơ" })

      expect(toast.error).toHaveBeenCalledWith(
        "Lỗi cập nhật hồ sơ",
        expect.any(Object)
      )
    })
  })

  describe("Backend code field", () => {
    it("should prefer backend code over HTTP status", () => {
      // Backend returns 400 but with STATE_CONFLICT code. Không kèm
      // `error_code` version-conflict → đi nhánh conflict-không-xác-định.
      const error = createAxiosError(400, {
        code: "STATE_CONFLICT",
      })

      handleApiError(error)

      expect(toast.error).toHaveBeenCalledWith(
        "Dữ liệu bị trùng hoặc đã thay đổi",
        expect.any(Object)
      )
    })
  })
})

describe("isErrorType", () => {
  it("should identify error type from code", () => {
    const error = createAxiosError(409)
    
    expect(isErrorType(error, "STATE_CONFLICT")).toBe(true)
    expect(isErrorType(error, "VALIDATION_FAILED")).toBe(false)
  })

  it("should identify error type from backend code", () => {
    const error = createAxiosError(400, {
      code: "BUSINESS_RULE_VIOLATION"
    })
    
    expect(isErrorType(error, "BUSINESS_RULE_VIOLATION")).toBe(true)
  })
})
