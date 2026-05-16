// src/hooks/useRecentPages.ts
/**
 * Custom hook for tracking recently visited pages
 * Provides quick access to frequently used pages in navigation
 */
import { useState, useEffect, useCallback, useMemo } from "react";
import { usePathname } from "next/navigation";
import { navigationConfig } from "@/lib/config/navigation";
import { useAuthStore } from "@/lib/stores/auth.store";
import type { NavItem } from "@/types/navigation";

const STORAGE_KEY = "recent-pages";
const MAX_RECENT_ITEMS = 5;
// ✅ VERSIONING: Increment when RecentPage schema changes
const STORAGE_VERSION = 1;

interface VersionedStorage {
  version: number;
  data: RecentPage[];
}

/**
 * Recent page item type
 */
export interface RecentPage {
  path: string;
  label: string;
  timestamp: number;
  visits: number;
}

/**
 * Find the NavItem matching `path` in the navigation tree (recursive).
 * Returns null if no item matches (e.g. dynamic detail routes like /leads/123).
 */
function findItemInNavigation(path: string, items?: NavItem[]): NavItem | null {
  if (!items) {
    for (const group of navigationConfig.groups) {
      const found = findItemInNavigation(path, group.items);
      if (found) return found;
    }
    return null;
  }
  for (const item of items) {
    if (item.href === path) return item;
    if (item.children && item.children.length > 0) {
      const childMatch = findItemInNavigation(path, item.children);
      if (childMatch) return childMatch;
    }
  }
  return null;
}

/**
 * Decide whether `path` is accessible to a user with given `role`.
 *
 * Rules:
 * - Path matches a NavItem with `roles` declared → user role must be in that list.
 * - Path matches a NavItem with `excludeRoles` containing the user's role → deny.
 * - Path doesn't match any NavItem (dynamic detail like /leads/123) → allow
 *   (route guards on the page itself bounce unauthorized users; we don't
 *   want to over-prune detail pages from the recents list).
 *
 * Why this matters: F4 fix — `useRecentPages` writes ANY visited URL to
 * localStorage which persists across login sessions. Without this filter,
 * an admin URL visited in a prior session leaks into the next user's
 * sidebar (officer/accountant) even though they cannot reach the page.
 */
function isPathAccessibleByRole(path: string, role: string | undefined): boolean {
  if (!role) return false;
  const item = findItemInNavigation(path);
  if (!item) return true;
  if (item.excludeRoles && item.excludeRoles.includes(role)) return false;
  if (!item.roles || item.roles.length === 0) return true;
  return item.roles.includes(role);
}

/**
 * Find label for a path in navigation config
 */
function findLabelInNavigation(path: string, items?: NavItem[]): string | null {
  if (!items) {
    for (const group of navigationConfig.groups) {
      const label = findLabelInNavigation(path, group.items);
      if (label) return label;
    }
    return null;
  }

  for (const item of items) {
    if (item.href === path) {
      return item.label;
    }
    if (item.children && item.children.length > 0) {
      const childLabel = findLabelInNavigation(path, item.children);
      if (childLabel) return childLabel;
    }
  }

  return null;
}

/**
 * Convert pathname to readable label
 */
function pathToLabel(path: string): string {
  // Try to find from navigation config first
  const configLabel = findLabelInNavigation(path);
  if (configLabel) return configLabel;

  // Fallback: convert path to readable text
  const segments = path.split("/").filter(Boolean);
  const lastSegment = segments[segments.length - 1];

  return lastSegment
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * Load recent pages from localStorage (with versioning)
 */
function loadRecentPages(): RecentPage[] {
  if (typeof window === "undefined") return [];

  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);

      // ✅ VERSIONING: Check version and reset if mismatched
      if (parsed?.version !== STORAGE_VERSION) {
        localStorage.removeItem(STORAGE_KEY);
        return [];
      }

      return Array.isArray(parsed.data) ? parsed.data : [];
    }
  } catch (error) {
    console.warn("Failed to load recent pages from localStorage:", error);
    localStorage.removeItem(STORAGE_KEY);
  }

  return [];
}

/**
 * Save recent pages to localStorage (with versioning)
 */
function saveRecentPages(pages: RecentPage[]): void {
  if (typeof window === "undefined") return;

  try {
    // ✅ VERSIONING: Store with version for schema compatibility
    const versioned: VersionedStorage = {
      version: STORAGE_VERSION,
      data: pages,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(versioned));
  } catch (error) {
    console.warn("Failed to save recent pages to localStorage:", error);
  }
}

