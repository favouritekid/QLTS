// src/components/layouts/dashboard/RecentPages.tsx
"use client";

import Link from "next/link";
import { Clock, X } from "lucide-react";
import { useRecentPages } from "@/hooks/useRecentPages";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface RecentPagesProps {
  /**
   * Whether the sidebar is collapsed
   */
  isCollapsed: boolean;
}

/**
 * Recent Pages Component
 * Displays a list of recently visited pages in the sidebar
 *
 * Features:
 * - Auto-tracks page visits
 * - Shows most recent 5 pages
 * - Remove individual items
 * - Highlight current page
 * - Responsive to sidebar collapse state
 *
 * @example
 * <RecentPages isCollapsed={false} />
 */
export function RecentPages({ isCollapsed }: RecentPagesProps) {
  const { recentPages, removePage } = useRecentPages();

  // Don't render if no recent pages
  if (recentPages.length === 0) {
    return null;
  }

  // Collapsed state - show icons only with tooltips
  if (isCollapsed) {
    return (
      <TooltipProvider delayDuration={0}>
        <div className="flex flex-col gap-1 pt-2 border-t">
          {recentPages.map((page) => {
            return (
              <Tooltip key={page.path}>
                <TooltipTrigger asChild>
                  <Link
                    href={page.path}
                    className="text-muted-foreground hover:bg-muted hover:text-foreground flex h-9 w-9 items-center justify-center rounded-lg transition-colors"
                  >
                    <Clock className="h-4 w-4" />
                    <span className="sr-only">{page.label}</span>
                  </Link>
                </TooltipTrigger>
                <TooltipContent
                  side="right"
                  className="bg-popover text-popover-foreground border shadow-md"
                >
                  <span className="font-medium">{page.label}</span>
                </TooltipContent>
              </Tooltip>
            );
          })}
        </div>
      </TooltipProvider>
    );
  }

  // Expanded state - show full list
  return (
    <div className="border-t pt-3 animate-in fade-in-0 slide-in-from-bottom-2 duration-500">
      {/* Header */}
      <div className="flex items-center justify-between px-4 mb-2">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Gần đây
        </h4>
        <Clock className="h-3.5 w-3.5 text-muted-foreground/70" />
      </div>

      {/* Recent items list */}
      <div className="space-y-0.5">
        {recentPages.map((page, index) => {
          return (
            <div
              key={page.path}
              className="group relative flex items-center animate-in fade-in-0 slide-in-from-left-2 duration-300"
              style={{ animationDelay: `${index * 75}ms` }}
            >
              {/* Link */}
              <Link
                href={page.path}
                className={cn(
                  "flex-1 flex items-center gap-2 px-3 py-2 rounded-md",
                  "transition-all duration-200 ease-in-out",
                  "text-sm text-muted-foreground hover:text-foreground hover:bg-muted",
                  "hover:scale-[1.02] hover:shadow-sm active:scale-[0.98]"
                )}
              >
                <Clock className="h-3.5 w-3.5 flex-shrink-0" />
                <span className="flex-1 truncate">{page.label}</span>
              </Link>

              {/* Remove button - shown on hover */}
              <Button
                variant="ghost"
                size="icon"
                onClick={(e) => {
                  e.preventDefault();
                  removePage(page.path);
                }}
                className={cn(
                  "absolute right-1 h-6 w-6 opacity-0 group-hover:opacity-100",
                  "transition-all duration-200 ease-in-out",
                  "hover:bg-destructive hover:text-destructive-foreground hover:scale-110"
                )}
                aria-label={`Remove ${page.label} from recent`}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
