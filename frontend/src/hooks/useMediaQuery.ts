// src/hooks/useMediaQuery.ts
/**
 * Hook to detect media query matches (responsive breakpoints)
 *
 * Usage:
 * const isMobile = useMediaQuery("(max-width: 768px)");
 * const isDesktop = useMediaQuery("(min-width: 1024px)");
 *
 * SSR-safe + KHÔNG flash: giá trị khởi tạo = false (khớp SSR → không hydration
 * mismatch), rồi được set về giá trị THẬT trong useLayoutEffect — chạy đồng bộ
 * SAU hydrate nhưng TRƯỚC khi trình duyệt paint. Nhờ vậy màn desktop paint thẳng
 * layout desktop, KHÔNG nháy mobile→desktop như khi dùng useSyncExternalStore
 * (re-sync của nó xảy ra sau paint → nháy). Mobile giữ nguyên (false → false).
 */

import { useEffect, useLayoutEffect, useState } from "react";

// useLayoutEffect chỉ chạy ở client; trên server React cảnh báo "does nothing on
// the server" → fallback useEffect ở server để im lặng (effect không chạy SSR).
const useIsomorphicLayoutEffect =
  typeof window !== "undefined" ? useLayoutEffect : useEffect;

export function useMediaQuery(query: string): boolean {
  // false ở SSR + lần render client đầu (hydrate) → khớp, không mismatch.
  const [matches, setMatches] = useState(false);

  useIsomorphicLayoutEffect(() => {
    const mediaQuery = window.matchMedia(query);
    // Set giá trị THẬT trước paint đầu tiên → không flash.
    setMatches(mediaQuery.matches);

    const onChange = () => setMatches(mediaQuery.matches);
    mediaQuery.addEventListener("change", onChange);
    return () => mediaQuery.removeEventListener("change", onChange);
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
