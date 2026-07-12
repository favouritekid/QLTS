/**
 * ARCHITECTURE STANDARD: Status-Driven UI Configuration
 * 
 * This module defines how UI should render based on backend status.
 * Every module MUST use this config for consistent UI behavior.
 * 
 * Rules:
 * - Backend owns status values
 * - Frontend owns presentation only
 * - Unknown statuses get fallback config (future-proofing)
 * 
 * @see FRONTEND_ARCHITECTURE_V3.md Section 2.1
 */

export interface StatusUIConfig {
  /** Display label for the status */
  label: string
  /** Badge variant for shadcn/ui Badge component */
  badgeVariant: 'default' | 'secondary' | 'destructive' | 'outline'
  /** Tailwind classes for badge styling */
  badgeColor: string
  /** Whether to show a status banner */
  showBanner: boolean
  /** Banner type for toast/alert styling */
  bannerType?: 'info' | 'warning' | 'success' | 'error'
  /** Banner message to display */
  bannerMessage?: string
  /** Actions that UI should indicate as available (for visual hints only) */
  allowedActions: string[]
}

// =============================================================================
// ADMISSION STATUS CONFIG
// =============================================================================

export const ADMISSION_STATUS_CONFIG: Record<string, StatusUIConfig> = {
  draft: {
    label: 'Nháp',
    badgeVariant: 'secondary',
    badgeColor: 'bg-muted text-muted-foreground',
    showBanner: false,
    allowedActions: ['save', 'submit'],
  },
  submitted: {
    label: 'Chờ duyệt',
    badgeVariant: 'default',
    badgeColor: 'bg-info-100 text-info-700',
    showBanner: true,
    bannerType: 'info',
    bannerMessage: 'Hồ sơ đang chờ xét duyệt',
    allowedActions: [],
  },
  resubmitted: {
    label: 'Đã nộp lại',
    badgeVariant: 'default',
    badgeColor: 'bg-info-100 text-info-700',
    showBanner: true,
    bannerType: 'info',
    bannerMessage: 'Hồ sơ đã được nộp lại và đang chờ xét duyệt',
    allowedActions: [],
  },
  approved: {
    label: 'Đã duyệt',
    badgeVariant: 'default',
    badgeColor: 'bg-success-100 text-success-700',
    showBanner: true,
    bannerType: 'info',
    bannerMessage:
      'Hồ sơ đã duyệt. Đang chờ thí sinh xác nhận qua email (4 số cuối CCCD) trước khi ghi danh.',
    allowedActions: ['enroll'],
  },
  rejected: {
    label: 'Từ chối',
    badgeVariant: 'destructive',
    badgeColor: 'bg-error-100 text-error-700',
    showBanner: true,
    bannerType: 'warning',
    bannerMessage: 'Hồ sơ bị từ chối. Vui lòng chỉnh sửa và nộp lại.',
    allowedActions: ['edit', 'resubmit'],
  },
  revision_requested: {
    label: 'Yêu cầu bổ sung',
    badgeVariant: 'outline',
    badgeColor: 'bg-orange-100 text-orange-700',
    showBanner: true,
    bannerType: 'warning',
    bannerMessage: 'Hồ sơ cần bổ sung thêm tài liệu/thông tin. Vui lòng chỉnh sửa và nộp lại.',
    allowedActions: ['edit', 'resubmit'],
  },
  confirmed: {
    label: 'Đã xác nhận',
    badgeVariant: 'default',
    badgeColor: 'bg-emerald-100 text-emerald-700',
    showBanner: true,
    bannerType: 'success',
    bannerMessage: 'Hồ sơ đã được xác nhận bởi thí sinh',
    allowedActions: ['enroll'],
  },
  overridden: {
    label: 'Đã override',
    badgeVariant: 'default',
    badgeColor: 'bg-purple-100 text-purple-700',
    showBanner: true,
    bannerType: 'warning',
    bannerMessage: 'Hồ sơ đã được admin override',
    allowedActions: ['enroll'],
  },
  enrolled: {
    label: 'Đã nhập học',
    badgeVariant: 'default',
    badgeColor: 'bg-blue-100 text-blue-700',
    showBanner: false,
    allowedActions: [],
  },
  withdrawn: {
    label: 'Đã rút hồ sơ',
    badgeVariant: 'secondary',
    badgeColor: 'bg-muted text-muted-foreground',
    showBanner: true,
    bannerType: 'info',
    bannerMessage: 'Hồ sơ đã được rút lại.',
    allowedActions: [],
  },
  // PR-B: intermediate "Chờ hoàn để rút" — a refund is being processed; the
  // profile settles to withdrawn only once the money is returned.
  withdrawal_pending: {
    label: 'Chờ hoàn để rút',
    badgeVariant: 'outline',
    badgeColor: 'bg-amber-50 text-amber-700',
    showBanner: true,
    bannerType: 'warning',
    bannerMessage: 'Hồ sơ có học phí đã thu — đang chờ hoàn tiền trước khi rút. Chỉ rút xong khi hoàn tất.',
    allowedActions: [],
  },
  // Phase 3 PR-3D-A Sub-3: 4 NEW multi-NV states (Phase 1 #11 DB CHECK
  // extension, choice-engine workflow). Status badge config trong
  // `status-badge.config.ts` đã có entries từ Phase 1 — đây là
  // text/banner config for legacy status-config consumers.
  reviewing: {
    label: 'Đang xét',
    badgeVariant: 'default',
    badgeColor: 'bg-info-50 text-info-700',
    showBanner: true,
    bannerType: 'info',
    bannerMessage: 'Hồ sơ đang được xét duyệt qua engine.',
    allowedActions: [],
  },
  result_published: {
    label: 'Đã công bố kết quả',
    badgeVariant: 'default',
    badgeColor: 'bg-sky-50 text-sky-700',
    showBanner: true,
    bannerType: 'info',
    bannerMessage: 'Kết quả tuyển sinh đã được công bố (T6).',
    allowedActions: [],
  },
  admitted: {
    label: 'Đậu',
    badgeVariant: 'default',
    badgeColor: 'bg-green-50 text-green-700',
    showBanner: true,
    bannerType: 'success',
    bannerMessage: 'Chúc mừng — bạn đã trúng tuyển!',
    allowedActions: ['confirm', 'withdraw'],
  },
  waitlisted: {
    label: 'Chờ ghế',
    badgeVariant: 'outline',
    badgeColor: 'bg-amber-50 text-amber-700',
    showBanner: true,
    bannerType: 'warning',
    bannerMessage: 'Hồ sơ đang chờ ghế (đã xét, chưa có slot).',
    allowedActions: [],
  },
}

