/**
 * STATUS BADGE CONFIGURATION
 *
 * Single source of truth for status → badge mapping.
 * Uses semantic tokens from admission.css for consistent theming.
 *
 * Usage:
 *   const config = getStatusBadgeConfig('approved', 'admission')
 *   <StatusBadge status="approved" module="admission" />
 *
 * @see UI_RULEBOOK.md for design guidelines
 */

import {
  FileText,
  Send,
  Clock,
  CheckCircle,
  XCircle,
  GraduationCap,
  UserPlus,
  Phone,
  Target,
  UserCheck,
  UserX,
  TrendingUp,
  TrendingDown,
  Minus,
  AlertCircle,
  AlertTriangle,
  Shield,
  LogOut,
  type LucideIcon,
} from "lucide-react";

// =============================================================================
// TYPES
// =============================================================================

export type AdmissionStatus =
  | "draft"
  | "submitted"
  | "resubmitted"
  | "reviewing"
  | "approved"
  | "rejected"
  | "revision_requested"
  | "confirmed"
  | "overridden"
  | "enrolled"
  | "withdrawn";

export type LeadStatus =
  | "new"
  | "assigned"
  | "contacted"
  | "qualified"
  | "unqualified"
  | "converted"
  | "rejected";

export type ScoreLevel =
  | "excellent"
  | "good"
  | "average"
  | "poor";

export type OutcomeType =
  | "positive"
  | "neutral"
  | "negative";

export type StatusModule = "admission" | "lead" | "score" | "outcome";

export interface StatusBadgeConfig {
  /** Display label (Vietnamese) */
  label: string;
  /** Short label for compact views */
  shortLabel?: string;
  /** Icon component */
  icon: LucideIcon;
  /** Semantic color classes (uses CSS tokens) */
  className: string;
  /** Badge variant for shadcn */
  variant: "default" | "secondary" | "destructive" | "outline";
  /** Description for tooltips */
  description?: string;
  /** Sort order for display */
  order: number;
}

// =============================================================================
// ADMISSION STATUS BADGES
// =============================================================================

export const ADMISSION_BADGE_CONFIG: Record<AdmissionStatus, StatusBadgeConfig> = {
  draft: {
    label: "Nháp",
    shortLabel: "Nháp",
    icon: FileText,
    className: "bg-admission-draft-bg text-admission-draft-fg border-admission-draft-border",
    variant: "secondary",
    description: "Hồ sơ đang được soạn thảo",
    order: 1,
  },
  submitted: {
    label: "Đã nộp",
    shortLabel: "Đã nộp",
    icon: Send,
    className: "bg-admission-submitted-bg text-admission-submitted-fg border-admission-submitted-border",
    variant: "default",
    description: "Hồ sơ đang chờ xét duyệt",
    order: 2,
  },
  resubmitted: {
    label: "Nộp lại",
    shortLabel: "Nộp lại",
    icon: Send,
    className: "bg-admission-submitted-bg text-admission-submitted-fg border-admission-submitted-border",
    variant: "default",
    description: "Hồ sơ đã được nộp lại sau chỉnh sửa",
    order: 3,
  },
  reviewing: {
    label: "Đang xét",
    shortLabel: "Đang xét",
    icon: Clock,
    className: "bg-admission-reviewing-bg text-admission-reviewing-fg border-admission-reviewing-border",
    variant: "default",
    description: "Hồ sơ đang được xét duyệt",
    order: 4,
  },
  approved: {
    label: "Đã duyệt",
    shortLabel: "Duyệt",
    icon: CheckCircle,
    className: "bg-admission-approved-bg text-admission-approved-fg border-admission-approved-border",
    variant: "default",
    description: "Hồ sơ đã được phê duyệt",
    order: 5,
  },
  rejected: {
    label: "Từ chối",
    shortLabel: "Từ chối",
    icon: XCircle,
    className: "bg-admission-rejected-bg text-admission-rejected-fg border-admission-rejected-border",
    variant: "destructive",
    description: "Hồ sơ bị từ chối, cần chỉnh sửa",
    order: 6,
  },
  revision_requested: {
    label: "Yêu cầu bổ sung",
    shortLabel: "Bổ sung",
    icon: AlertTriangle,
    className: "bg-orange-50 text-orange-700 border-orange-200",
    variant: "outline",
    description: "Hồ sơ cần bổ sung thêm tài liệu/thông tin",
    order: 7,
  },
  confirmed: {
    label: "Đã xác nhận",
    shortLabel: "Xác nhận",
    icon: CheckCircle,
    className: "bg-emerald-50 text-emerald-700 border-emerald-200",
    variant: "default",
    description: "Hồ sơ đã được xác nhận bởi thí sinh",
    order: 8,
  },
  overridden: {
    label: "Đã override",
    shortLabel: "Override",
    icon: Shield,
    className: "bg-purple-50 text-purple-700 border-purple-200",
    variant: "default",
    description: "Hồ sơ đã được admin override",
    order: 9,
  },
  enrolled: {
    label: "Đã nhập học",
    shortLabel: "Nhập học",
    icon: GraduationCap,
    className: "bg-admission-enrolled-bg text-admission-enrolled-fg border-admission-enrolled-border",
    variant: "default",
    description: "Thí sinh đã hoàn tất nhập học",
    order: 10,
  },
  withdrawn: {
    label: "Đã rút hồ sơ",
    shortLabel: "Rút",
    icon: LogOut,
    className: "bg-muted text-muted-foreground border-border",
    variant: "secondary",
    description: "Hồ sơ đã được rút lại",
    order: 11,
  },
};

