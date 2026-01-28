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

import { useState, useEffect, useCallback } from "react";

export type Theme = "light" | "dark" | "system";

export interface UseThemeReturn {
  /** Current theme setting */
  theme: Theme;
  /** Whether dark mode is currently active (resolved from system if needed) */
  isDarkMode: boolean;
  /** Whether component has mounted (use for SSR hydration) */
  mounted: boolean;
}

/**
 * Hook to access current theme state
 */
export function useTheme(): UseThemeReturn {
  const [theme, setTheme] = useState<Theme>("system");
  const [isDarkMode, setIsDarkMode] = useState(false);
  const [mounted, setMounted] = useState(false);

  // Check if dark mode is active
  const checkDarkMode = useCallback(() => {
    if (typeof window === "undefined") return false;
    return document.documentElement.classList.contains("dark");
  }, []);

  useEffect(() => {
    setMounted(true);

    // Get saved theme
    const savedTheme = (localStorage.getItem("theme") as Theme) || "system";
    setTheme(savedTheme);

    // Check initial dark mode state
    setIsDarkMode(checkDarkMode());

    // Create observer to watch for class changes on <html>
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.attributeName === "class") {
          setIsDarkMode(checkDarkMode());
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
      setTimeout(() => setIsDarkMode(checkDarkMode()), 50);
    };
    mediaQuery.addEventListener("change", handleMediaChange);

    return () => {
      observer.disconnect();
      mediaQuery.removeEventListener("change", handleMediaChange);
    };
  }, [checkDarkMode]);

  return {
    theme,
    isDarkMode,
    mounted,
  };
}

export default useTheme;
