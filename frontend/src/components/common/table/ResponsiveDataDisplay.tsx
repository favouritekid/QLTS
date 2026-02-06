// src/components/common/table/ResponsiveDataDisplay.tsx
/**
 * ResponsiveDataDisplay - Responsive data display component
 *
 * Shows DataTable on desktop (md+) and card view on mobile.
 * Provides a consistent pattern for displaying data across breakpoints.
 *
 * Usage:
 * ```tsx
 * <ResponsiveDataDisplay
 *   data={leads}
 *   columns={columns}
 *   isLoading={isLoading}
 *   mobileCardRender={(lead) => <LeadMobileCard lead={lead} />}
 * />
 * ```
 */
"use client";

import * as React from "react";
import { type ColumnDef } from "@tanstack/react-table";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { DataTable, type DataTableProps } from "./DataTable";

// =============================================================================
// TYPES
// =============================================================================

export interface ResponsiveDataDisplayProps<TData, TValue>
  extends Omit<DataTableProps<TData, TValue>, 'columns'> {
  /** Column definitions for table view */
  columns: ColumnDef<TData, TValue>[];
  /** Render function for mobile card view */
  mobileCardRender: (item: TData, index: number) => React.ReactNode;
  /** Optional key extractor for list items */
  keyExtractor?: (item: TData, index: number) => string | number;
  /** Mobile card container class */
  mobileCardClassName?: string;
  /** Mobile list container class */
  mobileListClassName?: string;
  /** Breakpoint to switch between card and table (default: md) */
  breakpoint?: "sm" | "md" | "lg";
  /** Show scroll shadows on mobile */
  showScrollShadows?: boolean;
}

// =============================================================================
// MOBILE SKELETON
// =============================================================================

function MobileCardSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i} className="p-4">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-5 w-16" />
            </div>
            <Skeleton className="h-4 w-48" />
            <div className="flex gap-2">
              <Skeleton className="h-8 w-16" />
              <Skeleton className="h-8 w-16" />
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

// =============================================================================
// COMPONENT
// =============================================================================

export function ResponsiveDataDisplay<TData, TValue>({
  data,
  columns,
  isLoading,
  mobileCardRender,
  keyExtractor,
  mobileCardClassName,
  mobileListClassName,
  breakpoint = "md",
  showScrollShadows = true,
  emptyMessage = "Không có dữ liệu",
  ...tableProps
}: ResponsiveDataDisplayProps<TData, TValue>) {
  // Breakpoint classes for visibility
  const mobileVisibility = {
    sm: "sm:hidden",
    md: "md:hidden",
    lg: "lg:hidden",
  };

  const desktopVisibility = {
    sm: "hidden sm:block",
    md: "hidden md:block",
    lg: "hidden lg:block",
  };

  // Default key extractor
  const getKey = keyExtractor || ((_, index) => index);

  return (
    <>
      {/* Mobile: Card view */}
      <div className={cn(mobileVisibility[breakpoint], mobileListClassName)}>
        {isLoading ? (
          <MobileCardSkeleton count={5} />
        ) : data.length === 0 ? (
          <Card className="p-8 text-center">
            <p className="text-muted-foreground">{emptyMessage}</p>
          </Card>
        ) : (
          <div className="space-y-3">
            {data.map((item, index) => (
              <Card
                key={getKey(item, index)}
                className={cn("p-4", mobileCardClassName)}
              >
                {mobileCardRender(item, index)}
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* Desktop: Table view */}
      <div className={cn(desktopVisibility[breakpoint])}>
        {showScrollShadows && (
          <div className="relative">
            {/* Scroll shadow indicators for horizontal scroll */}
            <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-4 bg-gradient-to-r from-background to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
            <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-4 bg-gradient-to-l from-background to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
          </div>
        )}
        <DataTable
          data={data}
          columns={columns}
          isLoading={isLoading}
          emptyMessage={emptyMessage}
          {...tableProps}
        />
      </div>
    </>
  );
}

// =============================================================================
// MOBILE CARD HELPERS
// =============================================================================

/**
 * Helper component for common mobile card layout patterns
 */
export function MobileCardRow({
  label,
  value,
  className,
}: {
  label: string;
  value: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center justify-between gap-2", className)}>
      <span className="text-xs text-muted-foreground shrink-0">{label}</span>
      <span className="text-sm font-medium truncate">{value}</span>
    </div>
  );
}

export function MobileCardHeader({
  title,
  badge,
  subtitle,
  className,
}: {
  title: React.ReactNode;
  badge?: React.ReactNode;
  subtitle?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1", className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium truncate">{title}</span>
        {badge}
      </div>
      {subtitle && (
        <p className="text-xs text-muted-foreground truncate">{subtitle}</p>
      )}
    </div>
  );
}

export function MobileCardActions({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-2 pt-2 border-t mt-3", className)}>
      {children}
    </div>
  );
}

export default ResponsiveDataDisplay;
