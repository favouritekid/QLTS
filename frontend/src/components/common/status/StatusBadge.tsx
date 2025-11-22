// src/components/common/status/StatusBadge.tsx
"use client";

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

// =============================================================================
// VARIANT DEFINITIONS
// =============================================================================

const statusBadgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        success: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
        warning: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400",
        danger: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
        info: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400",
        neutral: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-400",
        primary: "bg-primary/10 text-primary dark:bg-primary/20",
        secondary: "bg-secondary text-secondary-foreground",
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

export type StatusVariant = "success" | "warning" | "danger" | "info" | "neutral" | "primary" | "secondary";

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
  new: { label: "Moi", variant: "info" },
  assigned: { label: "Da gan", variant: "primary" },
  contacted: { label: "Da lien he", variant: "warning" },
  qualified: { label: "Du dieu kien", variant: "success" },
  unqualified: { label: "Khong du dieu kien", variant: "neutral" },
  converted: { label: "Da chuyen doi", variant: "success" },
  rejected: { label: "Tu choi", variant: "danger" },
};

export const PAYMENT_STATUS_MAP: Record<string, StatusConfig> = {
  pending: { label: "Cho xu ly", variant: "warning" },
  processing: { label: "Dang xu ly", variant: "info" },
  completed: { label: "Hoan thanh", variant: "success" },
  failed: { label: "That bai", variant: "danger" },
  refunded: { label: "Da hoan tien", variant: "neutral" },
};

export const CONSULTATION_STATUS_MAP: Record<string, StatusConfig> = {
  scheduled: { label: "Da hen", variant: "info" },
  in_progress: { label: "Dang tu van", variant: "warning" },
  completed: { label: "Hoan thanh", variant: "success" },
  cancelled: { label: "Da huy", variant: "danger" },
  no_show: { label: "Vang mat", variant: "neutral" },
};

export const ACTIVE_STATUS_MAP: Record<string, StatusConfig> = {
  active: { label: "Hoat dong", variant: "success" },
  inactive: { label: "Khong hoat dong", variant: "neutral" },
  suspended: { label: "Tam ngung", variant: "warning" },
  deleted: { label: "Da xoa", variant: "danger" },
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
            variant === "success" && "bg-green-500",
            variant === "warning" && "bg-yellow-500",
            variant === "danger" && "bg-red-500",
            variant === "info" && "bg-blue-500",
            variant === "neutral" && "bg-gray-500",
            variant === "primary" && "bg-primary",
            variant === "secondary" && "bg-secondary-foreground"
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
// CONVENIENCE COMPONENT
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

export default StatusBadge;
