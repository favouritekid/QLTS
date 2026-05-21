"use client"

import { useState } from "react"
import { AlertCircle, ChevronDown, ChevronUp } from "lucide-react"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface GroupedValidationErrors {
  personal_info?: { category: string; errors: string[]; count: number }
  documents?: { category: string; errors: string[]; count: number }
  scores?: { category: string; errors: string[]; count: number }
}

interface IssueSummaryProps {
  profile: AdmissionProfileResponse | null
  validationErrors: string[]
  groupedValidationErrors?: GroupedValidationErrors | null
  defaultOpen?: boolean
}

export function IssueSummary({
  profile: _profile,
  validationErrors,
  groupedValidationErrors,
  defaultOpen = false,
}: IssueSummaryProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen)

  if (validationErrors.length === 0) return null

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen} className="px-1">
      <CollapsibleTrigger className="flex items-center justify-between w-full px-3 py-2 rounded-lg bg-error-50 border border-error-200 hover:bg-error-100 transition-colors">
        <div className="flex items-center gap-2 text-sm font-medium text-error-700">
          <AlertCircle className="w-4 h-4" />
          <span>Vấn đề cần sửa ({validationErrors.length})</span>
        </div>
        {isOpen ? (
          <ChevronUp className="w-4 h-4 text-error-600" />
        ) : (
          <ChevronDown className="w-4 h-4 text-error-600" />
        )}
      </CollapsibleTrigger>

      <CollapsibleContent className="mt-2 px-3 py-2 bg-card border border-error-100 dark:border-error-900 rounded-lg max-h-[300px] overflow-y-auto">
        {groupedValidationErrors ? (
          <div className="space-y-3">
            {groupedValidationErrors.personal_info && groupedValidationErrors.personal_info.count > 0 && (
              <IssueGroup
                title={groupedValidationErrors.personal_info.category}
                count={groupedValidationErrors.personal_info.count}
                errors={groupedValidationErrors.personal_info.errors}
              />
            )}
            {groupedValidationErrors.documents && groupedValidationErrors.documents.count > 0 && (
              <IssueGroup
                title={groupedValidationErrors.documents.category}
                count={groupedValidationErrors.documents.count}
                errors={groupedValidationErrors.documents.errors}
              />
            )}
            {groupedValidationErrors.scores && groupedValidationErrors.scores.count > 0 && (
              <IssueGroup
                title={groupedValidationErrors.scores.category}
                count={groupedValidationErrors.scores.count}
                errors={groupedValidationErrors.scores.errors}
              />
            )}
          </div>
        ) : (
          <ul className="text-xs text-muted-foreground space-y-1.5">
            {validationErrors.map((error, idx) => (
              <li key={idx} className="flex items-start gap-2">
                <span className="text-error-500 mt-0.5">•</span>
                <span className="leading-relaxed">{error}</span>
              </li>
            ))}
          </ul>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}

function IssueGroup({ title, count, errors }: { title: string; count: number; errors: string[] }) {
  return (
    <div>
      <h4 className="text-xs font-semibold text-foreground mb-1.5">
        {title} ({count})
      </h4>
      <ul className="text-xs text-muted-foreground space-y-1 ml-2">
        {errors.map((error, idx) => (
          <li key={idx} className="flex items-start gap-2">
            <span className="text-error-500 mt-0.5">•</span>
            <span className="leading-relaxed">{error}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