/**
 * Status dot color — màu chấm trạng thái cho redesign trang danh sách hồ sơ.
 *
 * Co-located với ADMISSION_STATUS_CONFIG để giữ SINGLE SOURCE (status →
 * label/badge/dot ở cùng một module), tránh fork một map màu riêng trong
 * columns.tsx. Class PHẢI là literal static (Tailwind JIT không thấy chuỗi ghép).
 */
export const ADMISSION_STATUS_DOT_COLOR: Record<string, string> = {
  draft: 'bg-gray-400',
  submitted: 'bg-info-500',
  resubmitted: 'bg-info-600',
  reviewing: 'bg-sky-500',
  revision_requested: 'bg-orange-500',
  approved: 'bg-success-500',
  admitted: 'bg-green-500',
  overridden: 'bg-purple-500',
  waitlisted: 'bg-amber-500',
  confirmed: 'bg-emerald-500',
  enrolled: 'bg-blue-500',
  rejected: 'bg-error-500',
  withdrawn: 'bg-gray-400',
  withdrawal_pending: 'bg-amber-500',
  result_published: 'bg-sky-500',
}

/** Lấy class màu chấm cho 1 admission status (fallback xám trung tính). */
export function getStatusDotColor(status: string): string {
  return ADMISSION_STATUS_DOT_COLOR[status] ?? 'bg-gray-400'
}

// =============================================================================
// INVOICE STATUS CONFIG (Finance — "Thu học phí" workspace)
// =============================================================================

/**
 * Invoice status UI config — label + badge styling per enum status. Mirrors the
 * ADMISSION_STATUS_CONFIG pattern so the finance list shares one status source.
 * 6 enum values: draft / issued / partial / paid / cancelled / overdue.
 */
export const INVOICE_STATUS_CONFIG: Record<string, StatusUIConfig> = {
  draft: {
    label: 'Nháp',
    badgeVariant: 'secondary',
    badgeColor: 'bg-muted text-muted-foreground',
    showBanner: false,
    allowedActions: ['issue', 'cancel'],
  },
  issued: {
    label: 'Chờ thu',
    badgeVariant: 'outline',
    badgeColor: 'bg-info-100 text-info-700',
    showBanner: false,
    allowedActions: ['record_payment', 'cancel'],
  },
  partial: {
    label: 'Thu một phần',
    badgeVariant: 'default',
    badgeColor: 'bg-amber-100 text-amber-700',
    showBanner: false,
    allowedActions: ['record_payment'],
  },
  paid: {
    label: 'Đã thu đủ',
    badgeVariant: 'default',
    badgeColor: 'bg-emerald-100 text-emerald-700',
    showBanner: false,
    allowedActions: [],
  },
  cancelled: {
    label: 'Đã hủy',
    badgeVariant: 'secondary',
    badgeColor: 'bg-muted text-muted-foreground',
    showBanner: false,
    allowedActions: [],
  },
  overdue: {
    label: 'Quá hạn',
    badgeVariant: 'destructive',
    badgeColor: 'bg-error-100 text-error-700',
    showBanner: false,
    allowedActions: ['record_payment', 'apply_penalty'],
  },
}

