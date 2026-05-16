"use client"

import * as React from "react"
import * as ProgressPrimitive from "@radix-ui/react-progress"

import { cn } from "@/lib/utils"

export interface ProgressProps extends React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> {
  indicatorClassName?: string;
}

const Progress = React.forwardRef<
  React.ElementRef<typeof ProgressPrimitive.Root>,
  ProgressProps
>(({ className, value, indicatorClassName, ...props }, ref) => {
  // Wave 6 R-INFO-1 (Lighthouse aria-progressbar-name): Radix Root
  // renders role="progressbar" but without aria-label/labelledby, screen
  // readers announce a generic "X percent". Default to a Vietnamese
  // label that includes the current value; callers can override via
  // aria-label prop when they have richer context (e.g. "Tiến trình
  // hồ sơ"). Only apply default when caller did NOT supply either.
  const ariaLabel =
    props["aria-label"] ?? props["aria-labelledby"]
      ? props["aria-label"]
      : `Tiến trình ${value ?? 0}%`
  return (
  <ProgressPrimitive.Root
    ref={ref}
    aria-label={ariaLabel}
    className={cn(
      "relative h-2 w-full overflow-hidden rounded-full bg-primary/20",
      className
    )}
    {...props}
  >
    <ProgressPrimitive.Indicator
      className={cn("h-full w-full flex-1 bg-primary transition-[width]", indicatorClassName)}
      style={{ transform: `translateX(-${100 - Math.min(100, Math.max(0, value || 0))}%)` }}
    />
  </ProgressPrimitive.Root>
  )
})
Progress.displayName = ProgressPrimitive.Root.displayName

export { Progress }
