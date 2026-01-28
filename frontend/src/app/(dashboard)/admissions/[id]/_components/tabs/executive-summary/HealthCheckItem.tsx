/**
 * HealthCheckItem Component
 *
 * Shared component for displaying step status in Health Check Grid.
 * Used by: LegalDocsCard, AcademicCard, AdminCard
 */

"use client"

import { cn } from "@/lib/utils"
import { CheckCircle2, AlertTriangle, XCircle, Lock } from "lucide-react"
import { Badge } from "@/components/ui/badge"

interface HealthCheckItemProps {
  label: string
  status: "success" | "warning" | "error" | "locked"
  errorCount?: number
  className?: string
}

export function HealthCheckItem({
  label,
  status,
  errorCount,
  className,
}: HealthCheckItemProps) {
  const config = {
    success: {
      icon: CheckCircle2,
      color: "text-success-600",
      bg: "bg-success-50",
      border: "border-success-200",
    },
    warning: {
      icon: AlertTriangle,
      color: "text-warning-600",
      bg: "bg-warning-50",
      border: "border-warning-200",
    },
    error: {
      icon: XCircle,
      color: "text-error-600",
      bg: "bg-error-50",
      border: "border-error-200",
    },
    locked: {
      icon: Lock,
      color: "text-muted-foreground",
      bg: "bg-muted",
      border: "border-border",
    },
  }

  const c = config[status]
  const Icon = c.icon

  return (
    <div
      className={cn(
        "flex items-center justify-between p-2.5 rounded-lg border transition-colors",
        c.bg,
        c.border,
        className
      )}
    >
      <div className="flex items-center gap-2">
        <Icon className={cn("w-4 h-4", c.color)} />
        <span className="text-sm font-medium">{label}</span>
      </div>

      {errorCount !== undefined && errorCount > 0 && (
        <Badge variant="destructive" className="text-xs font-semibold">
          {errorCount} lỗi
        </Badge>
      )}
    </div>
  )
}
