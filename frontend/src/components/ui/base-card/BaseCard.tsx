// src/components/ui/base-card/BaseCard.tsx
"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { Checkbox } from "@/components/ui/checkbox"

export interface BaseCardProps {
  children: React.ReactNode
  /** Whether this card is selected */
  selected?: boolean
  /** Callback when selection changes */
  onSelect?: (selected: boolean) => void
  /** Show checkbox for selection */
  showCheckbox?: boolean
  /** Additional className */
  className?: string
  /** Click handler for the card (excluding checkbox area) */
  onClick?: () => void
}

/**
 * BaseCard - The root container for mobile data cards
 *
 * Standard layout:
 * ┌─────────────────────────────────────────┐
 * │ [☑] CardHeader          [Actions ⋮]    │
 * │     CardBody                            │
 * │     CardMeta                            │
 * └─────────────────────────────────────────┘
 *
 * @example
 * ```tsx
 * <BaseCard selected={isSelected} onSelect={setSelected} showCheckbox>
 *   <CardHeader title="Nguyễn Văn A" subtitle="Lead #123" />
 *   <CardBody>
 *     <CardField label="Email" value="user@example.com" />
 *   </CardBody>
 *   <CardMeta>
 *     <Badge>Active</Badge>
 *   </CardMeta>
 *   <CardActions>
 *     <DropdownMenu>...</DropdownMenu>
 *   </CardActions>
 * </BaseCard>
 * ```
 */
export function BaseCard({
  children,
  selected = false,
  onSelect,
  showCheckbox = true,
  className,
  onClick,
}: BaseCardProps) {
  // Separate CardActions from other children to position it absolutely
  const childArray = React.Children.toArray(children)
  const actionsChild = childArray.find(
    (child) => React.isValidElement(child) && child.type && (child.type as any).displayName === "CardActions"
  )
  const otherChildren = childArray.filter(
    (child) => !(React.isValidElement(child) && child.type && (child.type as any).displayName === "CardActions")
  )

  return (
    <div
      className={cn(
        // Base styles
        "relative rounded-lg border bg-card p-4",
        // Selection ring
        selected && "ring-2 ring-primary ring-offset-1",
        // Hover state
        onClick && "cursor-pointer hover:bg-accent/50 transition-colors",
        className
      )}
      onClick={onClick}
    >
      <div className="flex gap-3">
        {/* Checkbox column */}
        {showCheckbox && (
          <div className="flex-shrink-0 pt-0.5">
            <Checkbox
              checked={selected}
              onCheckedChange={(checked) => onSelect?.(checked === true)}
              onClick={(e) => e.stopPropagation()}
              aria-label="Select item"
            />
          </div>
        )}

        {/* Main content column */}
        <div className="flex-1 min-w-0 space-y-2">
          {otherChildren}
        </div>
      </div>

      {/* Actions positioned absolutely in top-right */}
      {actionsChild && (
        <div className="absolute top-3 right-3">
          {actionsChild}
        </div>
      )}
    </div>
  )
}

BaseCard.displayName = "BaseCard"
