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
    badgeColor: 'bg-gray-100 text-gray-700',
    showBanner: false,
    allowedActions: ['save', 'submit'],
  },
  submitted: {
    label: 'Chờ duyệt',
    badgeVariant: 'default',
    badgeColor: 'bg-blue-100 text-blue-700',
    showBanner: true,
    bannerType: 'info',
    bannerMessage: 'Hồ sơ đang chờ xét duyệt',
    allowedActions: [],
  },
  resubmitted: {
    label: 'Đã nộp lại',
    badgeVariant: 'default',
    badgeColor: 'bg-blue-100 text-blue-700',
    showBanner: true,
    bannerType: 'info',
    bannerMessage: 'Hồ sơ đã được nộp lại và đang chờ xét duyệt',
    allowedActions: [],
  },
  approved: {
    label: 'Đã duyệt',
    badgeVariant: 'default',
    badgeColor: 'bg-green-100 text-green-700',
    showBanner: true,
    bannerType: 'success',
    bannerMessage: 'Hồ sơ đã được phê duyệt',
    allowedActions: ['enroll'],
  },
  rejected: {
    label: 'Từ chối',
    badgeVariant: 'destructive',
    badgeColor: 'bg-red-100 text-red-700',
    showBanner: true,
    bannerType: 'warning',
    bannerMessage: 'Hồ sơ bị từ chối. Vui lòng chỉnh sửa và nộp lại.',
    allowedActions: ['edit', 'resubmit'],
  },
  enrolled: {
    label: 'Đã nhập học',
    badgeVariant: 'default',
    badgeColor: 'bg-purple-100 text-purple-700',
    showBanner: false,
    allowedActions: [],
  },
}

// =============================================================================
// LEAD STATUS CONFIG (for future use)
// =============================================================================

export const LEAD_STATUS_CONFIG: Record<string, StatusUIConfig> = {
  new: {
    label: 'Mới',
    badgeVariant: 'default',
    badgeColor: 'bg-blue-100 text-blue-700',
    showBanner: false,
    allowedActions: ['contact', 'assign'],
  },
  contacted: {
    label: 'Đã liên hệ',
    badgeVariant: 'secondary',
    badgeColor: 'bg-yellow-100 text-yellow-700',
    showBanner: false,
    allowedActions: ['follow_up', 'convert'],
  },
  qualified: {
    label: 'Đủ điều kiện',
    badgeVariant: 'default',
    badgeColor: 'bg-green-100 text-green-700',
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
    badgeColor: 'bg-red-100 text-red-700',
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
  badgeColor: 'bg-gray-100 text-gray-600',
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
