// src/components/common/ResponsiveDataDisplay.tsx
/**
 * ResponsiveDataDisplay - Automatically switches between Table and Card list
 *
 * On desktop (≥768px): Renders data in a table format
 * On mobile (<768px): Renders data as a card list
 *
 * Usage:
 * ```tsx
 * <ResponsiveDataDisplay
 *   data={items}
 *   isLoading={isLoading}
 *   emptyState={{
 *     icon: <Users className="h-12 w-12" />,
 *     title: "No users found",
 *     description: "Try adjusting your filters",
 *   }}
 *   tableView={<DataTable columns={columns} data={items} />}
 *   cardView={
 *     <div className="space-y-3">
 *       {items.map((item) => (
 *         <UserCard key={item.id} user={item} />
 *       ))}
 *     </div>
 *   }
 *   loadingSkeleton={{
 *     table: <TableSkeleton rows={5} cols={4} />,
 *     card: <CardListSkeleton count={4} />,
 *   }}
 * />
 * ```
 */
"use client";

import * as React from "react";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/common/EmptyState";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

interface EmptyStateConfig {
  /** Icon to display */
  icon?: React.ReactNode;
  /** Title text */
  title: string;
  /** Description text */
  description?: string;
  /** Action button/element */
  action?: React.ReactNode;
  /** Variant */
  variant?: "default" | "search";
}

interface LoadingSkeletonConfig {
  /** Desktop table loading skeleton */
  table?: React.ReactNode;
  /** Mobile card loading skeleton */
  card?: React.ReactNode;
}

interface ResponsiveDataDisplayProps<T> {
  /** Data array to display */
  data: T[];
  /** Whether data is loading */
  isLoading?: boolean;
  /** Whether there was an error */
  isError?: boolean;
  /** Error component to display */
  errorState?: React.ReactNode;
  /** Empty state configuration */
  emptyState?: EmptyStateConfig;
  /** Table view component (desktop) */
  tableView: React.ReactNode;
  /** Card view component (mobile) */
  cardView: React.ReactNode;
  /** Loading skeleton configuration */
  loadingSkeleton?: LoadingSkeletonConfig;
  /** Additional className for container */
  className?: string;
}

// =============================================================================
// DEFAULT LOADING SKELETONS
// =============================================================================

function DefaultTableSkeleton({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="rounded-md border">
      <div className="border-b bg-muted/50 p-4">
        <div className="flex gap-4">
          {Array.from({ length: cols }).map((_, i) => (
            <Skeleton key={i} className="h-4 flex-1" />
          ))}
        </div>
      </div>
      <div className="divide-y">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="p-4 flex gap-4">
            {Array.from({ length: cols }).map((_, j) => (
              <Skeleton key={j} className="h-4 flex-1" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function DefaultCardSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i}>
          <CardContent className="p-4">
            <div className="space-y-3">
              <div className="flex items-start justify-between">
                <div className="space-y-2 flex-1">
                  <Skeleton className="h-5 w-32" />
                  <Skeleton className="h-4 w-24" />
                </div>
                <Skeleton className="h-8 w-8 rounded" />
              </div>
              <Skeleton className="h-4 w-full" />
              <div className="flex gap-2">
                <Skeleton className="h-5 w-16 rounded-full" />
                <Skeleton className="h-5 w-20 rounded-full" />
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

function ResponsiveDataDisplay<T>({
  data,
  isLoading = false,
  isError = false,
  errorState,
  emptyState,
  tableView,
  cardView,
  loadingSkeleton,
  className,
}: ResponsiveDataDisplayProps<T>) {
  const isMobile = useIsMobile();

  // Loading state
  if (isLoading) {
    return (
      <div className={className}>
        {isMobile ? (
          loadingSkeleton?.card ?? <DefaultCardSkeleton />
        ) : (
          loadingSkeleton?.table ?? <DefaultTableSkeleton />
        )}
      </div>
    );
  }

  // Error state
  if (isError && errorState) {
    return <div className={className}>{errorState}</div>;
  }

  // Empty state
  if (data.length === 0 && emptyState) {
    return (
      <div className={className}>
        <Card>
          <CardContent className="p-0">
            <EmptyState
              icon={emptyState.icon}
              title={emptyState.title}
              description={emptyState.description}
              action={emptyState.action}
              variant={emptyState.variant}
            />
          </CardContent>
        </Card>
      </div>
    );
  }

  // Data display
  return (
    <div className={className}>
      {/* Mobile: Card View */}
      <div className="md:hidden">{cardView}</div>

      {/* Desktop: Table View */}
      <div className="hidden md:block">{tableView}</div>
    </div>
  );
}

// =============================================================================
// HELPER COMPONENTS
// =============================================================================

/**
 * TableSkeleton - Reusable table loading skeleton
 */
function TableSkeleton({
  rows = 5,
  cols = 4,
  className,
}: {
  rows?: number;
  cols?: number;
  className?: string;
}) {
  return <DefaultTableSkeleton rows={rows} cols={cols} />;
}

/**
 * CardListSkeleton - Reusable card list loading skeleton
 */
function CardListSkeleton({
  count = 4,
  className,
}: {
  count?: number;
  className?: string;
}) {
  return <DefaultCardSkeleton count={count} />;
}

// =============================================================================
// EXPORTS
// =============================================================================

// Attach helper components
ResponsiveDataDisplay.TableSkeleton = TableSkeleton;
ResponsiveDataDisplay.CardListSkeleton = CardListSkeleton;

export { ResponsiveDataDisplay, TableSkeleton, CardListSkeleton };
export type { ResponsiveDataDisplayProps, EmptyStateConfig, LoadingSkeletonConfig };
