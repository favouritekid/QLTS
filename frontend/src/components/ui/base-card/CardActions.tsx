// src/components/ui/base-card/CardActions.tsx
import * as React from "react"
import { cn } from "@/lib/utils"

export interface CardActionsProps {
  children: React.ReactNode
  /** Additional className */
  className?: string
}

/**
 * CardActions - Container for action menu (⋮)
 *
 * Positioned absolutely in top-right corner by BaseCard.
 * Should contain a DropdownMenu or similar action trigger.
 *
 * Standard implementation:
 * - Desktop: DropdownMenu with MoreVertical icon
 * - Mobile: Can use ActionSheet via hook
 *
 * @example
 * ```tsx
 * <CardActions>
 *   <DropdownMenu>
 *     <DropdownMenuTrigger asChild>
 *       <Button variant="ghost" size="icon" className="h-8 w-8">
 *         <MoreVertical className="h-4 w-4" />
 *       </Button>
 *     </DropdownMenuTrigger>
 *     <DropdownMenuContent align="end">
 *       <DropdownMenuItem>View</DropdownMenuItem>
 *       <DropdownMenuItem>Edit</DropdownMenuItem>
 *       <DropdownMenuSeparator />
 *       <DropdownMenuItem className="text-destructive">Delete</DropdownMenuItem>
 *     </DropdownMenuContent>
 *   </DropdownMenu>
 * </CardActions>
 * ```
 */
export function CardActions({ children, className }: CardActionsProps) {
  return (
    <div
      className={cn("flex items-center", className)}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </div>
  )
}

CardActions.displayName = "CardActions"
