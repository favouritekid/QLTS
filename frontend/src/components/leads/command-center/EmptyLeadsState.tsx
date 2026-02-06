// src/components/leads/command-center/EmptyLeadsState.tsx
/**
 * ✅ Phase 3: Contextual Empty States
 * 
 * Shows different empty state messages based on context:
 * - Has filters → "Không tìm thấy lead" + reset filters
 * - No filters → "Chưa có lead nào" + create lead
 * - Error → Error message + retry
 */

"use client";

import React from "react";
import { 
  SearchX, 
  Users, 
  Plus,
  RefreshCw,
  Filter,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

interface EmptyLeadsStateProps {
  /** Whether any filters are active */
  hasFilters?: boolean;
  /** Search query if any */
  searchQuery?: string;
  /** Total count (to distinguish between filtered empty vs truly empty) */
  totalCount?: number;
  /** Callback to reset filters */
  onResetFilters?: () => void;
  /** Callback to create new lead */
  onCreateLead?: () => void;
  /** Callback to retry loading */
  onRetry?: () => void;
  /** Custom class name */
  className?: string;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function EmptyLeadsState({
  hasFilters = false,
  searchQuery,
  totalCount = 0,
  onResetFilters,
  onCreateLead,
  onRetry,
  className,
}: EmptyLeadsStateProps) {
  
  // Determine which state to show
  const isFiltered = hasFilters || !!searchQuery;
  
  // State 1: Has filters but no results
  if (isFiltered) {
    return (
      <div className={cn("flex flex-col items-center justify-center gap-4 py-12", className)}>
        <div className="bg-muted/50 rounded-full p-4">
          <SearchX aria-hidden="true" className="h-10 w-10 text-muted-foreground" />
        </div>
        <div className="text-center space-y-1">
          <h3 className="font-semibold text-foreground">Không tìm thấy lead</h3>
          {searchQuery ? (
            <p className="text-muted-foreground text-sm max-w-[300px]">
              Không có lead nào khớp với &quot;{searchQuery}&quot;
            </p>
          ) : (
            <p className="text-muted-foreground text-sm max-w-[300px]">
              Không có lead nào khớp với bộ lọc hiện tại
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {onResetFilters && (
            <Button variant="outline" size="sm" onClick={onResetFilters}>
              <Filter aria-hidden="true" className="h-4 w-4 mr-1.5" />
              Xóa bộ lọc
            </Button>
          )}
          {onCreateLead && (
            <Button variant="default" size="sm" onClick={onCreateLead}>
              <Plus aria-hidden="true" className="h-4 w-4 mr-1.5" />
              Tạo lead mới
            </Button>
          )}
        </div>
      </div>
    );
  }
  
  // State 2: No leads at all (empty database)
  if (totalCount === 0) {
    return (
      <div className={cn("flex flex-col items-center justify-center gap-4 py-12", className)}>
        <div className="bg-primary/10 rounded-full p-4">
          <Users aria-hidden="true" className="h-10 w-10 text-primary" />
        </div>
        <div className="text-center space-y-1">
          <h3 className="font-semibold text-foreground">Chưa có lead nào</h3>
          <p className="text-muted-foreground text-sm max-w-[300px]">
            Bắt đầu bằng cách tạo lead mới hoặc import từ file Excel
          </p>
        </div>
        <div className="flex items-center gap-2">
          {onCreateLead && (
            <Button variant="default" size="sm" onClick={onCreateLead}>
              <Plus aria-hidden="true" className="h-4 w-4 mr-1.5" />
              Tạo lead đầu tiên
            </Button>
          )}
        </div>
      </div>
    );
  }
  
  // State 3: Generic empty (fallback)
  return (
    <div className={cn("flex flex-col items-center justify-center gap-4 py-12", className)}>
      <div className="bg-muted/50 rounded-full p-4">
        <SearchX aria-hidden="true" className="h-10 w-10 text-muted-foreground" />
      </div>
      <div className="text-center space-y-1">
        <h3 className="font-semibold text-foreground">Không có dữ liệu</h3>
        <p className="text-muted-foreground text-sm">
          Vui lòng thử lại sau
        </p>
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw aria-hidden="true" className="h-4 w-4 mr-1.5" />
          Thử lại
        </Button>
      )}
    </div>
  );
}

export default EmptyLeadsState;
