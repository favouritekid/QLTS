// src/components/common/CommandPalette.tsx
"use client";

import { useEffect, useState, useRef } from "react";
import { useCommandPalette } from "@/hooks/useCommandPalette";
import type { CommandItem } from "@/hooks/useCommandPalette";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem as CommandItemUI,
  CommandList,
} from "@/components/ui/command";
import { Badge } from "@/components/ui/badge";
import { Clock, Hash } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Command Palette Component
 *
 * Keyboard-first navigation interface inspired by Vercel, Linear, and Raycast
 *
 * Features:
 * - Cmd/Ctrl+K to open
 * - Fuzzy search across all pages
 * - Recent pages integration
 * - Arrow keys navigation
 * - Enter to navigate
 * - Esc to close
 * - Categories and grouping
 *
 * @example
 * <CommandPalette />
 */
export function CommandPalette() {
  const {
    isOpen,
    close,
    query,
    setQuery,
    filteredItems,
    executeCommand,
  } = useCommandPalette();

  const [selectedIndex, setSelectedIndex] = useState(0);
  const prevQueryRef = useRef(query);
  const prevItemsLengthRef = useRef(filteredItems.length);

  // Reset selected index when query changes
  useEffect(() => {
    // Only reset if query or items actually changed
    if (query !== prevQueryRef.current || filteredItems.length !== prevItemsLengthRef.current) {
      prevQueryRef.current = query;
      prevItemsLengthRef.current = filteredItems.length;
      // Use queueMicrotask to defer state update
      queueMicrotask(() => setSelectedIndex(0));
    }
  }, [query, filteredItems]);

  // Handle keyboard navigation (Arrow keys, Enter)
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setSelectedIndex((prev) =>
            prev < filteredItems.length - 1 ? prev + 1 : prev
          );
          break;

        case "ArrowUp":
          e.preventDefault();
          setSelectedIndex((prev) => (prev > 0 ? prev - 1 : 0));
          break;

        case "Enter":
          e.preventDefault();
          if (filteredItems[selectedIndex]) {
            executeCommand(filteredItems[selectedIndex]);
          }
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, selectedIndex, filteredItems, executeCommand]);

  // Group items by category
  const groupedItems = {
    recent: filteredItems.filter((item) => item.category === "recent"),
    navigation: filteredItems.filter((item) => item.category === "navigation"),
    actions: filteredItems.filter((item) => item.category === "action"),
  };

  // Render command item
  const renderItem = (item: CommandItem, index: number) => {
    const Icon = item.icon;
    const isSelected = index === selectedIndex;

    return (
      <CommandItemUI
        key={item.id}
        value={item.label}
        onSelect={() => executeCommand(item)}
        className={cn(
          "flex items-center gap-3 px-4 py-3 cursor-pointer",
          "transition-all duration-200 ease-in-out",
          "hover:scale-[1.02] active:scale-[0.98]",
          isSelected && "bg-accent shadow-sm"
        )}
      >
        {/* Icon */}
        <div className={cn(
          "flex items-center justify-center w-8 h-8 rounded-md bg-muted flex-shrink-0",
          "transition-all duration-200",
          isSelected && "bg-accent-foreground/10 scale-110"
        )}>
          {Icon ? (
            <Icon className={cn(
              "h-4 w-4 text-muted-foreground transition-all duration-200",
              isSelected && "text-foreground"
            )} />
          ) : item.category === "recent" ? (
            <Clock className={cn(
              "h-4 w-4 text-muted-foreground transition-all duration-200",
              isSelected && "text-foreground"
            )} />
          ) : (
            <Hash className={cn(
              "h-4 w-4 text-muted-foreground transition-all duration-200",
              isSelected && "text-foreground"
            )} />
          )}
        </div>

        {/* Label */}
        <div className="flex-1 flex items-center justify-between gap-2">
          <span className={cn(
            "font-medium transition-colors duration-200",
            isSelected && "text-foreground"
          )}>
            {item.label}
          </span>

          {/* Badge */}
          {item.badge && (
            <Badge
              variant="secondary"
              className={cn(
                "flex-shrink-0 transition-all duration-200",
                isSelected && "scale-105"
              )}
            >
              {item.badge}
            </Badge>
          )}
        </div>

        {/* Path hint */}
        {item.href && (
          <span className={cn(
            "text-xs text-muted-foreground truncate max-w-[200px]",
            "transition-opacity duration-200",
            isSelected ? "opacity-100" : "opacity-60"
          )}>
            {item.href}
          </span>
        )}
      </CommandItemUI>
    );
  };

  return (
    <CommandDialog open={isOpen} onOpenChange={close}>
      <Command
        shouldFilter={false}
        className="rounded-lg border shadow-md animate-in fade-in-0 zoom-in-95 duration-200"
      >
        {/* Search Input */}
        <CommandInput
          placeholder="Tìm kiếm trang, thao tác, hoặc nhập lệnh..."
          value={query}
          onValueChange={setQuery}
          className="h-14 border-none focus:ring-0 transition-all duration-200"
        />

        {/* Results List */}
        <CommandList className="max-h-[400px] animate-in fade-in-0 slide-in-from-bottom-2 duration-300">
          {/* Empty State */}
          <CommandEmpty className="py-8 text-center">
            <div className="text-muted-foreground space-y-2 animate-in fade-in-0 zoom-in-95 duration-500">
              <div className="text-4xl">🔍</div>
              <p className="text-sm font-medium">Không tìm thấy kết quả cho "{query}"</p>
              <p className="text-xs">Thử tìm kiếm trang hoặc tính năng</p>
            </div>
          </CommandEmpty>

          {/* Recent Pages Group */}
          {groupedItems.recent.length > 0 && (
            <CommandGroup heading="Trang Gần Đây">
              {groupedItems.recent.map((item, idx) =>
                renderItem(item, idx)
              )}
            </CommandGroup>
          )}

          {/* Navigation Group */}
          {groupedItems.navigation.length > 0 && (
            <CommandGroup heading={query ? "Trang" : "Tất cả Trang"}>
              {groupedItems.navigation.map((item, idx) => {
                const globalIndex = groupedItems.recent.length + idx;
                return renderItem(item, globalIndex);
              })}
            </CommandGroup>
          )}

          {/* Actions Group (Future) */}
          {groupedItems.actions.length > 0 && (
            <CommandGroup heading="Thao tác">
              {groupedItems.actions.map((item, idx) => {
                const globalIndex =
                  groupedItems.recent.length +
                  groupedItems.navigation.length +
                  idx;
                return renderItem(item, globalIndex);
              })}
            </CommandGroup>
          )}
        </CommandList>

        {/* Footer with keyboard hints */}
        <div className="border-t px-4 py-2 text-xs text-muted-foreground flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1">
              <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium">
                ↑↓
              </kbd>
              <span>Điều hướng</span>
            </div>
            <div className="flex items-center gap-1">
              <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium">
                ↵
              </kbd>
              <span>Chọn</span>
            </div>
            <div className="flex items-center gap-1">
              <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium">
                ESC
              </kbd>
              <span>Đóng</span>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium">
              ⌘K
            </kbd>
            <span>để mở</span>
          </div>
        </div>
      </Command>
    </CommandDialog>
  );
}
