// src/hooks/useMediaQuery.ts
/**
 * Hook to detect media query matches (responsive breakpoints)
 *
 * Usage:
 * const isMobile = useMediaQuery("(max-width: 768px)");
 * const isDesktop = useMediaQuery("(min-width: 1024px)");
 */

import { useSyncExternalStore, useCallback } from "react";

export function useMediaQuery(query: string): boolean {
  // Subscribe function for useSyncExternalStore
  const subscribe = useCallback(
    (callback: () => void) => {
      const mediaQuery = window.matchMedia(query);
      mediaQuery.addEventListener("change", callback);
      return () => {
        mediaQuery.removeEventListener("change", callback);
      };
    },
    [query]
  );

  // Get current snapshot
  const getSnapshot = useCallback(() => {
    return window.matchMedia(query).matches;
  }, [query]);

  // Server snapshot (SSR safe - default to false)
  const getServerSnapshot = useCallback(() => {
    return false;
  }, []);

  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
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
