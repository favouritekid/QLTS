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
      color: "text-green-600",
      bg: "bg-green-50",
      border: "border-green-200",
    },
    warning: {
      icon: AlertTriangle,
      color: "text-amber-600",
      bg: "bg-amber-50",
      border: "border-amber-200",
    },
    error: {
      icon: XCircle,
      color: "text-red-600",
      bg: "bg-red-50",
      border: "border-red-200",
    },
    locked: {
      icon: Lock,
      color: "text-gray-400",
      bg: "bg-gray-50",
      border: "border-gray-200",
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
