/**
 * ActionItemsList — "VIỆC CẦN XỬ LÝ".
 *
 * Renders the readiness `actionItems` (built by useSubmissionReadiness). Each row
 * is a real <button> that deep-links to its step via `onNavigateToStep` (which
 * goes through the unsaved-changes guard in AdmissionDetailClient.handleStepChange).
 *
 * Only short summary lines per section — NOT the tab's granular FormMessages
 * (plan R3). Errors sort before warnings (handled by the hook). Step 7 never
 * appears here (plan B4). Renders nothing when there is no work to do.
 */

"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { AlertCircle, AlertTriangle, ArrowRight } from "lucide-react"
import type { ReadinessActionItem } from "./useSubmissionReadiness"

interface ActionItemsListProps {
  items: ReadinessActionItem[]
  onNavigateToStep: (step: number) => void
}

export function ActionItemsList({ items, onNavigateToStep }: ActionItemsListProps) {
  if (items.length === 0) return null

  return (
    <Card data-testid="action-items-list">
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center gap-2 text-error-700">
          <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
          Việc cần xử lý ({items.length})
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onNavigateToStep(item.step)}
            className="w-full flex items-center justify-between gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="flex items-start gap-2 min-w-0">
              {item.severity === "error" ? (
                <AlertCircle
                  className="h-4 w-4 mt-0.5 shrink-0 text-error-500"
                  aria-hidden="true"
                />
              ) : (
                <AlertTriangle
                  className="h-4 w-4 mt-0.5 shrink-0 text-warning-500"
                  aria-hidden="true"
                />
              )}
              <span className="min-w-0 space-y-1">
                <span className="block text-sm text-foreground break-words">
                  {item.message}
                </span>
                <span
                  className={
                    item.canDeferAsDocumentDebt
                      ? "block text-xs font-medium text-warning-700"
                      : item.severity === "error"
                        ? "block text-xs font-medium text-error-700"
                        : "block text-xs font-medium text-warning-700"
                  }
                >
                  {item.canDeferAsDocumentDebt
                    ? "Có thể nộp kèm nợ giấy tờ"
                    : item.severity === "error"
                      ? "Phải sửa trước khi nộp"
                      : "Cần rà soát"}
                </span>
              </span>
            </span>
            <span className="flex items-center gap-1 text-sm font-medium text-primary shrink-0">
              Sửa Bước {item.step}
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </span>
          </button>
        ))}
      </CardContent>
    </Card>
  )
}
