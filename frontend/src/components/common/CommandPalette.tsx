// src/components/common/CommandPalette.tsx
"use client";

import { useEffect, useState } from "react";
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

  // Reset selected index when query changes
  useEffect(() => {
    setSelectedIndex(0);
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
          isSelected && "bg-accent"
        )}
      >
        {/* Icon */}
        <div className="flex items-center justify-center w-8 h-8 rounded-md bg-muted flex-shrink-0">
          {Icon ? (
            <Icon className="h-4 w-4 text-muted-foreground" />
          ) : item.category === "recent" ? (
            <Clock className="h-4 w-4 text-muted-foreground" />
          ) : (
            <Hash className="h-4 w-4 text-muted-foreground" />
          )}
        </div>

        {/* Label */}
        <div className="flex-1 flex items-center justify-between gap-2">
          <span className="font-medium">{item.label}</span>

          {/* Badge */}
          {item.badge && (
            <Badge variant="secondary" className="flex-shrink-0">
              {item.badge}
            </Badge>
          )}
        </div>

        {/* Path hint */}
        {item.href && (
          <span className="text-xs text-muted-foreground truncate max-w-[200px]">
            {item.href}
          </span>
        )}
      </CommandItemUI>
    );
  };

  return (
    <CommandDialog open={isOpen} onOpenChange={close}>
      <Command shouldFilter={false} className="rounded-lg border shadow-md">
        {/* Search Input */}
        <CommandInput
          placeholder="Search pages, actions, or type a command..."
          value={query}
          onValueChange={setQuery}
          className="h-14 border-none focus:ring-0"
        />

        {/* Results List */}
        <CommandList className="max-h-[400px]">
          {/* Empty State */}
          <CommandEmpty className="py-6 text-center">
            <div className="text-muted-foreground">
              <p className="text-sm">No results found for &quot;{query}&quot;</p>
              <p className="text-xs mt-1">Try searching for pages or features</p>
            </div>
          </CommandEmpty>

          {/* Recent Pages Group */}
          {groupedItems.recent.length > 0 && (
            <CommandGroup heading="Recent Pages">
              {groupedItems.recent.map((item, idx) =>
                renderItem(item, idx)
              )}
            </CommandGroup>
          )}

          {/* Navigation Group */}
          {groupedItems.navigation.length > 0 && (
            <CommandGroup heading={query ? "Pages" : "All Pages"}>
              {groupedItems.navigation.map((item, idx) => {
                const globalIndex = groupedItems.recent.length + idx;
                return renderItem(item, globalIndex);
              })}
            </CommandGroup>
          )}

          {/* Actions Group (Future) */}
          {groupedItems.actions.length > 0 && (
            <CommandGroup heading="Actions">
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
              <span>Navigate</span>
            </div>
            <div className="flex items-center gap-1">
              <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium">
                ↵
              </kbd>
              <span>Select</span>
            </div>
            <div className="flex items-center gap-1">
              <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium">
                ESC
              </kbd>
              <span>Close</span>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium">
              ⌘K
            </kbd>
            <span>to open</span>
          </div>
        </div>
      </Command>
    </CommandDialog>
  );
}
