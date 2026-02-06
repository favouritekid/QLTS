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
  message?: string
  detail?: string | Array<{ msg: string; loc: string[] }>
  field_errors?: Record<string, string[]>
}

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
      handleConflictError(options)
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

function handleConflictError(options: HandleErrorOptions): void {
  toast.error('Dữ liệu đã được cập nhật bởi người khác', {
    action: {
      label: 'Làm mới',
      onClick: () => {
        options.invalidateKeys?.forEach(key => 
          options.queryClient?.invalidateQueries({ queryKey: key })
        )
        options.onConflict?.()
      }
    },
    duration: 10000, // Keep visible longer for user action
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
