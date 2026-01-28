// src/components/ui/dynamic-color-badge.tsx
/**
 * DynamicColorBadge - Badge component for database-driven colors
 *
 * Handles colors from API (status.color_code, stage colors) with:
 * - Automatic dark mode adjustments
 * - Proper text contrast
 * - XSS-safe color sanitization
 * - Consistent styling across the app
 *
 * @example
 * ```tsx
 * // Basic usage with API color
 * <DynamicColorBadge color={status.color_code}>
 *   {status.name}
 * </DynamicColorBadge>
 *
 * // Solid variant (colored background)
 * <DynamicColorBadge color={stage.color} variant="solid">
 *   {stage.name}
 * </DynamicColorBadge>
 *
 * // Dot indicator
 * <DynamicColorBadge color={status.color_code} variant="dot">
 *   {status.name}
 * </DynamicColorBadge>
 * ```
 */

"use client";

import React from "react";
import { useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";
import {
  sanitizeColor,
  getDynamicBadgeStyle,
  getDynamicSolidBadgeStyle,
  adjustForDarkMode,
  DEFAULT_COLOR,
} from "@/lib/utils/dynamic-color";

// =============================================================================
// TYPES
// =============================================================================

export type DynamicColorBadgeVariant = "outline" | "solid" | "dot" | "subtle";
export type DynamicColorBadgeSize = "sm" | "md" | "lg";

export interface DynamicColorBadgeProps {
  /** Dynamic color from API/database */
  color?: string | null;
  /** Badge content */
  children: React.ReactNode;
  /** Visual variant */
  variant?: DynamicColorBadgeVariant;
  /** Badge size */
  size?: DynamicColorBadgeSize;
  /** Additional CSS classes */
  className?: string;
  /** Fallback color if color is invalid */
  fallback?: string;
  /** Whether to show a colored dot indicator */
  showDot?: boolean;
  /** Custom icon to show before text */
  icon?: React.ReactNode;
}

// =============================================================================
// SIZE CONFIGURATIONS
// =============================================================================

const SIZE_STYLES: Record<DynamicColorBadgeSize, string> = {
  sm: "text-xs px-1.5 py-0.5 gap-1",
  md: "text-xs px-2 py-1 gap-1.5",
  lg: "text-sm px-2.5 py-1 gap-2",
};

const DOT_SIZES: Record<DynamicColorBadgeSize, string> = {
  sm: "h-1.5 w-1.5",
  md: "h-2 w-2",
  lg: "h-2.5 w-2.5",
};

// =============================================================================
// COMPONENT
// =============================================================================

export function DynamicColorBadge({
  color,
  children,
  variant = "subtle",
  size = "md",
  className,
  fallback = DEFAULT_COLOR,
  showDot = false,
  icon,
}: DynamicColorBadgeProps) {
  const { isDarkMode } = useTheme();

  // Sanitize the color
  const safeColor = sanitizeColor(color, fallback);

  // Generate styles based on variant
  const getStyles = (): React.CSSProperties => {
    switch (variant) {
      case "solid":
        return getDynamicSolidBadgeStyle(safeColor, isDarkMode);

      case "outline":
        const adjustedColor = isDarkMode ? adjustForDarkMode(safeColor, 65) : safeColor;
        return {
          backgroundColor: "transparent",
          borderColor: adjustedColor,
          color: adjustedColor,
        };

      case "dot":
        return {}; // Dot variant uses default badge styles

      case "subtle":
      default:
        return getDynamicBadgeStyle(safeColor, isDarkMode);
    }
  };

  const styles = getStyles();

  // Dot color (for dot variant or showDot)
  const dotColor = isDarkMode ? adjustForDarkMode(safeColor, 60) : safeColor;

  return (
    <span
      className={cn(
        "inline-flex items-center font-medium rounded-full whitespace-nowrap",
        variant === "outline" && "border",
        variant !== "solid" && "bg-muted/50",
        SIZE_STYLES[size],
        className
      )}
      style={styles}
    >
      {/* Dot indicator */}
      {(variant === "dot" || showDot) && (
        <span
          className={cn("rounded-full shrink-0", DOT_SIZES[size])}
          style={{ backgroundColor: dotColor }}
        />
      )}

      {/* Custom icon */}
      {icon && <span className="shrink-0">{icon}</span>}

      {/* Content */}
      <span className="truncate">{children}</span>
    </span>
  );
}

// =============================================================================
// SPECIALIZED VARIANTS
// =============================================================================

/**
 * Stage badge with predefined stage color lookup
 */
export interface StageBadgeProps extends Omit<DynamicColorBadgeProps, "color"> {
  /** Stage ID or color code */
  stageId?: string;
  /** Direct color override */
  color?: string | null;
}

/**
 * Colored dot indicator (minimal)
 */
export interface ColorDotProps {
  /** Color from API */
  color?: string | null;
  /** Size */
  size?: DynamicColorBadgeSize;
  /** Additional classes */
  className?: string;
}

export function ColorDot({ color, size = "md", className }: ColorDotProps) {
  const { isDarkMode } = useTheme();
  const safeColor = sanitizeColor(color);
  const adjustedColor = isDarkMode ? adjustForDarkMode(safeColor, 60) : safeColor;

  return (
    <span
      className={cn("rounded-full shrink-0", DOT_SIZES[size], className)}
      style={{ backgroundColor: adjustedColor }}
    />
  );
}

export default DynamicColorBadge;
