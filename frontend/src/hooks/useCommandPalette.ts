// src/hooks/useCommandPalette.ts
/**
 * Custom hook for Command Palette functionality
 * Manages keyboard shortcuts, search state, and command execution
 */
import { useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { navigationConfig } from "@/lib/config/navigation";
import { useRecentPages } from "@/hooks/useRecentPages";
import type { NavItem } from "@/types/navigation";

/**
 * Command item type for search results
 */
export interface CommandItem {
  id: string;
  label: string;
  href?: string;
  icon?: React.ComponentType<{ className?: string }>;
  category: "navigation" | "recent" | "action";
  keywords?: string[];
  badge?: string | number;
  action?: () => void;
}

/**
 * Hook return type
 */
interface UseCommandPaletteReturn {
  /**
   * Whether the command palette is open
   */
  isOpen: boolean;
  /**
   * Open the command palette
   */
  open: () => void;
  /**
   * Close the command palette
   */
  close: () => void;
  /**
   * Toggle the command palette
   */
  toggle: () => void;
  /**
   * Search query
   */
  query: string;
  /**
   * Set search query
   */
  setQuery: (query: string) => void;
  /**
   * Filtered command items based on query
   */
  filteredItems: CommandItem[];
  /**
   * Execute a command (navigate or run action)
   */
  executeCommand: (item: CommandItem) => void;
}

/**
 * Simple fuzzy match function
 * Returns true if all characters in query appear in text in order (case-insensitive)
 */
function fuzzyMatch(text: string, query: string): boolean {
  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();

  let queryIndex = 0;
  for (let i = 0; i < lowerText.length && queryIndex < lowerQuery.length; i++) {
    if (lowerText[i] === lowerQuery[queryIndex]) {
      queryIndex++;
    }
  }

  return queryIndex === lowerQuery.length;
}

/**
 * Calculate match score for ranking
 * Higher score = better match
 */
function calculateScore(text: string, query: string): number {
  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();

  // Exact match = highest score
  if (lowerText === lowerQuery) return 1000;

  // Starts with query = high score
  if (lowerText.startsWith(lowerQuery)) return 500;

  // Contains query as substring = medium score
  if (lowerText.includes(lowerQuery)) return 250;

  // Fuzzy match = base score
  if (fuzzyMatch(text, query)) return 100;

  return 0;
}

/**
 * Recursively extract navigation items
 */
function extractNavItems(items: NavItem[], category: "navigation" = "navigation"): CommandItem[] {
  const result: CommandItem[] = [];

  for (const item of items) {
    result.push({
      id: item.href,
      label: item.label,
      href: item.href,
      icon: item.icon,
      category,
      keywords: [item.label.toLowerCase(), item.href.toLowerCase()],
      badge: item.badge as string | number | undefined,
    });

    // Add children recursively
    if (item.children && item.children.length > 0) {
      result.push(...extractNavItems(item.children, category));
    }
  }

  return result;
}

/**
 * Custom hook for Command Palette functionality
 *
 * Features:
 * - Keyboard shortcuts (Cmd/Ctrl+K)
 * - Fuzzy search across navigation items
 * - Recent pages integration
 * - Command execution
 * - Automatic close on navigation
 *
 * @returns {UseCommandPaletteReturn} Command palette state and actions
 *
 * @example
 * const { isOpen, toggle, filteredItems } = useCommandPalette();
 *
 * // Open with Cmd/Ctrl+K
 * // Search for "lead"
 * // Navigate with arrow keys
 */
export function useCommandPalette(): UseCommandPaletteReturn {
  const router = useRouter();
  const { recentPages } = useRecentPages();
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");

  /**
   * Open command palette
   */
  const open = useCallback(() => {
    setIsOpen(true);
    setQuery(""); // Reset query when opening
  }, []);

  /**
   * Close command palette
   */
  const close = useCallback(() => {
    setIsOpen(false);
    setQuery(""); // Reset query when closing
  }, []);

  /**
   * Toggle command palette
   */
  const toggle = useCallback(() => {
    setIsOpen((prev) => !prev);
    if (isOpen) {
      setQuery(""); // Reset query when closing
    }
  }, [isOpen]);

  /**
   * Build complete command list from navigation config and recent pages
   */
  const allCommands = useMemo((): CommandItem[] => {
    const commands: CommandItem[] = [];

    // Add navigation items from config
    for (const group of navigationConfig.groups) {
      commands.push(...extractNavItems(group.items));
    }

    // Add recent pages
    for (const page of recentPages) {
      // Check if not already in navigation
      if (!commands.find((cmd) => cmd.href === page.path)) {
        commands.push({
          id: `recent-${page.path}`,
          label: page.label,
          href: page.path,
          category: "recent",
          keywords: [page.label.toLowerCase(), page.path.toLowerCase()],
        });
      }
    }

    return commands;
  }, [recentPages]);

  /**
   * Filter and rank commands based on search query
   */
  const filteredItems = useMemo((): CommandItem[] => {
    if (!query.trim()) {
      // No query: show recent pages first, then navigation
      const recentItems = allCommands.filter((item) => item.category === "recent");
      const navItems = allCommands.filter((item) => item.category === "navigation").slice(0, 8);
      return [...recentItems, ...navItems];
    }

    // Filter and score items
    const scoredItems = allCommands
      .map((item) => {
        // Check label match
        const labelScore = calculateScore(item.label, query);

        // Check keywords match
        const keywordScore = Math.max(
          0,
          ...(item.keywords?.map((kw) => calculateScore(kw, query)) || [])
        );

        const score = Math.max(labelScore, keywordScore);

        return { item, score };
      })
      .filter(({ score }) => score > 0) // Only include matches
      .sort((a, b) => {
        // Sort by score (descending)
        if (b.score !== a.score) return b.score - a.score;

        // Tie-breaker: recent pages first
        if (a.item.category === "recent" && b.item.category !== "recent") return -1;
        if (a.item.category !== "recent" && b.item.category === "recent") return 1;

        // Tie-breaker: alphabetical
        return a.item.label.localeCompare(b.item.label);
      })
      .map(({ item }) => item)
      .slice(0, 10); // Limit to top 10 results

    return scoredItems;
  }, [query, allCommands]);

  /**
   * Execute a command (navigate to href or run action)
   */
  const executeCommand = useCallback(
    (item: CommandItem) => {
      if (item.action) {
        item.action();
      } else if (item.href) {
        router.push(item.href);
      }

      close();
    },
    [router, close]
  );

  /**
   * Set up keyboard shortcuts
   */
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // Cmd+K (Mac) or Ctrl+K (Windows/Linux)
      if ((event.metaKey || event.ctrlKey) && event.key === "k") {
        event.preventDefault();
        toggle();
      }

      // Escape to close
      if (event.key === "Escape" && isOpen) {
        event.preventDefault();
        close();
      }
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [toggle, close, isOpen]);

  return {
    isOpen,
    open,
    close,
    toggle,
    query,
    setQuery,
    filteredItems,
    executeCommand,
  };
}
