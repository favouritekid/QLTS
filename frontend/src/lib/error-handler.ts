/**
 * ARCHITECTURE STANDARD: Centralized Error Handler
 * 
 * This module provides unified error handling for all API mutations.
 * 
 * Rules:
 * - ALL mutations MUST use handleApiError() in onError
 * - NO direct toast.error() calls in mutation handlers
 * - Backend error codes are mapped to Vietnamese user messages
 * 
 * @see FRONTEND_ARCHITECTURE_V3.md Section 2.4
 */

import { AxiosError } from 'axios'
import { toast } from 'sonner'
import type { QueryClient } from '@tanstack/react-query'

// =============================================================================
// ERROR CODE TAXONOMY
// =============================================================================

export type ErrorCode = 
  | 'VALIDATION_FAILED'       // 400 - Form validation errors
  | 'AUTHENTICATION_REQUIRED' // 401 - Redirect to login
  | 'PERMISSION_DENIED'       // 403 - Show access denied
  | 'RESOURCE_NOT_FOUND'      // 404 - Show not found
  | 'STATE_CONFLICT'          // 409 - Optimistic lock conflict
  | 'BUSINESS_RULE_VIOLATION' // 422 - Business logic error
  | 'RATE_LIMITED'            // 429 - Too many requests
  | 'SERVER_ERROR'            // 500 - System error
  | 'UNKNOWN'                 // Fallback

// =============================================================================
// API ERROR STRUCTURE
// =============================================================================

export interface ApiErrorResponse {
  code?: ErrorCode
  /**
   * Mã lỗi máy-đọc do backend gửi (`base_app_exception_handler` trả
   * `{detail, error_code}` — xem `app/middleware/exception_handlers.py`).
   * KHÁC `code` ở trên: `code` là taxonomy của frontend và backend hiện
   * KHÔNG gửi field đó. Chỉ dùng `error_code` để phân biệt các nghĩa khác
   * nhau của cùng một HTTP status (xem `handleConflictError`) — việc map
   * toàn bộ taxonomy sang `error_code` là một thay đổi riêng.
   */
  error_code?: string
  message?: string
  detail?: string | Array<{ msg: string; loc: string[] }>
  field_errors?: Record<string, string[]>
}

/**
 * `error_code` của backend mà message ĐÃ được viết cho người dùng cuối:
 * tiếng Việt, nói rõ phải làm gì. Chỉ những mã này được hiện `detail` thô.
 *
 * `DuplicateResourceError` (`app/utils/exceptions.py`) là mã như vậy — vd
 * "Số điện thoại này đã được sử dụng. Lead: … - Đơn vị: … - Quản lý bởi: …",
 * và backend CỐ Ý kèm tên/đơn vị/officer để officer xử lý được ca cross-unit
 * (`app/services/lead_service.py:1564`).
 *
 * Ngược lại `ConflictError` dùng chung mã `CONFLICT` cho nhiều thứ, trong đó
 * có chuỗi nội bộ/tiếng Anh không được để lộ ra UI: "Technical user 'system'
 * is not configured", "Inconsistent application fee ledger: payment method",
 * "Multiple application fee rows exist for this profile".
 */
const USER_FACING_CONFLICT_CODES = new Set<string>(['DUPLICATE_RESOURCE'])

// =============================================================================
// HANDLER OPTIONS
// =============================================================================

export interface HandleErrorOptions {
  /** QueryClient for invalidating queries on conflict */
  queryClient?: QueryClient
  /** Query keys to invalidate on conflict */
  invalidateKeys?: unknown[][]
  /** Callback when conflict (409) occurs */
  onConflict?: () => void
  /** Callback when validation error (400) occurs with field errors */
  onValidation?: (errors: Record<string, string[]>) => void
  /** Custom context for error message (e.g., "cập nhật hồ sơ") */
  context?: string
}

// =============================================================================
// MAIN HANDLER
// =============================================================================

/**
 * Handle API errors with consistent UI feedback.
 * 
 * @param error - Axios error from mutation
 * @param options - Optional handlers for specific error types
 * 
 * @example
 * useMutation({
 *   mutationFn: updateProfile,
 *   onError: (error) => handleApiError(error, {
 *     queryClient,
 *     invalidateKeys: [profileKeys.detail(id)],
 *   })
 * })
 */
export function handleApiError(
  error: AxiosError<ApiErrorResponse>,
  options: HandleErrorOptions = {}
): void {
  const status = error.response?.status
  const data = error.response?.data
  const code = data?.code ?? mapStatusToCode(status)
  
  switch (code) {
    case 'STATE_CONFLICT':
      handleConflictError(data, options)
      break
      
    case 'VALIDATION_FAILED':
      handleValidationError(data, options)
      break
      
    case 'PERMISSION_DENIED':
      toast.error('Bạn không có quyền thực hiện thao tác này')
      break
      
    case 'AUTHENTICATION_REQUIRED':
      toast.error('Phiên đăng nhập hết hạn', { 
        description: 'Vui lòng đăng nhập lại' 
      })
      break
      
    case 'RESOURCE_NOT_FOUND':
      toast.error('Không tìm thấy dữ liệu', {
        description: 'Dữ liệu có thể đã bị xóa hoặc di chuyển'
      })
      break
      
    case 'BUSINESS_RULE_VIOLATION':
      toast.error('Không thể thực hiện', { 
        description: extractMessage(data) 
      })
      break
      
    case 'RATE_LIMITED':
      toast.warning('Vui lòng thử lại sau', { 
        description: 'Quá nhiều yêu cầu trong thời gian ngắn' 
      })
      break
      
    case 'SERVER_ERROR':
      toast.error('Lỗi hệ thống', { 
        description: 'Vui lòng thử lại sau hoặc liên hệ hỗ trợ' 
      })
      break
      
    default:
      const contextMsg = options.context ? `Lỗi ${options.context}` : 'Đã có lỗi xảy ra'
      toast.error(contextMsg, { description: extractMessage(data) })
  }
}