// =============================================================================
// LEAD STATUS BADGES
// =============================================================================

export const LEAD_BADGE_CONFIG: Record<LeadStatus, StatusBadgeConfig> = {
  new: {
    label: "Mới",
    shortLabel: "Mới",
    icon: UserPlus,
    className: "bg-lead-new-bg text-lead-new-fg",
    variant: "default",
    description: "Lead mới chưa được xử lý",
    order: 1,
  },
  assigned: {
    label: "Đã phân công",
    shortLabel: "Phân công",
    icon: UserCheck,
    className: "bg-lead-contacted-bg text-lead-contacted-fg",
    variant: "secondary",
    description: "Đã phân công cho tư vấn viên",
    order: 2,
  },
  contacted: {
    label: "Đã liên hệ",
    shortLabel: "Liên hệ",
    icon: Phone,
    className: "bg-lead-contacted-bg text-lead-contacted-fg",
    variant: "secondary",
    description: "Đã liên hệ với lead",
    order: 3,
  },
  qualified: {
    label: "Đủ điều kiện",
    shortLabel: "Đủ ĐK",
    icon: Target,
    className: "bg-lead-qualified-bg text-lead-qualified-fg",
    variant: "default",
    description: "Lead đủ điều kiện chuyển đổi",
    order: 4,
  },
  unqualified: {
    label: "Không đủ ĐK",
    shortLabel: "Không ĐK",
    icon: UserX,
    className: "bg-lead-lost-bg text-lead-lost-fg",
    variant: "secondary",
    description: "Lead không đủ điều kiện",
    order: 5,
  },
  converted: {
    label: "Đã chuyển đổi",
    shortLabel: "Chuyển đổi",
    icon: GraduationCap,
    className: "bg-lead-converted-bg text-lead-converted-fg",
    variant: "default",
    description: "Đã chuyển đổi thành sinh viên",
    order: 6,
  },
  rejected: {
    label: "Đã từ chối",
    shortLabel: "Từ chối",
    icon: XCircle,
    className: "bg-admission-rejected-bg text-admission-rejected-fg",
    variant: "destructive",
    description: "Lead bị từ chối",
    order: 7,
  },
};

// =============================================================================
// SCORE LEVEL BADGES
// =============================================================================

