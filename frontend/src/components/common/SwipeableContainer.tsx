// src/components/common/SwipeableContainer.tsx
/**
 * SwipeableContainer - Wrapper component for swipe gestures
 *
 * Makes any content swipeable on mobile devices.
 * Commonly used for:
 * - Tab navigation
 * - Card carousels
 * - Panel switching
 * - Dismissible elements
 *
 * Usage:
 * ```tsx
 * <SwipeableContainer
 *   onSwipeLeft={() => nextTab()}
 *   onSwipeRight={() => prevTab()}
 * >
 *   <TabContent />
 * </SwipeableContainer>
 * ```
 */
"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { useSwipeNavigation } from "@/hooks/useSwipeNavigation";

interface SwipeableContainerProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Callback when swiping left */
  onSwipeLeft?: () => void;
  /** Callback when swiping right */
  onSwipeRight?: () => void;
  /** Callback when swiping up */
  onSwipeUp?: () => void;
  /** Callback when swiping down */
  onSwipeDown?: () => void;
  /** Minimum swipe distance (default: 50) */
  threshold?: number;
  /** Disable swipe gestures */
  disabled?: boolean;
  /** Show visual feedback during swipe */
  showFeedback?: boolean;
  /** Children content */
  children: React.ReactNode;
}

export function SwipeableContainer({
  onSwipeLeft,
  onSwipeRight,
  onSwipeUp,
  onSwipeDown,
  threshold = 50,
  disabled = false,
  showFeedback = false,
  children,
  className,
  ...props
}: SwipeableContainerProps) {
  const { handlers, isSwiping, swipeDirection, swipeProgress } = useSwipeNavigation({
    onSwipeLeft,
    onSwipeRight,
    onSwipeUp,
    onSwipeDown,
    delta: threshold,
    disabled,
  });

  // Calculate transform for visual feedback
  const getTransformStyle = React.useMemo(() => {
    if (!showFeedback || !isSwiping) return {};

    const maxOffset = 20; // Max pixels to move
    const offset = swipeProgress * maxOffset;

    switch (swipeDirection) {
      case "left":
        return { transform: `translateX(-${offset}px)` };
      case "right":
        return { transform: `translateX(${offset}px)` };
      case "up":
        return { transform: `translateY(-${offset}px)` };
      case "down":
        return { transform: `translateY(${offset}px)` };
      default:
        return {};
    }
  }, [showFeedback, isSwiping, swipeDirection, swipeProgress]);

  return (
    <div
      {...handlers}
      {...props}
      className={cn(
        "touch-pan-y", // Allow vertical scroll by default
        showFeedback && "transition-transform duration-75",
        className
      )}
      style={{
        ...props.style,
        ...getTransformStyle,
      }}
    >
      {children}
    </div>
  );
}

// =============================================================================
// SWIPEABLE TABS - Pre-built component for tab navigation
// =============================================================================

interface SwipeableTabsProps {
  /** Current active tab index */
  activeIndex: number;
  /** Callback when tab changes */
  onTabChange: (index: number) => void;
  /** Total number of tabs */
  tabCount: number;
  /** Children (tab content) */
  children: React.ReactNode;
  /** Additional className */
  className?: string;
  /** Disable swipe */
  disabled?: boolean;
}

export function SwipeableTabs({
  activeIndex,
  onTabChange,
  tabCount,
  children,
  className,
  disabled = false,
}: SwipeableTabsProps) {
  const handleSwipeLeft = React.useCallback(() => {
    if (activeIndex < tabCount - 1) {
      onTabChange(activeIndex + 1);
    }
  }, [activeIndex, tabCount, onTabChange]);

  const handleSwipeRight = React.useCallback(() => {
    if (activeIndex > 0) {
      onTabChange(activeIndex - 1);
    }
  }, [activeIndex, onTabChange]);

  return (
    <SwipeableContainer
      onSwipeLeft={handleSwipeLeft}
      onSwipeRight={handleSwipeRight}
      disabled={disabled}
      showFeedback
      className={cn("overflow-hidden", className)}
    >
      {children}
    </SwipeableContainer>
  );
}

// =============================================================================
// DISMISSIBLE CONTAINER - Swipe to dismiss
// =============================================================================

interface DismissibleContainerProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Callback when dismissed (swipe left or right) */
  onDismiss: () => void;
  /** Direction to allow dismiss */
  dismissDirection?: "left" | "right" | "both";
  /** Children content */
  children: React.ReactNode;
}

export function DismissibleContainer({
  onDismiss,
  dismissDirection = "both",
  children,
  className,
  ...props
}: DismissibleContainerProps) {
  return (
    <SwipeableContainer
      onSwipeLeft={dismissDirection !== "right" ? onDismiss : undefined}
      onSwipeRight={dismissDirection !== "left" ? onDismiss : undefined}
      showFeedback
      className={className}
      {...props}
    >
      {children}
    </SwipeableContainer>
  );
}

export default SwipeableContainer;
