// src/components/leads/command-center/KeyboardShortcutsHelp.tsx
/**
 * ✅ Option C: Keyboard Shortcuts Help
 * 
 * Popover showing all available keyboard shortcuts.
 * Opened by pressing `?` key or clicking help button.
 */

"use client";

import React, { useEffect, useState } from "react";
import { Keyboard } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// =============================================================================
// TYPES
// =============================================================================

interface KeyboardShortcut {
  keys: string[];
  description: string;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const SHORTCUTS: KeyboardShortcut[] = [
  // ✅ Phase 3: Vim-style navigation added
  { keys: ["j", "↓"], description: "Di chuyển xuống" },
  { keys: ["k", "↑"], description: "Di chuyển lên" },
  { keys: ["Enter"], description: "Xem chi tiết lead" },
  { keys: ["Space"], description: "Chọn/bỏ chọn checkbox" },
  { keys: ["e"], description: "Sửa lead đang focus" },
  { keys: ["/"], description: "Focus ô tìm kiếm" },
  { keys: ["Escape"], description: "Bỏ chọn tất cả" },
  { keys: ["?"], description: "Hiển thị phím tắt" },
];

// =============================================================================
// MAIN COMPONENT
// =============================================================================

interface KeyboardShortcutsHelpProps {
  className?: string;
}

export function KeyboardShortcutsHelp({ className }: KeyboardShortcutsHelpProps) {
  const [open, setOpen] = useState(false);

  // Listen for ? key globally
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Only handle if not in input/textarea
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") {
        return;
      }

      if (e.key === "?" && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <TooltipProvider delayDuration={300}>
      <Popover open={open} onOpenChange={setOpen}>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className={className}
              >
                <Keyboard className="h-4 w-4" />
              </Button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent>Phím tắt (?)</TooltipContent>
        </Tooltip>

        <PopoverContent align="end" className="w-64 p-4">
          <div className="space-y-3">
            <div className="flex items-center gap-2 border-b pb-2">
              <Keyboard className="text-primary h-4 w-4" />
              <h4 className="font-semibold">Phím tắt</h4>
            </div>

            <div className="space-y-2">
              {SHORTCUTS.map((shortcut, index) => (
                <div
                  key={index}
                  className="flex items-center justify-between text-sm"
                >
                  <span className="text-muted-foreground">
                    {shortcut.description}
                  </span>
                  <div className="flex gap-1">
                    {shortcut.keys.map((key, keyIndex) => (
                      <kbd
                        key={keyIndex}
                        className="bg-muted rounded border px-1.5 py-0.5 font-mono text-xs"
                      >
                        {key}
                      </kbd>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <p className="text-muted-foreground border-t pt-2 text-xs">
              Nhấn <kbd className="bg-muted rounded border px-1 font-mono text-xs">?</kbd> để ẩn/hiện
            </p>
          </div>
        </PopoverContent>
      </Popover>
    </TooltipProvider>
  );
}

export default KeyboardShortcutsHelp;
