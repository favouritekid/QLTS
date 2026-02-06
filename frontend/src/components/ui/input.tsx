import * as React from "react"

import { cn } from "@/lib/utils"

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "flex w-full rounded-md border border-input bg-transparent px-3 shadow-sm transition-colors",
          // Mobile: taller input (44px touch target), 16px font to prevent iOS zoom
          "h-11 py-2 text-[16px]",
          // Desktop: compact
          "md:h-9 md:py-1 md:text-sm",
          // File input styles
          "file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground",
          // States
          "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = "Input"

export { Input }
