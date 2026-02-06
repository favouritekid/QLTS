// src/hooks/useSwipeNavigation.ts
/**
 * useSwipeNavigation - Hook for swipe-based navigation on mobile
 *
 * Features:
 * - Swipe left/right to navigate between tabs/pages
 * - Configurable swipe threshold and velocity
 * - Respects reduced motion preference
 * - Touch-only (no mouse tracking for desktop)
 *
 * Usage:
 * ```tsx
 * const { handlers, isSwiping } = useSwipeNavigation({
 *   onSwipeLeft: () => setActiveTab(prev => Math.min(prev + 1, maxTab)),
 *   onSwipeRight: () => setActiveTab(prev => Math.max(prev - 1, 0)),
 * });
 *
 * return <div {...handlers}>{children}</div>;
 * ```
 */

import { useSwipeable, SwipeEventData } from "react-swipeable";
import { useState, useCallback, useMemo } from "react";

interface UseSwipeNavigationOptions {
  /** Callback when swiping left (navigate forward) */
  onSwipeLeft?: () => void;
  /** Callback when swiping right (navigate backward) */
  onSwipeRight?: () => void;
  /** Callback when swiping up */
  onSwipeUp?: () => void;
  /** Callback when swiping down */
  onSwipeDown?: () => void;
  /** Minimum distance in pixels to trigger swipe (default: 50) */
  delta?: number;
  /** Maximum time in ms for swipe to complete (default: 500) */
  swipeDuration?: number;
  /** Minimum velocity required (default: 0.3) */
  velocity?: number;
  /** Whether to prevent scroll while swiping horizontally (default: true) */
  preventScrollOnSwipe?: boolean;
  /** Disabled state */
  disabled?: boolean;
}

interface UseSwipeNavigationReturn {
  /** Spread these handlers on the swipeable container */
  handlers: ReturnType<typeof useSwipeable>;
  /** Whether a swipe is currently in progress */
  isSwiping: boolean;
  /** Current swipe direction if swiping */
  swipeDirection: "left" | "right" | "up" | "down" | null;
  /** Swipe progress (0-1) for animation purposes */
  swipeProgress: number;
}

export function useSwipeNavigation({
  onSwipeLeft,
  onSwipeRight,
  onSwipeUp,
  onSwipeDown,
  delta = 50,
  swipeDuration = 500,
  velocity = 0.3,
  preventScrollOnSwipe = true,
  disabled = false,
}: UseSwipeNavigationOptions): UseSwipeNavigationReturn {
  const [isSwiping, setIsSwiping] = useState(false);
  const [swipeDirection, setSwipeDirection] = useState<"left" | "right" | "up" | "down" | null>(null);
  const [swipeProgress, setSwipeProgress] = useState(0);

  // Check for reduced motion preference
  const prefersReducedMotion = useMemo(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }, []);

  const handleSwipeStart = useCallback(() => {
    if (disabled) return;
    setIsSwiping(true);
  }, [disabled]);

  const handleSwiping = useCallback(
    (eventData: SwipeEventData) => {
      if (disabled) return;

      const { dir, deltaX, deltaY } = eventData;
      setSwipeDirection(dir.toLowerCase() as "left" | "right" | "up" | "down");

      // Calculate progress based on direction
      const progress = Math.min(
        Math.abs(dir === "Left" || dir === "Right" ? deltaX : deltaY) / 150,
        1
      );
      setSwipeProgress(progress);
    },
    [disabled]
  );

  const handleSwipedLeft = useCallback(() => {
    if (disabled || prefersReducedMotion) return;
    onSwipeLeft?.();
  }, [disabled, prefersReducedMotion, onSwipeLeft]);

  const handleSwipedRight = useCallback(() => {
    if (disabled || prefersReducedMotion) return;
    onSwipeRight?.();
  }, [disabled, prefersReducedMotion, onSwipeRight]);

  const handleSwipedUp = useCallback(() => {
    if (disabled || prefersReducedMotion) return;
    onSwipeUp?.();
  }, [disabled, prefersReducedMotion, onSwipeUp]);

  const handleSwipedDown = useCallback(() => {
    if (disabled || prefersReducedMotion) return;
    onSwipeDown?.();
  }, [disabled, prefersReducedMotion, onSwipeDown]);

  const handleSwipeEnd = useCallback(() => {
    setIsSwiping(false);
    setSwipeDirection(null);
    setSwipeProgress(0);
  }, []);

  const handlers = useSwipeable({
    onSwipeStart: handleSwipeStart,
    onSwiping: handleSwiping,
    onSwipedLeft: handleSwipedLeft,
    onSwipedRight: handleSwipedRight,
    onSwipedUp: handleSwipedUp,
    onSwipedDown: handleSwipedDown,
    onSwiped: handleSwipeEnd,
    trackMouse: false, // Touch only
    trackTouch: !disabled,
    delta,
    swipeDuration,
    preventScrollOnSwipe,
  });

  return {
    handlers,
    isSwiping,
    swipeDirection,
    swipeProgress,
  };
}

export default useSwipeNavigation;
