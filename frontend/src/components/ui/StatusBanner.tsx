"use client"

/**
 * StatusBanner Component
 * 
 * Architecture Standard: Status-Driven UI (ADR-FE-003)
 * 
 * A reusable banner component that renders status-based messages
 * using the centralized status-config.
 * 
 * Usage:
 * <StatusBanner status={profile.status} module="admission" />
 */

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { 
  CheckCircle2, 
  Clock, 
  AlertCircle, 
  XCircle, 
  Info,
  Loader2
} from "lucide-react"
import { getStatusConfig } from "@/lib/status-config"
import { cn } from "@/lib/utils"

interface StatusBannerProps {
  /** Current status value from backend */
  status: string
  /** Module name for config lookup (default: "admission") */
  module?: "admission" | "lead"
  /** Optional custom message override */
  customMessage?: string
  /** Optional className for styling */
  className?: string
  /** Optional: Show loading state */
  isLoading?: boolean
}

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  success: CheckCircle2,
  info: Clock,
  warning: AlertCircle,
  error: XCircle,
}

export function StatusBanner({ 
  status, 
  module = "admission",
  customMessage,
  className,
  isLoading = false
}: StatusBannerProps) {
  const config = getStatusConfig(status, module)
  
  // Don't render if banner should not be shown
  if (!config.showBanner) return null
  
  const Icon = ICON_MAP[config.bannerType ?? 'info'] ?? Info
  const message = customMessage ?? config.bannerMessage
  
  if (!message) return null
  
  return (
    <Alert 
      variant={config.bannerType === 'error' ? 'destructive' : 'default'}
      className={cn(
        "mb-6",
        config.bannerType === 'success' && "border-green-200 bg-green-50 text-green-800",
        config.bannerType === 'info' && "border-blue-200 bg-blue-50 text-blue-800",
        config.bannerType === 'warning' && "border-yellow-200 bg-yellow-50 text-yellow-800",
        className
      )}
    >
      {isLoading ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <Icon className="h-4 w-4" />
      )}
      <AlertTitle>{config.label}</AlertTitle>
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  )
}

/**
 * AdmissionPendingBanner - Specialized for pending approval state
 * Shows when profile.status === 'submitted' or 'resubmitted'
 */
interface AdmissionPendingBannerProps {
  status: string
  className?: string
}

export function AdmissionPendingBanner({ status, className }: AdmissionPendingBannerProps) {
  const isPending = status === 'submitted' || status === 'resubmitted'
  
  if (!isPending) return null
  
  return (
    <Alert 
      className={cn(
        "mb-6 border-yellow-200 bg-yellow-50",
        className
      )}
    >
      <Clock className="h-4 w-4 text-yellow-600" />
      <AlertTitle className="text-yellow-800">Đang chờ duyệt</AlertTitle>
      <AlertDescription className="text-yellow-700">
        Hồ sơ của bạn đã được nộp và đang chờ phê duyệt từ bộ phận tuyển sinh.
        Bạn sẽ nhận được thông báo khi có kết quả.
      </AlertDescription>
    </Alert>
  )
}

/**
 * ValidationErrorsBanner - Shows backend validation errors
 */
interface ValidationErrorsBannerProps {
  errors: string[]
  className?: string
}

export function ValidationErrorsBanner({ errors, className }: ValidationErrorsBannerProps) {
  if (!errors || errors.length === 0) return null
  
  return (
    <Alert 
      variant="destructive"
      className={cn("mb-6", className)}
    >
      <AlertCircle className="h-4 w-4" />
      <AlertTitle>Hồ sơ chưa đủ điều kiện</AlertTitle>
      <AlertDescription>
        <ul className="list-disc pl-5 mt-2 space-y-1">
          {errors.map((err, idx) => (
            <li key={idx}>{err}</li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  )
}
