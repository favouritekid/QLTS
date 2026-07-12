// src/components/common/status/StatusBadge.tsx
"use client";

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import {
  getStatusBadgeConfig,
  type StatusModule,
} from "@/lib/ui-config/status-badge.config";

// =============================================================================
// VARIANT DEFINITIONS
// =============================================================================

const statusBadgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        // Semantic variants (using CSS tokens)
        success: "bg-success-100 text-success-700 dark:bg-success-500/20 dark:text-success-500",
        warning: "bg-warning-100 text-warning-700 dark:bg-warning-500/20 dark:text-warning-500",
        danger: "bg-error-100 text-error-700 dark:bg-error-500/20 dark:text-error-500",
        info: "bg-info-100 text-info-700 dark:bg-info-500/20 dark:text-info-500",
        neutral: "bg-muted text-muted-foreground dark:bg-muted dark:text-muted-foreground",
        primary: "bg-primary/10 text-primary dark:bg-primary/20",
        secondary: "bg-secondary text-secondary-foreground",

        // Semantic variants (using CSS tokens) - NEW
        "admission-draft": "bg-admission-draft-bg text-admission-draft-fg border border-admission-draft-border",
        "admission-submitted": "bg-admission-submitted-bg text-admission-submitted-fg border border-admission-submitted-border",
        "admission-reviewing": "bg-admission-reviewing-bg text-admission-reviewing-fg border border-admission-reviewing-border",
        "admission-approved": "bg-admission-approved-bg text-admission-approved-fg border border-admission-approved-border",
        "admission-rejected": "bg-admission-rejected-bg text-admission-rejected-fg border border-admission-rejected-border",
        "admission-enrolled": "bg-admission-enrolled-bg text-admission-enrolled-fg border border-admission-enrolled-border",

        "lead-new": "bg-lead-new-bg text-lead-new-fg",
        "lead-contacted": "bg-lead-contacted-bg text-lead-contacted-fg",
        "lead-qualified": "bg-lead-qualified-bg text-lead-qualified-fg",
        "lead-converted": "bg-lead-converted-bg text-lead-converted-fg",
        "lead-lost": "bg-lead-lost-bg text-lead-lost-fg",

        "score-excellent": "bg-score-excellent-bg text-score-excellent-fg",
        "score-good": "bg-score-good-bg text-score-good-fg",
        "score-average": "bg-score-average-bg text-score-average-fg",
        "score-poor": "bg-score-poor-bg text-score-poor-fg",
      },
      size: {
        sm: "text-[10px] px-2 py-0.5",
        md: "text-xs px-2.5 py-0.5",
        lg: "text-sm px-3 py-1",
      },
    },
    defaultVariants: {
      variant: "neutral",
      size: "md",
    },
  }
);

// =============================================================================
// TYPES
// =============================================================================

export type StatusVariant =
  | "success" | "warning" | "danger" | "info" | "neutral" | "primary" | "secondary"
  // Semantic variants
  | "admission-draft" | "admission-submitted" | "admission-reviewing"
  | "admission-approved" | "admission-rejected" | "admission-enrolled"
  | "lead-new" | "lead-contacted" | "lead-qualified" | "lead-converted" | "lead-lost"
  | "score-excellent" | "score-good" | "score-average" | "score-poor";

export interface StatusConfig {
  label: string;
  variant: StatusVariant;
  icon?: React.ReactNode;
}

export interface StatusBadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof statusBadgeVariants> {
  /** Status variant */
  variant?: StatusVariant;
  /** Optional icon */
  icon?: React.ReactNode;
  /** Show dot indicator instead of icon */
  showDot?: boolean;
  /** Children (label text) */
  children: React.ReactNode;
}

// =============================================================================
// STATUS MAPPINGS (for common use cases)
// =============================================================================

/**
 * Pre-defined status mappings for common scenarios
 */
export const LEAD_STATUS_MAP: Record<string, StatusConfig> = {
  new: { label: "Mới", variant: "lead-new" },
  assigned: { label: "Đã gán", variant: "lead-contacted" },
  contacted: { label: "Đã liên hệ", variant: "lead-contacted" },
  qualified: { label: "Đủ điều kiện", variant: "lead-qualified" },
  unqualified: { label: "Không đủ ĐK", variant: "lead-lost" },
  converted: { label: "Đã chuyển đổi", variant: "lead-converted" },
  rejected: { label: "Từ chối", variant: "admission-rejected" },
};