export const SCORE_BADGE_CONFIG: Record<ScoreLevel, StatusBadgeConfig> = {
  excellent: {
    label: "Xuất sắc",
    shortLabel: "Xuất sắc",
    icon: TrendingUp,
    className: "bg-score-excellent-bg text-score-excellent-fg",
    variant: "default",
    description: "Điểm số xuất sắc (≥90%)",
    order: 1,
  },
  good: {
    label: "Tốt",
    shortLabel: "Tốt",
    icon: CheckCircle,
    className: "bg-score-good-bg text-score-good-fg",
    variant: "default",
    description: "Điểm số tốt (70-89%)",
    order: 2,
  },
  average: {
    label: "Trung bình",
    shortLabel: "TB",
    icon: Minus,
    className: "bg-score-average-bg text-score-average-fg",
    variant: "secondary",
    description: "Điểm số trung bình (50-69%)",
    order: 3,
  },
  poor: {
    label: "Yếu",
    shortLabel: "Yếu",
    icon: TrendingDown,
    className: "bg-score-poor-bg text-score-poor-fg",
    variant: "destructive",
    description: "Điểm số yếu (<50%)",
    order: 4,
  },
};

// =============================================================================
// OUTCOME TYPE BADGES
// =============================================================================

export const OUTCOME_BADGE_CONFIG: Record<OutcomeType, StatusBadgeConfig> = {
  positive: {
    label: "Tích cực",
    shortLabel: "+",
    icon: TrendingUp,
    className: "bg-admission-approved-bg text-admission-approved-fg",
    variant: "default",
    description: "Kết quả tích cực",
    order: 1,
  },
  neutral: {
    label: "Trung lập",
    shortLabel: "~",
    icon: Minus,
    className: "bg-admission-draft-bg text-admission-draft-fg",
    variant: "secondary",
    description: "Cần theo dõi thêm",
    order: 2,
  },
  negative: {
    label: "Tiêu cực",
    shortLabel: "-",
    icon: TrendingDown,
    className: "bg-admission-rejected-bg text-admission-rejected-fg",
    variant: "destructive",
    description: "Kết quả tiêu cực",
    order: 3,
  },
};

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

const MODULE_CONFIGS = {
  admission: ADMISSION_BADGE_CONFIG,
  lead: LEAD_BADGE_CONFIG,
  score: SCORE_BADGE_CONFIG,
  outcome: OUTCOME_BADGE_CONFIG,
} as const;

/** Default config for unknown statuses */
export const DEFAULT_BADGE_CONFIG: StatusBadgeConfig = {
  label: "Không xác định",
  icon: AlertCircle,
  className: "bg-muted text-muted-foreground",
  variant: "outline",
  order: 999,
};

/**
 * Get badge configuration for a status
 *
 * @example
 * const config = getStatusBadgeConfig('approved', 'admission')
 * <Badge className={config.className}>
 *   <config.icon className="h-3 w-3 mr-1" />
 *   {config.label}
 * </Badge>
 */
export function getStatusBadgeConfig(
  status: string,
  module: StatusModule = "admission"
): StatusBadgeConfig {
  const configs = MODULE_CONFIGS[module] as Record<string, StatusBadgeConfig>;
  return configs[status] ?? { ...DEFAULT_BADGE_CONFIG, label: status };
}

/**
 * Get all statuses for a module (sorted by order)
 */
export function getAllStatuses(module: StatusModule): Array<{ value: string; config: StatusBadgeConfig }> {
  const configs = MODULE_CONFIGS[module] as Record<string, StatusBadgeConfig>;
  return Object.entries(configs)
    .map(([value, config]) => ({ value, config }))
    .sort((a, b) => a.config.order - b.config.order);
}

/**
 * Calculate score level from percentage
 */
export function getScoreLevel(percentage: number): ScoreLevel {
  if (percentage >= 90) return "excellent";
  if (percentage >= 70) return "good";
  if (percentage >= 50) return "average";
  return "poor";
}
