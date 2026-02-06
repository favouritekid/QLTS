/**
 * MobileTableWrapper - Horizontal scroll wrapper for tables on mobile
 *
 * Based on MOBILE_STANDARDIZATION.md section 8.2
 * Provides scroll indicators and proper overflow handling for tables on small screens.
 *
 * @example
 * ```tsx
 * <MobileTableWrapper>
 *   <Table>
 *     <TableHeader>...</TableHeader>
 *     <TableBody>...</TableBody>
 *   </Table>
 * </MobileTableWrapper>
 * ```
 */

import { cn } from "@/lib/utils";

interface MobileTableWrapperProps {
  children: React.ReactNode;
  className?: string;
  /** Minimum width for the table content. Default: 600px */
  minWidth?: string;
  /** Show scroll shadow indicators on mobile. Default: true */
  showScrollIndicators?: boolean;
}

export function MobileTableWrapper({
  children,
  className,
  minWidth = "600px",
  showScrollIndicators = true,
}: MobileTableWrapperProps) {
  return (
    <div className={cn("relative w-full", className)}>
      {/* Scroll shadow indicators - only visible on mobile */}
      {showScrollIndicators && (
        <>
          <div
            className="pointer-events-none absolute inset-y-0 left-0 z-10 w-4 bg-gradient-to-r from-background to-transparent lg:hidden"
            aria-hidden="true"
          />
          <div
            className="pointer-events-none absolute inset-y-0 right-0 z-10 w-4 bg-gradient-to-l from-background to-transparent lg:hidden"
            aria-hidden="true"
          />
        </>
      )}

      {/* Scrollable container */}
      <div
        className="overflow-x-auto overflow-y-visible pb-2"
        style={{ WebkitOverflowScrolling: 'touch' }}
      >
        <div className="inline-block min-w-full" style={{ minWidth }}>
          {children}
        </div>
      </div>
    </div>
  );
}
