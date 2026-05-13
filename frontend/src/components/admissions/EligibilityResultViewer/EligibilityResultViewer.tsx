"use client"

/**
 * Phase 3 PR-3D-B FE Wave B Day 9 — EligibilityResultViewer.
 *
 * Renders `choice.eligibility_check_result` JSONB (engine output) as
 * candidate-friendly pretty cards instead of raw JSON. Each reason code
 * gets a Vietnamese label via `REASON_CODE_LABELS` in `lib/admission/eligibility.ts`.
 *
 * UI sections:
 *   1. Decision header (DecisionBadge + path name)
 *   2. Reason cards (1 per reason_code with XCircle icon + label)
 *   3. Score summary (final_score, passed, selected_subjects) if score present
 *   4. Collapsible raw JSON for power-users / debugging
 *   5. Empty state when result === null (not yet evaluated)
 *
 * Per Plan v0.7 design v0.5: candidate-facing → friendly labels, NOT raw codes.
 * Officer/manager can expand collapsible to see raw payload for support.
 */
import { CheckCircle2, ChevronDown, ChevronUp, XCircle } from "lucide-react"
import { useState } from "react"
import { DecisionBadge } from "@/components/admissions/DecisionBadge"
import type { ChoiceDecision } from "@/components/admissions/DecisionBadge/DecisionBadge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  getReasonLabel,
  type EligibilityCheckResult,
} from "@/lib/admission/eligibility"

export interface EligibilityResultViewerProps {
  result: EligibilityCheckResult | null | undefined
  /** Optional context — display next to decision badge for clarity. */
  pathName?: string
  /** Optional display order, e.g. "NV2" prefix. */
  displayOrder?: number
}

export function EligibilityResultViewer({
  result,
  pathName,
  displayOrder,
}: EligibilityResultViewerProps) {
  const [rawOpen, setRawOpen] = useState(false)

  if (!result) {
    return (
      <Card data-testid="eligibility-empty">
        <CardContent className="py-6 text-center text-sm text-muted-foreground">
          Chưa có kết quả xét tuyển. Quản trị viên sẽ chạy engine khi đến kỳ
          xét.
        </CardContent>
      </Card>
    )
  }

  const hasReasons = result.reason_codes && result.reason_codes.length > 0
  const hasScore = result.score !== null && result.score !== undefined
  const passed = result.decision === "admitted"

  return (
    <Card data-testid="eligibility-viewer">
      <CardHeader className="space-y-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">
            {displayOrder !== undefined ? `NV${displayOrder} — ` : ""}
            Kết quả xét tuyển
          </CardTitle>
          <DecisionBadge
            decision={result.decision as ChoiceDecision}
            size="sm"
          />
        </div>
        {pathName && (
          <p className="text-sm text-muted-foreground">{pathName}</p>
        )}
      </CardHeader>

      <CardContent className="space-y-4">
        {hasReasons && (
          <section
            aria-labelledby="eligibility-reasons-heading"
            className="space-y-2"
          >
            <h4
              id="eligibility-reasons-heading"
              className="text-sm font-medium"
            >
              {passed ? "Ghi chú" : "Lý do chưa đạt"}
            </h4>
            <ul className="space-y-1" data-testid="eligibility-reason-list">
              {result.reason_codes.map((code) => {
                const Icon = passed ? CheckCircle2 : XCircle
                const iconClass = passed
                  ? "text-success-700"
                  : "text-destructive"
                return (
                  <li
                    key={code}
                    className="flex items-start gap-2 text-sm"
                    data-testid={`eligibility-reason-${code}`}
                  >
                    <Icon
                      className={`mt-0.5 h-4 w-4 shrink-0 ${iconClass}`}
                      aria-hidden="true"
                    />
                    <span>{getReasonLabel(code)}</span>
                  </li>
                )
              })}
            </ul>
          </section>
        )}

        {hasScore && result.score && (
          <section
            aria-labelledby="eligibility-score-heading"
            className="space-y-2 rounded-md border bg-muted/30 p-3"
            data-testid="eligibility-score-card"
          >
            <h4
              id="eligibility-score-heading"
              className="text-sm font-medium"
            >
              Điểm tổng kết
            </h4>
            <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-sm">
              <dt className="text-muted-foreground">Điểm cuối:</dt>
              <dd className="font-semibold">
                {result.score.final_score !== null
                  ? result.score.final_score
                  : "—"}
              </dd>
              <dt className="text-muted-foreground">Đạt ngưỡng:</dt>
              <dd className={result.score.passed ? "text-success-700" : "text-destructive"}>
                {result.score.passed ? "Có" : "Không"}
              </dd>
              {result.score.selected_subjects.length > 0 && (
                <>
                  <dt className="text-muted-foreground">Môn tham gia tính:</dt>
                  <dd>{result.score.selected_subjects.join(", ")}</dd>
                </>
              )}
            </dl>
          </section>
        )}

        {!hasReasons && !hasScore && (
          <p
            className="text-sm text-muted-foreground"
            data-testid="eligibility-no-details"
          >
            Không có thêm chi tiết cho kết quả này.
          </p>
        )}

        <Collapsible open={rawOpen} onOpenChange={setRawOpen}>
          <CollapsibleTrigger
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            data-testid="eligibility-raw-toggle"
            aria-expanded={rawOpen}
          >
            {rawOpen ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
            {rawOpen ? "Ẩn dữ liệu thô" : "Xem dữ liệu thô (JSON)"}
          </CollapsibleTrigger>
          <CollapsibleContent>
            <pre
              className="mt-2 max-h-64 overflow-auto rounded-md bg-muted p-2 text-xs"
              data-testid="eligibility-raw-json"
            >
              {JSON.stringify(result, null, 2)}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  )
}
