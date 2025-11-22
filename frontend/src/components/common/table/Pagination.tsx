// src/components/common/table/Pagination.tsx
"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

export interface PaginationProps {
  /** Current page (1-indexed) */
  page: number;
  /** Number of items per page */
  pageSize: number;
  /** Total number of items */
  total: number;
  /** Callback when page changes */
  onPageChange: (page: number) => void;
  /** Callback when page size changes */
  onPageSizeChange?: (size: number) => void;
  /** Show page size selector */
  showPageSizeSelector?: boolean;
  /** Available page sizes */
  pageSizeOptions?: number[];
  /** Loading state - disables all controls */
  isLoading?: boolean;
  /** Show total count */
  showTotal?: boolean;
  /** Additional CSS classes */
  className?: string;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const DEFAULT_PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const DEBOUNCE_DELAY = 300;

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Clamp page number to valid range
 */
function clampPage(page: number, totalPages: number): number {
  return Math.max(1, Math.min(page, totalPages));
}

/**
 * Calculate total pages
 */
function getTotalPages(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(total / pageSize));
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  showPageSizeSelector = true,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  isLoading = false,
  showTotal = true,
  className,
}: PaginationProps) {
  const totalPages = getTotalPages(total, pageSize);
  const currentPage = clampPage(page, totalPages);

  // Debounced page change
  const debounceRef = React.useRef<NodeJS.Timeout | null>(null);

  const handlePageChange = React.useCallback(
    (newPage: number) => {
      const clampedPage = clampPage(newPage, totalPages);
      if (clampedPage === currentPage) return;

      // Clear previous debounce
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }

      // Debounce the page change
      debounceRef.current = setTimeout(() => {
        onPageChange(clampedPage);
      }, DEBOUNCE_DELAY);
    },
    [currentPage, totalPages, onPageChange]
  );

  // Cleanup on unmount
  React.useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, []);

  const handlePageSizeChange = React.useCallback(
    (value: string) => {
      const newSize = parseInt(value, 10);
      if (onPageSizeChange && !isNaN(newSize)) {
        onPageSizeChange(newSize);
        // Reset to page 1 when page size changes
        onPageChange(1);
      }
    },
    [onPageSizeChange, onPageChange]
  );

  // Calculate display range
  const startItem = total === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const endItem = Math.min(currentPage * pageSize, total);

  // Navigation state
  const canGoPrev = currentPage > 1;
  const canGoNext = currentPage < totalPages;

  return (
    <div
      className={cn(
        "flex flex-col sm:flex-row items-center justify-between gap-4 px-2 py-4",
        className
      )}
    >
      {/* Left side - Info */}
      <div className="flex items-center gap-4 text-sm text-muted-foreground">
        {showTotal && (
          <span>
            Hien thi {startItem} - {endItem} / {total} ket qua
          </span>
        )}

        {showPageSizeSelector && onPageSizeChange && (
          <div className="flex items-center gap-2">
            <span>Hien thi</span>
            <Select
              value={String(pageSize)}
              onValueChange={handlePageSizeChange}
              disabled={isLoading}
            >
              <SelectTrigger className="h-8 w-[70px]">
                <SelectValue placeholder={pageSize} />
              </SelectTrigger>
              <SelectContent side="top">
                {pageSizeOptions.map((size) => (
                  <SelectItem key={size} value={String(size)}>
                    {size}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span>dong</span>
          </div>
        )}
      </div>

      {/* Right side - Navigation */}
      <div className="flex items-center gap-1">
        {/* First page */}
        <Button
          variant="outline"
          size="icon"
          className="h-8 w-8"
          onClick={() => handlePageChange(1)}
          disabled={!canGoPrev || isLoading}
          aria-label="Trang dau"
        >
          <ChevronsLeft className="h-4 w-4" />
        </Button>

        {/* Previous page */}
        <Button
          variant="outline"
          size="icon"
          className="h-8 w-8"
          onClick={() => handlePageChange(currentPage - 1)}
          disabled={!canGoPrev || isLoading}
          aria-label="Trang truoc"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>

        {/* Page indicator */}
        <div className="flex items-center gap-1 px-2 text-sm">
          <span>Trang</span>
          <span className="font-medium">{currentPage}</span>
          <span>/</span>
          <span>{totalPages}</span>
        </div>

        {/* Next page */}
        <Button
          variant="outline"
          size="icon"
          className="h-8 w-8"
          onClick={() => handlePageChange(currentPage + 1)}
          disabled={!canGoNext || isLoading}
          aria-label="Trang sau"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>

        {/* Last page */}
        <Button
          variant="outline"
          size="icon"
          className="h-8 w-8"
          onClick={() => handlePageChange(totalPages)}
          disabled={!canGoNext || isLoading}
          aria-label="Trang cuoi"
        >
          <ChevronsRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

export default Pagination;