/**
 * Status dot color cho danh sách hóa đơn (chấm trạng thái). Class PHẢI là literal
 * static (Tailwind JIT). overdue đỏ; còn lại theo enum.
 */
export const INVOICE_STATUS_DOT_COLOR: Record<string, string> = {
  draft: 'bg-gray-400',
  issued: 'bg-info-500',
  partial: 'bg-amber-500',
  paid: 'bg-emerald-500',
  cancelled: 'bg-gray-400',
  overdue: 'bg-error-500',
}

/** Lấy class màu chấm cho 1 invoice status (fallback xám trung tính). */
export function getInvoiceStatusDotColor(status: string): string {
  return INVOICE_STATUS_DOT_COLOR[status] ?? 'bg-gray-400'
}

/**
 * Status SPINE color — viền-trái `border-l-2` của mỗi dòng hóa đơn (mockup
 * signature "vệt màu quét cả màn"). 6 enum: issued=info · partial=amber ·
 * paid=emerald · draft+cancelled=xám. `is_overdue` ĐỎ override xử lý ở call site
 * (getInvoiceStatusSpineColor nhận cờ overdue). Class literal static.
 */
export const INVOICE_STATUS_SPINE_COLOR: Record<string, string> = {
  draft: 'border-l-gray-300',
  issued: 'border-l-info-500',
  partial: 'border-l-amber-500',
  paid: 'border-l-emerald-500',
  cancelled: 'border-l-gray-300',
  overdue: 'border-l-error-500',
}

/**
 * Class màu spine (border-left) cho 1 dòng hóa đơn.
 *
 * `isOverdue` (backend-owned) → ĐỎ override KỂ CẢ khi enum vẫn là issued/partial
 * — đây là nguồn DUY NHẤT cho vệt đỏ, khớp status-pill/tab/overdue_derived.
 */
export function getInvoiceStatusSpineColor(status: string, isOverdue?: boolean): string {
  if (isOverdue) return 'border-l-error-500'
  return INVOICE_STATUS_SPINE_COLOR[status] ?? 'border-l-gray-300'
}

// =============================================================================
// LEAD STATUS CONFIG (for future use)
// =============================================================================

export const LEAD_STATUS_CONFIG: Record<string, StatusUIConfig> = {
  new: {
    label: 'Mới',
    badgeVariant: 'default',
    badgeColor: 'bg-info-100 text-info-700',
    showBanner: false,
    allowedActions: ['contact', 'assign'],
  },
  contacted: {
    label: 'Đã liên hệ',
    badgeVariant: 'secondary',
    badgeColor: 'bg-warning-100 text-warning-700',
    showBanner: false,
    allowedActions: ['follow_up', 'convert'],
  },
  qualified: {
    label: 'Đủ điều kiện',
    badgeVariant: 'default',
    badgeColor: 'bg-success-100 text-success-700',
    showBanner: false,
    allowedActions: ['convert'],
  },
  converted: {
    label: 'Đã chuyển đổi',
    badgeVariant: 'default',
    badgeColor: 'bg-purple-100 text-purple-700',
    showBanner: false,
    allowedActions: [],
  },
  lost: {
    label: 'Mất',
    badgeVariant: 'destructive',
    badgeColor: 'bg-error-100 text-error-700',
    showBanner: false,
    allowedActions: ['reactivate'],
  },
}

// =============================================================================
// FALLBACK & HELPER FUNCTIONS
// =============================================================================

/** Fallback config for unknown statuses (future-proofing) */
export const DEFAULT_STATUS_CONFIG: StatusUIConfig = {
  label: 'Không xác định',
  badgeVariant: 'outline',
  badgeColor: 'bg-muted text-muted-foreground',
  showBanner: false,
  allowedActions: [],
}

export type ModuleType = 'admission' | 'lead'

const MODULE_CONFIGS: Record<ModuleType, Record<string, StatusUIConfig>> = {
  admission: ADMISSION_STATUS_CONFIG,
  lead: LEAD_STATUS_CONFIG,
}

/**
 * Get UI configuration for a specific status.
 * 
 * @param status - Backend status value
 * @param module - Module type (default: 'admission')
 * @returns StatusUIConfig with display settings
 * 
 * @example
 * const config = getStatusConfig('submitted')
 * <Badge className={config.badgeColor}>{config.label}</Badge>
 */
export function getStatusConfig(
  status: string, 
  module: ModuleType = 'admission'
): StatusUIConfig {
  const configs = MODULE_CONFIGS[module]
  return configs[status] ?? { ...DEFAULT_STATUS_CONFIG, label: status }
}

/**
 * Get toast type for mutation success based on new status.
 * 
 * @param status - New status after mutation
 * @returns Toast method name: 'success' | 'info' | 'warning' | 'error'
 */
export function getToastTypeForStatus(status: string): 'success' | 'info' | 'warning' | 'error' {
  const config = getStatusConfig(status)
  return config.bannerType ?? 'info'
}
