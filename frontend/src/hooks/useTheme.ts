// src/hooks/useTheme.ts
/**
 * useTheme - Hook for accessing current theme state
 *
 * Provides reactive access to the current theme (light/dark/system)
 * and computed isDarkMode value.
 *
 * @example
 * ```tsx
 * const { isDarkMode, theme } = useTheme();
 *
 * // Use for conditional styling
 * const bgColor = isDarkMode ? "#1f2937" : "#ffffff";
 * ```
 */

"use client";

import { useSyncExternalStore, useCallback } from "react";

export type Theme = "light" | "dark" | "system";

// ✅ VALIDATION: Valid theme values for schema compatibility
const VALID_THEMES: Theme[] = ["light", "dark", "system"];

export interface UseThemeReturn {
  /** Current theme setting */
  theme: Theme;
  /** Whether dark mode is currently active (resolved from system if needed) */
  isDarkMode: boolean;
  /** Whether component has mounted (use for SSR hydration) */
  mounted: boolean;
}

// Check if dark mode is active by looking at document class
function checkDarkMode(): boolean {
  if (typeof window === "undefined") return false;
  return document.documentElement.classList.contains("dark");
}

// Get current theme from localStorage (with validation)
function getTheme(): Theme {
  if (typeof window === "undefined") return "system";
  const stored = localStorage.getItem("theme");
  // ✅ VALIDATION: Reset invalid values to prevent schema issues
  if (stored && VALID_THEMES.includes(stored as Theme)) {
    return stored as Theme;
  }
  return "system";
}

/**
 * Hook to access current theme state
 */
export function useTheme(): UseThemeReturn {
  // Subscribe to dark mode changes via MutationObserver
  const subscribeDarkMode = useCallback((callback: () => void) => {
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.attributeName === "class") {
          callback();
        }
      });
    });

    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });

    // Also listen for system preference changes
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleMediaChange = () => {
      // Re-check after a small delay to let ThemeToggle update classes
      setTimeout(callback, 50);
    };
    mediaQuery.addEventListener("change", handleMediaChange);

    return () => {
      observer.disconnect();
      mediaQuery.removeEventListener("change", handleMediaChange);
    };
  }, []);

  // Subscribe to theme changes via storage event
  const subscribeTheme = useCallback((callback: () => void) => {
    const handleStorage = (e: StorageEvent) => {
      if (e.key === "theme") {
        callback();
      }
    };
    window.addEventListener("storage", handleStorage);
    return () => {
      window.removeEventListener("storage", handleStorage);
    };
  }, []);

  // Use useSyncExternalStore for reactive state
  const isDarkMode = useSyncExternalStore(
    subscribeDarkMode,
    checkDarkMode,
    () => false // Server snapshot
  );

  const theme = useSyncExternalStore(
    subscribeTheme,
    getTheme,
    () => "system" as Theme // Server snapshot
  );

  // For mounted, we can use useSyncExternalStore with a simple check
  const mounted = useSyncExternalStore(
    () => () => {}, // No subscription needed
    () => true, // Client is always mounted
    () => false // Server is not mounted
  );

  return {
    theme,
    isDarkMode,
    mounted,
  };
}

export default useTheme;
