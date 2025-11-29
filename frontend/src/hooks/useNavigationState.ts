// src/hooks/useNavigationState.ts
/**
 * Custom hook for managing navigation group collapse state
 * Persists state in localStorage for better UX
 */
import { useState, useCallback, useEffect } from "react";

const STORAGE_KEY = "navigation-collapsed-groups";

/**
 * Hook return type
 */
interface UseNavigationStateReturn {
  /**
   * Check if a group is collapsed
   */
  isCollapsed: (groupTitle: string) => boolean;
  /**
   * Toggle collapse state of a group
   */
  toggleGroup: (groupTitle: string) => void;
  /**
   * Collapse a specific group
   */
  collapseGroup: (groupTitle: string) => void;
  /**
   * Expand a specific group
   */
  expandGroup: (groupTitle: string) => void;
  /**
   * Collapse all groups
   */
  collapseAll: () => void;
  /**
   * Expand all groups
   */
  expandAll: () => void;
}

/**
 * Load collapsed groups from localStorage
 */
function loadCollapsedGroups(): Set<string> {
  if (typeof window === "undefined") return new Set();

  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      return new Set(Array.isArray(parsed) ? parsed : []);
    }
  } catch (error) {
    console.warn("Failed to load navigation state from localStorage:", error);
  }

  return new Set();
}

/**
 * Save collapsed groups to localStorage
 */
function saveCollapsedGroups(collapsedGroups: Set<string>): void {
  if (typeof window === "undefined") return;

  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(collapsedGroups)));
  } catch (error) {
    console.warn("Failed to save navigation state to localStorage:", error);
  }
}

/**
 * Custom hook that manages navigation group collapse state
 * with localStorage persistence
 *
 * Features:
 * - Persistent state across page refreshes
 * - Per-group collapse/expand
 * - Bulk collapse/expand all
 * - SSR-safe (no hydration errors)
 *
 * @returns {UseNavigationStateReturn} Navigation state management functions
 *
 * @example
 * const { isCollapsed, toggleGroup } = useNavigationState();
 *
 * <button onClick={() => toggleGroup("System")}>
 *   Toggle System Group
 * </button>
 *
 * {!isCollapsed("System") && <SystemItems />}
 */
export function useNavigationState(): UseNavigationStateReturn {
  // Initialize state from localStorage (client-side only)
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [isHydrated, setIsHydrated] = useState(false);

  // Load from localStorage on mount (avoid hydration mismatch)
  useEffect(() => {
    setCollapsedGroups(loadCollapsedGroups());
    setIsHydrated(true);
  }, []);

  // Save to localStorage whenever state changes
  useEffect(() => {
    if (isHydrated) {
      saveCollapsedGroups(collapsedGroups);
    }
  }, [collapsedGroups, isHydrated]);

  /**
   * Check if a group is collapsed
   */
  const isCollapsed = useCallback(
    (groupTitle: string): boolean => {
      // During SSR or before hydration, default to expanded
      if (!isHydrated) return false;
      return collapsedGroups.has(groupTitle);
    },
    [collapsedGroups, isHydrated]
  );

  /**
   * Toggle collapse state of a group
   */
  const toggleGroup = useCallback((groupTitle: string): void => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupTitle)) {
        next.delete(groupTitle);
      } else {
        next.add(groupTitle);
      }
      return next;
    });
  }, []);

  /**
   * Collapse a specific group
   */
  const collapseGroup = useCallback((groupTitle: string): void => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      next.add(groupTitle);
      return next;
    });
  }, []);

  /**
   * Expand a specific group
   */
  const expandGroup = useCallback((groupTitle: string): void => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      next.delete(groupTitle);
      return next;
    });
  }, []);

  /**
   * Collapse all groups
   */
  const collapseAll = useCallback((): void => {
    // This would need access to all group titles
    // For now, just clear the set (which means expand all)
    // To properly implement, we'd need to pass available groups
    console.warn("collapseAll not fully implemented - needs group titles");
  }, []);

  /**
   * Expand all groups
   */
  const expandAll = useCallback((): void => {
    setCollapsedGroups(new Set());
  }, []);

  return {
    isCollapsed,
    toggleGroup,
    collapseGroup,
    expandGroup,
    collapseAll,
    expandAll,
  };
}
