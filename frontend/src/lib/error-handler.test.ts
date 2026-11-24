// src/lib/error-handler.test.ts
/**
 * Unit tests for handleApiError function
 *
 * Tests the centralized error handling pattern (ADR-FE-004)
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import type { AxiosError, InternalAxiosRequestConfig } from "axios"
import { handleApiError, isErrorType, readApiError, type ApiErrorResponse, type HandleErrorOptions } from "./error-handler"

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

    it.each([
      ["COUNCIL_DECISION_LOCKS_PROFILE", "Hồ sơ đã có tên trong Quyết định đã ký (hoặc mang dấu đã trúng tuyển theo Quyết định cũ) — không chuyển sang 'rejected'. Muốn đổi, ghi nhận văn bản điều chỉnh / huỷ trước."],
      ["CAU_HINH_DA_DUOC_QUYET_DINH_DUNG", "Dòng cấu hình ngành – năm học (hoặc đường xét) này đã được Quyết định đã ký dùng tới — không sửa năm học / ngành, không xoá. Năm học mới hãy tạo dòng cấu hình mới."],
    ])("review max PR #724 (R8): 409 %s hiện NGUYÊN câu tiếng Việt của máy chủ", (ma, detail) => {
      handleApiError(createAxiosError(409, { detail, error_code: ma }), { context: "từ chối hồ sơ" })

      expect(toast.error).toHaveBeenCalledWith(
        "Không thể từ chối hồ sơ",
        expect.objectContaining({ description: detail })
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

  // Codex N4 (22-11) Q1: toast từng gộp 500 và 503 thành câu cố định "Lỗi hệ thống — Vui lòng thử lại sau…", NÉM ĐI câu
  // máy chủ viết cho người dùng của họ 503 fail-closed (CLAUDE.md dự án, mục Error Handling).
  describe("503 họ fail-closed — hiện câu của máy chủ; 500 / 503 khác — câu chung", () => {
    const CAU_CHUNG = "Vui lòng thử lại sau hoặc liên hệ hỗ trợ"

    it.each([
      ["SERVICE_UNAVAILABLE", "Dịch vụ tạm thời chưa sẵn sàng."],
      [
        "INITIAL_LEAD_STATUS_NOT_CONFIGURED",
        "Hệ thống chưa có trạng thái khởi tạo hợp lệ cho lead mới. Liên hệ quản trị để seed lại bảng trạng thái tư vấn.",
      ],
      ["AUTH_STATE_UNAVAILABLE", "Hệ thống xác thực tạm thời không sẵn sàng. Vui lòng thử lại sau."],
      // N4 `AuditTrailUnavailable.detail` — câu máy chủ, owner 22-11 Q1 (Phê duyệt đơn đi qua handleApiError).
      ["AUDIT_TRAIL_UNAVAILABLE", "Không ghi được nhật ký từ chối — hồ sơ chưa đổi, vui lòng thử lại."],
      // GĐ2-B `ReviewConfigUnavailable` — câu máy chủ `MESSAGES[FEE_GATE_MODE_INVALID]` (admission_review_errors.py).
      [
        "REVIEW_CONFIG_UNAVAILABLE",
        "Cấu hình chế độ cổng học phí trên máy chủ không hợp lệ — không chạy kiểm hồ sơ. Báo quản trị hệ thống.",
      ],
      ["PRIORITY_RATE_NOT_CONFIGURED", "Chưa có mức điểm ưu tiên đang áp dụng."],
    ])("503 %s có detail ⇒ hiện NGUYÊN detail của máy chủ", (ma, detail) => {
      handleApiError(createAxiosError(503, { detail, error_code: ma }), { context: "phê duyệt hồ sơ" })

      expect(toast.error).toHaveBeenCalledWith("Lỗi hệ thống", expect.objectContaining({ description: detail }))
    })

    it.each([
      ["mã chung của handler cuối", { detail: "Lỗi CSDL khi đọc hồ sơ cho bộ văn bản.", error_code: "INTERNAL_ERROR" }],
      ["mã của họ 503 nhưng status 500", { detail: "Dịch vụ tạm thời chưa sẵn sàng.", error_code: "SERVICE_UNAVAILABLE" }],
    ])("500 (%s) ⇒ câu chung, KHÔNG in detail", (_ten, than) => {
      handleApiError(createAxiosError(500, than))

      expect(toast.error).toHaveBeenCalledWith("Lỗi hệ thống", expect.objectContaining({ description: CAU_CHUNG }))
    })

    it.each([
      [
        "thân HTML của nginx",
        "<html>\r\n<head><title>503 Service Temporarily Unavailable</title></head>\r\n<body>nginx</body>\r\n</html>\r\n",
      ],
      ["thân rỗng", ""],
      ["JSON rỗng", {}],
      ["HTTPException (mã HTTP_503, câu nội bộ)", { detail: "Celery service unavailable", error_code: "HTTP_503" }],
      ["mã lạ", { detail: "x", error_code: "SOMETHING_ELSE" }],
      ["mã đúng nhưng không có detail", { error_code: "SERVICE_UNAVAILABLE" }],
    ])("503 %s ⇒ câu chung", (_ten, than) => {
      handleApiError(createAxiosError(503, than as unknown as ApiErrorResponse))

      expect(toast.error).toHaveBeenCalledWith("Lỗi hệ thống", expect.objectContaining({ description: CAU_CHUNG }))
    })

    it.each(["ADMISSION_FROZEN", "NGINX_ADMISSION_FROZEN"])("503 đóng băng (%s) ⇒ như cũ: tiêu đề theo ngữ cảnh + detail", (code) => {
      const detail = "Tuyển sinh đang tạm đóng băng."
      handleApiError(createAxiosError(503, { detail, code } as unknown as ApiErrorResponse), {
        context: "phê duyệt hồ sơ",
      })

      expect(toast.error).toHaveBeenCalledWith("Lỗi phê duyệt hồ sơ", expect.objectContaining({ description: detail }))
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

describe("readApiError — đóng băng hai tầng (review max PR #724 R9)", () => {
  it.each(["ADMISSION_FROZEN", "NGINX_ADMISSION_FROZEN"])("503 + code %s ⇒ frozen", (code) => {
    // thân phản hồi THÔ của máy chủ / nginx (`code` ngoài hợp mã của ApiErrorResponse) ⇒ ép qua unknown
    const v = readApiError(createAxiosError(503, { detail: "x", code } as unknown as ApiErrorResponse))
    expect(v.frozen).toBe(true)
  })
  it("503 với code khác ⇒ KHÔNG frozen; 500 + code đóng băng ⇒ KHÔNG frozen", () => {
    const than = (code: string) => ({ detail: "x", code }) as unknown as ApiErrorResponse
    expect(readApiError(createAxiosError(503, than("SERVICE_UNAVAILABLE"))).frozen).toBe(false)
    expect(readApiError(createAxiosError(500, than("NGINX_ADMISSION_FROZEN"))).frozen).toBe(false)
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
