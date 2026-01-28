// src/components/common/CopyableCell.tsx
/**
 * CopyableCell - A cell component with click-to-copy functionality
 * 
 * Features:
 * - Click to copy value to clipboard
 * - Visual feedback with tooltip and icon
 * - Smooth animation on copy
 * - Works with any text content
 */

"use client";

import React, { useState, useCallback } from "react";
import { Copy, Check } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

// =============================================================================
// TYPES
// =============================================================================

interface CopyableCellProps {
  /** The value to copy to clipboard */
  value: string | null | undefined;
  /** Display value (if different from copy value) */
  displayValue?: React.ReactNode;
  /** Label for the toast message (e.g., "Số điện thoại") */
  label?: string;
  /** Additional class names */
  className?: string;
  /** Empty placeholder when value is null/undefined */
  placeholder?: string;
  /** Icon to show before value */
  icon?: React.ReactNode;
  /** Whether to show copy icon on hover */
  showCopyIcon?: boolean;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function CopyableCell({
  value,
  displayValue,
  label = "Giá trị",
  className,
  placeholder = "—",
  icon,
  showCopyIcon = true,
}: CopyableCellProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation(); // Prevent row selection when clicking to copy
      
      if (!value) return;

      try {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        toast.success(`Đã sao chép ${label}`, {
          description: value,
          duration: 2000,
        });
        
        // Reset copied state after animation
        setTimeout(() => setCopied(false), 2000);
      } catch (err) {
        console.error("Failed to copy:", err);
        toast.error("Không thể sao chép");
      }
    },
    [value, label]
  );

  // Empty state
  if (!value) {
    return <span className="text-muted-foreground">{placeholder}</span>;
  }

  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={handleCopy}
            className={cn(
              "group inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 -mx-1.5 -my-0.5",
              "transition-all duration-150",
              "hover:bg-muted/80 active:bg-muted",
              "focus:outline-none focus:ring-2 focus:ring-primary/20",
              "cursor-pointer text-left",
              className
            )}
          >
            {/* Optional icon */}
            {icon}
            
            {/* Value */}
            <span className={cn(
              "transition-colors",
              copied && "text-success-600 dark:text-success-400"
            )}>
              {displayValue ?? value}
            </span>
            
            {/* Copy icon - appears on hover */}
            {showCopyIcon && (
              <span className={cn(
                "transition-all duration-150",
                copied 
                  ? "opacity-100" 
                  : "opacity-0 group-hover:opacity-60"
              )}>
                {copied ? (
                  <Check className="h-3 w-3 text-success-600 dark:text-success-400" />
                ) : (
                  <Copy className="h-3 w-3 text-muted-foreground" />
                )}
              </span>
            )}
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="text-xs">
          {copied ? "Đã sao chép!" : `Click để sao chép ${label.toLowerCase()}`}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default CopyableCell;