// =============================================================================
// SPECIALIZED HANDLERS
// =============================================================================

/**
 * 409 — nhiều nghĩa rất khác nhau dùng chung một HTTP status: trùng dữ liệu
 * (`DUPLICATE_RESOURCE`), xung đột phiên bản và xung đột trạng thái (cả hai
 * đều là `CONFLICT`).
 *
 * Trước đây handler chỉ xử lý theo một nghĩa: toast cứng "Dữ liệu đã được cập
 * nhật bởi người khác" + nút "Làm mới", và NÉM ĐI `detail` của backend. Audit
 * prod 2026-07-30: một hồ sơ nhận 20 lần 409 trong 6 phút vì officer nhập số
 * điện thoại của phụ huynh vào ô SĐT thí sinh — backend nói rõ lý do, nhưng
 * officer chỉ thấy câu về "người khác cập nhật" nên bấm Làm mới rồi Lưu lại,
 * y hệt, hàng chục lần.
 *
 * Nay:
 *  - LUÔN background-invalidate (im lặng, không cần user bấm gì) để màn hình
 *    tự sửa ở các ca refetch giải quyết được — vd xung đột trạng thái sau khi
 *    người khác đã duyệt. An toàn với form đang nhập dở: effect reset form ở
 *    `AdmissionDetailClient.tsx:200` có guard `!isDirty` nên draft được giữ.
 *  - Chỉ hiện `detail` thô khi mã lỗi nằm trong `USER_FACING_CONFLICT_CODES`;
 *    các mã khác dùng câu tiếng Việt chung để không lộ chuỗi nội bộ.
 *  - KHÔNG có nút "Làm mới": nút đó vốn không thoát được bế tắc (guard
 *    `!isDirty` giữ `version` cũ trong form) mà chỉ khuyến khích bấm lại.
 *    Nút làm mới hiệu quả cần một `error_code` riêng cho optimistic-lock —
 *    thuộc đợt đồng bộ contract, không làm ở hotfix này.
 */
function handleConflictError(
  data: ApiErrorResponse | undefined,
  options: HandleErrorOptions
): void {
  // Background-invalidate: cache có thể đã cũ so với server ở mọi loại 409.
  options.invalidateKeys?.forEach(key =>
    options.queryClient?.invalidateQueries({ queryKey: key })
  )
  options.onConflict?.()

  const isUserFacing =
    data?.error_code !== undefined && USER_FACING_CONFLICT_CODES.has(data.error_code)
  const message = isUserFacing ? extractMessage(data) : ''
  // Không dùng 'Không thể thực hiện' khi thiếu context — đó là tiêu đề của 422
  // BUSINESS_RULE_VIOLATION; trùng tiêu đề thì user (và screenshot hỗ trợ)
  // không phân biệt được "xung đột dữ liệu" với "nghiệp vụ từ chối".
  const title = options.context
    ? `Không thể ${options.context}`
    : 'Dữ liệu bị trùng hoặc đã thay đổi'

  toast.error(title, {
    description:
      message ||
      'Dữ liệu vừa nhập bị trùng hoặc đã thay đổi trên hệ thống. Vui lòng kiểm tra lại.',
    duration: 10000, // Message backend thường dài — để user đọc kịp
  })
}

function handleValidationError(
  data: ApiErrorResponse | undefined, 
  options: HandleErrorOptions
): void {
  const fieldErrors = data?.field_errors ?? {}
  
  if (Object.keys(fieldErrors).length > 0) {
    options.onValidation?.(fieldErrors)
    const errorMessages = Object.values(fieldErrors).flat()
    toast.error('Vui lòng kiểm tra lại thông tin', {
      description: errorMessages.slice(0, 3).join(', ') + 
        (errorMessages.length > 3 ? ` (+${errorMessages.length - 3} lỗi khác)` : '')
    })
  } else {
    toast.error('Dữ liệu không hợp lệ', { 
      description: extractMessage(data) 
    })
  }
}

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

function mapStatusToCode(status?: number): ErrorCode {
  switch (status) {
    case 400: return 'VALIDATION_FAILED'
    case 401: return 'AUTHENTICATION_REQUIRED'
    case 403: return 'PERMISSION_DENIED'
    case 404: return 'RESOURCE_NOT_FOUND'
    case 409: return 'STATE_CONFLICT'
    case 422: return 'BUSINESS_RULE_VIOLATION'
    case 429: return 'RATE_LIMITED'
    case 500: 
    case 502:
    case 503:
    case 504:
      return 'SERVER_ERROR'
    default: 
      return 'UNKNOWN'
  }
}

function extractMessage(data?: ApiErrorResponse): string {
  if (!data) return ''
  if (typeof data.detail === 'string') return data.detail
  if (Array.isArray(data.detail)) {
    return data.detail.map(e => e.msg).join(', ')
  }
  return data.message ?? ''
}

/**
 * Check if an error is a specific type.
 * Useful for conditional handling in components.
 */
export function isErrorType(
  error: AxiosError<ApiErrorResponse>, 
  type: ErrorCode
): boolean {
  const status = error.response?.status
  const code = error.response?.data?.code
  return code === type || mapStatusToCode(status) === type
}
