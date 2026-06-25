import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import {
  BATCH_STATUS_CONFIG,
  ROW_STATUS_CONFIG,
} from "@/lib/zod/payment-import"

/** Badge cho status dòng (matched/warned/error) — fallback nếu status lạ. */
export function RowStatusBadge({ status }: { status: string }) {
  const cfg = ROW_STATUS_CONFIG[status]
  return (
    <Badge
      variant="outline"
      className={cn("font-medium", cfg?.className)}
    >
      {cfg?.label ?? status}
    </Badge>
  )
}

/** Badge cho status lô (preview/committed/void) — fallback nếu status lạ. */
export function BatchStatusBadge({ status }: { status: string }) {
  const cfg = BATCH_STATUS_CONFIG[status]
  return (
    <Badge
      variant="outline"
      className={cn("font-medium", cfg?.className)}
    >
      {cfg?.label ?? status}
    </Badge>
  )
}
