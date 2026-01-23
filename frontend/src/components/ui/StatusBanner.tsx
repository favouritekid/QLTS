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

import { useMemo, useState } from "react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  CheckCircle2,
  Clock,
  AlertCircle,
  XCircle,
  Info,
  Loader2,
  ChevronDown,
  ChevronUp,
  GraduationCap,
  FileText,
  UserCircle,
  AlertTriangle
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
 * ValidationErrorsBanner - Shows backend validation errors with grouped display
 *
 * Features:
 * - Smart grouping by category (GPA, Documents, Personal, Family, Academic)
 * - Collapsible sections for clean UX
 * - Auto-refresh when errors prop changes
 * - Visual hierarchy with icons and colors
 */
interface ValidationErrorsBannerProps {
  errors: string[]
  className?: string
}

interface ErrorSectionProps {
  id: string
  title: string
  icon: React.ComponentType<{ className?: string }>
  errors: string[]
  color?: "red" | "yellow" | "blue"
  expandedSections: Set<string>
  toggleSection: (section: string) => void
}

function ErrorSection({
  id,
  title,
  icon: Icon,
  errors: sectionErrors,
  color = "red",
  expandedSections,
  toggleSection
}: ErrorSectionProps) {
  if (sectionErrors.length === 0) return null

  const isExpanded = expandedSections.has(id)
  const colorClasses = {
    red: "text-red-700 bg-red-50 hover:bg-red-100",
    yellow: "text-yellow-700 bg-yellow-50 hover:bg-yellow-100",
    blue: "text-blue-700 bg-blue-50 hover:bg-blue-100"
  }

  return (
    <div className="border-l-4 border-red-400 pl-3 py-2">
      <button
        onClick={() => toggleSection(id)}
        className={cn(
          "flex items-center justify-between w-full text-sm font-medium transition-colors rounded px-2 py-1",
          colorClasses[color]
        )}
      >
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4" />
          <span>{title}</span>
          <span className="text-xs opacity-75">({sectionErrors.length})</span>
        </div>
        {isExpanded ? (
          <ChevronUp className="w-4 h-4" />
        ) : (
          <ChevronDown className="w-4 h-4" />
        )}
      </button>

      {isExpanded && (
        <ul className="list-disc pl-9 mt-2 space-y-1 text-sm">
          {sectionErrors.map((err, i) => (
            <li key={i} className="text-gray-700">{err}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function ValidationErrorsBanner({ errors, className }: ValidationErrorsBannerProps) {
  // Fix: Hooks must run unconditionally
  const safeErrors = useMemo(() => errors || [], [errors])

  // Smart grouping based on error content patterns
  const grouped = useMemo(() => {
    const result = {
      gpa: [] as string[],
      docs: [] as string[],
      personal: [] as string[],
      family: [] as string[],
      academic: [] as string[],
      other: [] as string[]
    }

    safeErrors.forEach(err => {
      const lower = err.toLowerCase()
      if (lower.includes("gpa") || lower.includes("điểm") || lower.includes("tổng điểm") || lower.includes("môn")) {
        result.gpa.push(err)
      } else if (lower.includes("tài liệu") || lower.includes("minh chứng")) {
        result.docs.push(err)
      } else if (lower.includes("cccd") || lower.includes("cmnd") || lower.includes("citizen")) {
        result.personal.push(err)
      } else if (lower.includes("gia đình") || lower.includes("family")) {
        result.family.push(err)
      } else if (lower.includes("học tập") || lower.includes("academic")) {
        result.academic.push(err)
      } else {
        result.other.push(err)
      }
    })

    return result
  }, [safeErrors])

  // Calculate total sections that have errors
  const sectionsWithErrors = [
    grouped.gpa.length > 0,
    grouped.docs.length > 0,
    grouped.personal.length > 0,
    grouped.family.length > 0,
    grouped.academic.length > 0,
    grouped.other.length > 0
  ].filter(Boolean).length

  // Collapsible state (auto-expand if <= 2 sections with errors)
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    // Initialize lazily to avoid recalculating on render
    () => new Set(sectionsWithErrors <= 2 ? ['gpa', 'docs', 'personal', 'family', 'academic', 'other'] : [])
  )

  const toggleSection = (section: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev)
      if (next.has(section)) next.delete(section)
      else next.add(section)
      return next
    })
  }

  // Conditional return moved AFTER hooks
  if (!errors || errors.length === 0) return null

  return (
    <Alert
      variant="destructive"
      className={cn("mb-6 border-red-300", className)}
    >
      <AlertCircle className="h-5 w-5" />
      <AlertTitle className="text-base font-semibold">
        Hồ sơ chưa đủ điều kiện - {errors.length} vấn đề cần hoàn thiện
      </AlertTitle>
      <AlertDescription>
        <div className="space-y-2 mt-3">
          {/* GPA/Score Section */}
          <ErrorSection
            id="gpa"
            title="Điểm số & Thành tích học tập"
            icon={GraduationCap}
            errors={grouped.gpa}
            color="red"
            expandedSections={expandedSections}
            toggleSection={toggleSection}
          />

          {/* Documents Section */}
          <ErrorSection
            id="docs"
            title="Tài liệu & Minh chứng"
            icon={FileText}
            errors={grouped.docs}
            color="yellow"
            expandedSections={expandedSections}
            toggleSection={toggleSection}
          />

          {/* Personal Info Section */}
          <ErrorSection
            id="personal"
            title="Thông tin cá nhân (CCCD/CMND)"
            icon={UserCircle}
            errors={grouped.personal}
            color="red"
            expandedSections={expandedSections}
            toggleSection={toggleSection}
          />

          {/* Family Info Section */}
          <ErrorSection
            id="family"
            title="Thông tin gia đình"
            icon={UserCircle}
            errors={grouped.family}
            color="yellow"
            expandedSections={expandedSections}
            toggleSection={toggleSection}
          />

          {/* Academic History Section */}
          <ErrorSection
            id="academic"
            title="Quá trình học tập"
            icon={GraduationCap}
            errors={grouped.academic}
            color="yellow"
            expandedSections={expandedSections}
            toggleSection={toggleSection}
          />

          {/* Other Errors */}
          {grouped.other.length > 0 && (
            <ErrorSection
              id="other"
              title="Vấn đề khác"
              icon={AlertTriangle}
              errors={grouped.other}
              color="red"
              expandedSections={expandedSections}
              toggleSection={toggleSection}
            />
          )}
        </div>

        {/* Helper text */}
        <p className="text-xs text-muted-foreground mt-3 pt-3 border-t">
          💡 Click vào từng mục để xem chi tiết. Hồ sơ sẽ tự động cập nhật sau khi bạn hoàn thiện.
        </p>
      </AlertDescription>
    </Alert>
  )
}