export const ADMISSION_STATUS_MAP: Record<string, StatusConfig> = {
  draft: { label: "Nháp", variant: "admission-draft" },
  submitted: { label: "Đã nộp", variant: "admission-submitted" },
  resubmitted: { label: "Nộp lại", variant: "admission-submitted" },
  reviewing: { label: "Đang xét", variant: "admission-reviewing" },
  approved: { label: "Đã duyệt", variant: "admission-approved" },
  // phase1_11 (#184 Wave 3 PR-3A) — 3 new states. ``admitted``
  // shares ``admission-approved`` variant since it's a positive
  // admission outcome via choice engine. ``waitlisted`` uses
  // warning (chờ slot). ``result_published`` uses info (broadcast
  // marker). All 3 also have detailed config in
  // ``status-badge.config.ts:ADMISSION_BADGE_CONFIG`` —
  // AdmissionBadge component reads from that source. This map is
  // the simpler StatusFromMap fallback path.
  admitted: { label: "Đậu", variant: "admission-approved" },
  waitlisted: { label: "Chờ ghế", variant: "warning" },
  result_published: { label: "Đã công bố KQ", variant: "info" },
  rejected: { label: "Từ chối", variant: "admission-rejected" },
  revision_requested: { label: "Yêu cầu bổ sung", variant: "warning" },
  confirmed: { label: "Đã xác nhận", variant: "success" },
  overridden: { label: "Đã override", variant: "primary" },
  enrolled: { label: "Đã nhập học", variant: "admission-enrolled" },
  withdrawn: { label: "Đã rút hồ sơ", variant: "neutral" },
  withdrawal_pending: { label: "Chờ hoàn để rút", variant: "warning" },
};

export const SCORE_LEVEL_MAP: Record<string, StatusConfig> = {
  excellent: { label: "Xuất sắc", variant: "score-excellent" },
  good: { label: "Tốt", variant: "score-good" },
  average: { label: "Trung bình", variant: "score-average" },
  poor: { label: "Yếu", variant: "score-poor" },
};

export const PAYMENT_STATUS_MAP: Record<string, StatusConfig> = {
  pending: { label: "Chờ xử lý", variant: "warning" },
  processing: { label: "Đang xử lý", variant: "info" },
  completed: { label: "Hoàn thành", variant: "success" },
  failed: { label: "Thất bại", variant: "danger" },
  refunded: { label: "Đã hoàn tiền", variant: "neutral" },
};

export const CONSULTATION_STATUS_MAP: Record<string, StatusConfig> = {
  scheduled: { label: "Đã hẹn", variant: "info" },
  in_progress: { label: "Đang tư vấn", variant: "warning" },
  completed: { label: "Hoàn thành", variant: "success" },
  cancelled: { label: "Đã hủy", variant: "danger" },
  no_show: { label: "Vắng mặt", variant: "neutral" },
};

export const ACTIVE_STATUS_MAP: Record<string, StatusConfig> = {
  active: { label: "Hoạt động", variant: "success" },
  inactive: { label: "Không hoạt động", variant: "neutral" },
  suspended: { label: "Tạm ngưng", variant: "warning" },
  deleted: { label: "Đã xóa", variant: "danger" },
};

// =============================================================================
// HELPER FUNCTION
// =============================================================================

/**
 * Get status config from a map based on status value
 */
