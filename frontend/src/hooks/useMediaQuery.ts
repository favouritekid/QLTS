// src/hooks/useMediaQuery.ts
/**
 * Hook to detect media query matches (responsive breakpoints)
 *
 * Usage:
 * const isMobile = useMediaQuery("(max-width: 768px)");
 * const isDesktop = useMediaQuery("(min-width: 1024px)");
 */

import { useState, useEffect } from "react";

export function useMediaQuery(query: string): boolean {
  // Default to false on server (SSR safe)
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    // Create media query list
    const mediaQuery = window.matchMedia(query);

    // Set initial value
    setMatches(mediaQuery.matches);

    // Define handler
    const handler = (event: MediaQueryListEvent) => {
      setMatches(event.matches);
    };

    // Add listener
    mediaQuery.addEventListener("change", handler);

    // Cleanup
    return () => {
      mediaQuery.removeEventListener("change", handler);
    };
  }, [query]);

  return matches;
}

// Convenience hooks for common breakpoints (Tailwind defaults)
export function useIsMobile(): boolean {
  return useMediaQuery("(max-width: 767px)");
}

export function useIsTablet(): boolean {
  return useMediaQuery("(min-width: 768px) and (max-width: 1023px)");
}

export function useIsDesktop(): boolean {
  return useMediaQuery("(min-width: 1024px)");
}
