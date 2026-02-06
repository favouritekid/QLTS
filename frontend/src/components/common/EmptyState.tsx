// src/components/common/EmptyState.tsx
/**
 * EmptyState - Generic reusable empty state component
 *
 * Provides consistent empty state UI across the application.
 * Supports multiple variants for different contexts.
 *
 * @example
 * ```tsx
 * // Basic usage
 * <EmptyState
 *   icon={<Inbox className="h-12 w-12" />}
 *   title="No items yet"
 *   description="Create your first item to get started"
 * />
 *
 * // With action
 * <EmptyState
 *   icon={<Users />}
 *   title="No users found"
 *   description="Add users to your team"
 *   action={<Button>Add User</Button>}
 * />
 *
 * // Search/Filter empty
 * <EmptyState
 *   variant="search"
 *   title="No results"
 *   description="Try different search terms"
 *   action={<Button variant="outline" onClick={onReset}>Clear filters</Button>}
 * />
 * ```
 */

"use client";

import React from "react";
import { Inbox, SearchX, AlertCircle, FileX, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

export type EmptyStateVariant = "default" | "search" | "error" | "minimal";

export interface EmptyStateProps {
  /** Custom icon to display */
  icon?: React.ReactNode;
  /** Title text */
  title: string;
  /** Description text */
  description?: string;
  /** Action button(s) */
  action?: React.ReactNode;
  /** Visual variant */
  variant?: EmptyStateVariant;
  /** Additional class name */
  className?: string;
  /** Icon size - applies to default icons only */
  iconSize?: "sm" | "md" | "lg";
}

// =============================================================================
// DEFAULT ICONS BY VARIANT
// =============================================================================

const variantIcons: Record<EmptyStateVariant, React.ReactNode> = {
  default: <Inbox className="h-12 w-12" />,
  search: <SearchX className="h-12 w-12" />,
  error: <AlertCircle className="h-12 w-12" />,
  minimal: <FileX className="h-10 w-10" />,
};

const variantStyles: Record<EmptyStateVariant, { iconBg: string; iconColor: string }> = {
  default: {
    iconBg: "bg-primary/10",
    iconColor: "text-primary",
  },
  search: {
    iconBg: "bg-muted",
    iconColor: "text-muted-foreground",
  },
  error: {
    iconBg: "bg-destructive/10",
    iconColor: "text-destructive",
  },
  minimal: {
    iconBg: "bg-muted/50",
    iconColor: "text-muted-foreground",
  },
};

const iconSizeClasses = {
  sm: "p-3",
  md: "p-4",
  lg: "p-5",
};

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function EmptyState({
  icon,
  title,
  description,
  action,
  variant = "default",
  className,
  iconSize = "md",
}: EmptyStateProps) {
  const styles = variantStyles[variant];
  const defaultIcon = variantIcons[variant];
  const displayIcon = icon || defaultIcon;

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-4 py-12 px-4",
        className
      )}
    >
      {/* Icon */}
      <div
        className={cn(
          "rounded-full",
          iconSizeClasses[iconSize],
          styles.iconBg
        )}
      >
        <div className={styles.iconColor}>{displayIcon}</div>
      </div>

      {/* Text Content */}
      <div className="text-center space-y-1 max-w-sm">
        <h3 className="font-semibold text-foreground">{title}</h3>
        {description && (
          <p className="text-muted-foreground text-sm">{description}</p>
        )}
      </div>

      {/* Action */}
      {action && <div className="flex items-center gap-2 mt-2">{action}</div>}
    </div>
  );
}

// =============================================================================
// PRESET VARIANTS
// =============================================================================

/**
 * SearchEmptyState - For filtered/searched results with no matches
 */
export function SearchEmptyState({
  searchQuery,
  onReset,
  className,
}: {
  searchQuery?: string;
  onReset?: () => void;
  className?: string;
}) {
  return (
    <EmptyState
      variant="search"
      title="Không tìm thấy kết quả"
      description={
        searchQuery
          ? `Không có kết quả khớp với "${searchQuery}"`
          : "Không có dữ liệu khớp với bộ lọc hiện tại"
      }
      action={
        onReset && (
          <Button variant="outline" size="sm" onClick={onReset}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Xóa bộ lọc
          </Button>
        )
      }
      className={className}
    />
  );
}

/**
 * ErrorEmptyState - For error scenarios
 */
export function ErrorEmptyState({
  message,
  onRetry,
  className,
}: {
  message?: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <EmptyState
      variant="error"
      title="Có lỗi xảy ra"
      description={message || "Không thể tải dữ liệu. Vui lòng thử lại."}
      action={
        onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Thử lại
          </Button>
        )
      }
      className={className}
    />
  );
}

/**
 * TableEmptyState - Minimal variant for inside tables
 */
export function TableEmptyState({
  title = "Chưa có dữ liệu",
  description,
  className,
}: {
  title?: string;
  description?: string;
  className?: string;
}) {
  return (
    <EmptyState
      variant="minimal"
      iconSize="sm"
      title={title}
      description={description}
      className={cn("py-8", className)}
    />
  );
}

export default EmptyState;