/**
 * Check if a path should be tracked
 * Skip certain paths like root, auth pages, etc.
 */
function shouldTrackPath(path: string): boolean {
  // Skip root and dashboard
  if (path === "/" || path === "/dashboard") return false;

  // Skip auth pages
  if (path.startsWith("/login") || path.startsWith("/register")) return false;

  // Skip settings (could be noisy)
  // Uncomment if you want to skip settings pages
  // if (path.startsWith("/settings")) return false;

  return true;
}

/**
 * Hook return type
 */
interface UseRecentPagesReturn {
  /**
   * List of recent pages sorted by timestamp (most recent first)
   */
  recentPages: RecentPage[];
  /**
   * Clear all recent pages
   */
  clearRecent: () => void;
  /**
   * Remove a specific page from recent
   */
  removePage: (path: string) => void;
}

/**
 * Custom hook that tracks and manages recently visited pages
 *
 * Features:
 * - Automatic tracking of page visits
 * - Persistent storage in localStorage
 * - Smart sorting (most recent + most visited)
 * - Configurable max items
 * - SSR-safe
 *
 * @param maxItems - Maximum number of recent items to keep (default: 5)
 * @returns {UseRecentPagesReturn} Recent pages management
 *
 * @example
 * const { recentPages, clearRecent } = useRecentPages();
 *
 * {recentPages.map(page => (
 *   <Link key={page.path} href={page.path}>
 *     {page.label}
 *   </Link>
 * ))}
 */
export function useRecentPages(maxItems: number = MAX_RECENT_ITEMS): UseRecentPagesReturn {
  const pathname = usePathname();
  const userRole = useAuthStore((s) => s.user?.role);
  // Start with empty state to match SSR output
  const [recentPages, setRecentPages] = useState<RecentPage[]>([]);
  // Track hydration state with useState to trigger re-render
  const [isHydrated, setIsHydrated] = useState(false);

  // Load from localStorage AFTER mount (client-side only)
  useEffect(() => {
    const stored = loadRecentPages();
    // Use queueMicrotask to avoid synchronous setState in effect
    queueMicrotask(() => {
      setRecentPages(stored);
      setIsHydrated(true);
    });
  }, []);

  // Track current page visit
  useEffect(() => {
    if (!isHydrated || !pathname || !shouldTrackPath(pathname)) {
      return;
    }

    // Use queueMicrotask to defer state update and avoid synchronous setState warning
    queueMicrotask(() => {
      setRecentPages((prev) => {
        const existing = prev.find((p) => p.path === pathname);

        if (existing) {
          // Update existing entry
          const updated = prev.map((p) =>
            p.path === pathname
              ? {
                  ...p,
                  timestamp: Date.now(),
                  visits: p.visits + 1,
                }
              : p
          );

          // Sort by timestamp (most recent first)
          const sorted = updated.sort((a, b) => b.timestamp - a.timestamp);
          saveRecentPages(sorted);
          return sorted;
        } else {
          // Add new entry
          const label = pathToLabel(pathname);
          const newPage: RecentPage = {
            path: pathname,
            label,
            timestamp: Date.now(),
            visits: 1,
          };

          const updated = [newPage, ...prev].slice(0, maxItems);
          saveRecentPages(updated);
          return updated;
        }
      });
    });
  }, [pathname, maxItems, isHydrated]);

  /**
   * Clear all recent pages
   */
  const clearRecent = useCallback(() => {
    setRecentPages([]);
    saveRecentPages([]);
  }, []);

  /**
   * Remove a specific page from recent
   */
  const removePage = useCallback((path: string) => {
    setRecentPages((prev) => {
      const updated = prev.filter((p) => p.path !== path);
      saveRecentPages(updated);
      return updated;
    });
  }, []);

  // F4 fix: filter out pages the current user cannot access. localStorage
  // persists across logins, so an admin URL from a prior session would
  // otherwise leak into the next user's sidebar.
  const accessibleRecentPages = useMemo(
    () => recentPages.filter((page) => isPathAccessibleByRole(page.path, userRole)),
    [recentPages, userRole],
  );

  return {
    recentPages: accessibleRecentPages,
    clearRecent,
    removePage,
  };
}
