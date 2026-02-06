// src/lib/error-handler.test.ts
/**
 * Unit tests for handleApiError function
 *
 * Tests the centralized error handling pattern (ADR-FE-004)
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { AxiosError } from "axios"
import { handleApiError, isErrorType, type ApiErrorResponse } from "./error-handler"

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
      config: {} as any,
    },
    isAxiosError: true,
    name: "AxiosError",
    message: "Request failed",
    config: {} as any,
    toJSON: () => ({}),
  }
}

describe("handleApiError", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe("409 Conflict (STATE_CONFLICT)", () => {
    it("should show conflict error with refresh action", () => {
      const error = createAxiosError(409)
      
      handleApiError(error)

      expect(toast.error).toHaveBeenCalledWith(
        "Dữ liệu đã được cập nhật bởi người khác",
        expect.objectContaining({
          action: expect.any(Object),
          duration: 10000,
        })
      )
    })

    it("should invalidate queries when action clicked", () => {
      const mockQueryClient = {
        invalidateQueries: vi.fn(),
      }
      const onConflict = vi.fn()
      const error = createAxiosError(409)

      handleApiError(error, {
        queryClient: mockQueryClient as any,
        invalidateKeys: [["admissions", "detail", 1]],
        onConflict,
      })

      // Get the action callback from the toast call
      const toastCall = vi.mocked(toast.error).mock.calls[0]
      const actionConfig = (toastCall[1] as any)?.action
      
      // Simulate clicking the action
      if (actionConfig?.onClick) {
        actionConfig.onClick()
      }

      expect(mockQueryClient.invalidateQueries).toHaveBeenCalled()
      expect(onConflict).toHaveBeenCalled()
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
      // Backend returns 400 but with STATE_CONFLICT code
      const error = createAxiosError(400, {
        code: "STATE_CONFLICT" as any,
      })

      handleApiError(error)

      expect(toast.error).toHaveBeenCalledWith(
        "Dữ liệu đã được cập nhật bởi người khác",
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
      code: "BUSINESS_RULE_VIOLATION" as any
    })
    
    expect(isErrorType(error, "BUSINESS_RULE_VIOLATION")).toBe(true)
  })
})
