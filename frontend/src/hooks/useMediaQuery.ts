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
 * SAU hydrate nhưng TRƯỚC khi trình duyệt paint. Nhờ vậy MÀN CLIENT-SIDE NAV
 * paint thẳng layout đúng, KHÔNG nháy mobile→desktop như khi dùng
 * useSyncExternalStore (re-sync của nó xảy ra sau paint → nháy). Mobile giữ
 * nguyên (false → false).
 *
 * ⚠️ Giới hạn: trên HARD-LOAD (refresh / vào thẳng URL), trình duyệt paint HTML
 * server (matches=false) TRƯỚC khi bất kỳ JS nào — kể cả useLayoutEffect — chạy.
 * Nghĩa là `matches` một mình KHÔNG phân biệt được "đang là mobile thật" với
 * "chưa kịp đo viewport". Component cần render layout khác hẳn giữa 2 breakpoint
 * (vd master-detail split desktop vs card list mobile) PHẢI dùng
 * `useMediaQueryState().resolved` để hoãn nhánh tới khi đo xong viewport, tránh
 * nháy layout-sai (card-mobile → bảng-desktop) lúc hard-load.
 */

import { useEffect, useLayoutEffect, useState } from "react";

// useLayoutEffect chỉ chạy ở client; trên server React cảnh báo "does nothing on
// the server" → fallback useEffect ở server để im lặng (effect không chạy SSR).
const useIsomorphicLayoutEffect =
  typeof window !== "undefined" ? useLayoutEffect : useEffect;

interface MediaQueryState {
  /** Query có khớp không. `false` ở SSR + lần render client đầu (chưa đo). */
  matches: boolean;
  /**
   * Đã đo viewport thật chưa. `false` ở SSR + render đầu, `true` sau khi
   * useLayoutEffect chạy. Gate nhánh layout khác-hẳn-nhau bằng cờ này để
   * KHÔNG commit mobile/desktop trước khi biết viewport thật (chống nháy
   * layout-sai lúc hard-load — xem chú thích trên).
   */
  resolved: boolean;
}

/**
 * Như `useMediaQuery` nhưng trả kèm cờ `resolved` để phân biệt "mobile thật"
 * với "chưa đo viewport". Dùng khi 2 breakpoint render CÂY ELEMENT khác hẳn
 * nhau và nháy layout-sai lúc hard-load là không chấp nhận được.
 */
export function useMediaQueryState(query: string): MediaQueryState {
  // resolved=false ở SSR + lần render client đầu (hydrate) → khớp, không mismatch.
  const [state, setState] = useState<MediaQueryState>({
    matches: false,
    resolved: false,
  });

  useIsomorphicLayoutEffect(() => {
    const mediaQuery = window.matchMedia(query);
    // Set giá trị THẬT + đánh dấu resolved trước paint đầu (client-side nav).
    setState({ matches: mediaQuery.matches, resolved: true });

    const onChange = () =>
      setState({ matches: mediaQuery.matches, resolved: true });
    mediaQuery.addEventListener("change", onChange);
    return () => mediaQuery.removeEventListener("change", onChange);
  }, [query]);

  return state;
}

export function useMediaQuery(query: string): boolean {
  return useMediaQueryState(query).matches;
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