export function getStatusConfig(
  status: string,
  statusMap: Record<string, StatusConfig>,
  fallback: StatusConfig = { label: status, variant: "neutral" }
): StatusConfig {
  return statusMap[status.toLowerCase()] || fallback;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function StatusBadge({
  variant = "neutral",
  size,
  icon,
  showDot = false,
  className,
  children,
  ...props
}: StatusBadgeProps) {
  return (
    <span className={cn(statusBadgeVariants({ variant, size }), className)} {...props}>
      {/* Dot indicator */}
      {showDot && !icon && (
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            variant === "success" && "bg-success-500",
            variant === "warning" && "bg-warning-500",
            variant === "danger" && "bg-error-500",
            variant === "info" && "bg-info-500",
            variant === "neutral" && "bg-muted-foreground",
            variant === "primary" && "bg-primary",
            variant === "secondary" && "bg-secondary-foreground",
            // Semantic variants use currentColor
            variant.startsWith("admission-") && "bg-current opacity-70",
            variant.startsWith("lead-") && "bg-current opacity-70",
            variant.startsWith("score-") && "bg-current opacity-70"
          )}
        />
      )}

      {/* Custom icon */}
      {icon && <span className="shrink-0">{icon}</span>}

      {/* Label */}
      {children}
    </span>
  );
}

// =============================================================================
// CONVENIENCE COMPONENTS
// =============================================================================

export interface StatusFromMapProps extends Omit<StatusBadgeProps, "children" | "variant"> {
  /** Status value to look up */
  status: string;
  /** Status map to use for lookup */
  statusMap: Record<string, StatusConfig>;
  /** Fallback config if status not found */
  fallback?: StatusConfig;
}

/**
 * StatusBadge that automatically resolves status from a map
 */
export function StatusFromMap({
  status,
  statusMap,
  fallback,
  ...props
}: StatusFromMapProps) {
  const config = getStatusConfig(status, statusMap, fallback);

  return (
    <StatusBadge variant={config.variant} icon={config.icon} {...props}>
      {config.label}
    </StatusBadge>
  );
}

// =============================================================================
// SEMANTIC BADGE COMPONENTS (NEW - using config system)
// =============================================================================

interface SemanticBadgeProps extends Omit<StatusBadgeProps, "children" | "variant"> {
  /** Status value from backend */
  status: string;
  /** Use compact label */
  compact?: boolean;
}

/**
 * Admission status badge using semantic tokens
 * @example <AdmissionBadge status="approved" />
 */
export function AdmissionBadge({ status, compact, showDot, ...props }: SemanticBadgeProps) {
  const config = getStatusBadgeConfig(status, "admission");
  const Icon = config.icon;
  const label = compact ? (config.shortLabel ?? config.label) : config.label;

  return (
    <StatusBadge
      variant={`admission-${status}` as StatusVariant}
      icon={!showDot && Icon ? <Icon className="h-3 w-3" /> : undefined}
      showDot={showDot}
      {...props}
    >
      {label}
    </StatusBadge>
  );
}

/**
 * Lead status badge using semantic tokens
 * @example <LeadBadge status="qualified" />
 */
export function LeadBadge({ status, compact, showDot, ...props }: SemanticBadgeProps) {
  const config = getStatusBadgeConfig(status, "lead");
  const Icon = config.icon;
  const label = compact ? (config.shortLabel ?? config.label) : config.label;

  // Map to closest semantic variant
  const variantMap: Record<string, StatusVariant> = {
    new: "lead-new",
    assigned: "lead-contacted",
    contacted: "lead-contacted",
    qualified: "lead-qualified",
    unqualified: "lead-lost",
    converted: "lead-converted",
    rejected: "admission-rejected",
  };

  return (
    <StatusBadge
      variant={variantMap[status] ?? "neutral"}
      icon={!showDot && Icon ? <Icon className="h-3 w-3" /> : undefined}
      showDot={showDot}
      {...props}
    >
      {label}
    </StatusBadge>
  );
}

/**
 * Score level badge using semantic tokens
 * @example <ScoreLevelBadge level="excellent" />
 */
export function ScoreLevelBadge({
  level,
  compact,
  showDot,
  ...props
}: Omit<SemanticBadgeProps, "status"> & { level: string }) {
  const config = getStatusBadgeConfig(level, "score");
  const Icon = config.icon;
  const label = compact ? (config.shortLabel ?? config.label) : config.label;

  return (
    <StatusBadge
      variant={`score-${level}` as StatusVariant}
      icon={!showDot && Icon ? <Icon className="h-3 w-3" /> : undefined}
      showDot={showDot}
      {...props}
    >
      {label}
    </StatusBadge>
  );
}

export default StatusBadge;
