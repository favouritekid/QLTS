"use client"

import type { ReactNode } from "react"
import Link from "next/link"
import { Loader2, RefreshCw } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  PRIORITY_CONFIG_HREF,
  PRIORITY_CONFIG_LABEL,
  RUN_CHECK_AGAIN,
  RUN_FAILED_HINT,
  RUN_LOCATION_MISMATCH,
  RUN_NO_NEW,
  RUN_OTHER_CEILING,
  RUN_OTHER_WAITING,
  RUN_SUBMITTING,
  RUN_UNCERTAIN_CHECKING,
  RUN_VIEW_RESULT,
  priorityMissingCodes,
  runDoneMessage,
  runFailedMessage,
  runOtherDone,
  runOwnCeiling,
  runRunningFor,
  runSubmitErrorMessage,
  runTrackingLabel,
} from "@/lib/review-sessions/messages"
import type { RunTrackPhase } from "@/lib/review-sessions/run-tracking"
import { reviewRunHref } from "@/lib/review-sessions/url"

import { ReviewErrorAlert } from "./ReviewErrorAlert"

function Info({ testId, children }: { testId: string; children: ReactNode }) {
  return (
    <Alert data-testid={testId}>
      <AlertDescription className="space-y-1">{children}</AlertDescription>
    </Alert>
  )
}

function RetryButton({ onRetry }: { onRetry: () => void }) {
  return (
    <Button variant="outline" size="sm" onClick={onRetry} data-testid="kiem-kiem-tra-lai">
      <RefreshCw className="mr-1 h-4 w-4" />
      {RUN_CHECK_AGAIN}
    </Button>
  )
}

/** `missing_codes` của 503 `PRIORITY_RATE_NOT_CONFIGURED` — chỉ nhận mảng chuỗi (thân lỗi là dữ liệu công khai, HĐ4 §5). */
function missingCodesOf(data: Record<string, unknown> | undefined): string[] {
  const v = data?.missing_codes
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []
}

/**
 * Băng trạng thái của "Kiểm hồ sơ" (M4 — thiết kế §3.5): vẽ ĐÚNG pha của `useReviewRunTracker`. Pha lỗi hỏi lại CHỈ hiện lỗi +
 * "Kiểm tra lại" — không vẽ trạng thái cũ (đính chính 2 §1). Không tự suy kết quả: chữ trạng thái là nhãn của `status` máy chủ.
 */
export function ReviewRunTrackerBand({
  sessionId,
  phase,
  onRetry,
}: {
  sessionId: number
  phase: RunTrackPhase
  onRetry: () => void
}) {
  switch (phase.kind) {
    case "idle":
      return null
    case "submitting":
      return (
        <Info testId="kiem-dang-gui">
          <p className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" /> {RUN_SUBMITTING}
          </p>
        </Info>
      )
    case "polling": {
      const { target } = phase
      if (target.mode === "check") {
        return (
          <Info testId="kiem-dang-kiem-tra">
            <p className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" /> {RUN_UNCERTAIN_CHECKING}
            </p>
          </Info>
        )
      }
      if (target.mode === "other") {
        return (
          <Info testId="kiem-cho-luot-khac">
            {target.serverNote !== null ? <p data-testid="kiem-cau-may-chu">{target.serverNote}</p> : null}
            <p>{RUN_OTHER_WAITING}</p>
            {target.runId !== null ? (
              <p data-testid="kiem-trang-thai-luot">{runTrackingLabel(target.runId, phase.status)}</p>
            ) : null}
          </Info>
        )
      }
      const minutes = runRunningFor(phase.elapsedMs)
      return (
        <Info testId="kiem-dang-theo-doi">
          <p className="flex items-center gap-2" data-testid="kiem-trang-thai-luot">
            <Loader2 className="h-4 w-4 animate-spin" />
            {target.runId !== null ? runTrackingLabel(target.runId, phase.status) : RUN_UNCERTAIN_CHECKING}
          </p>
          {minutes !== null ? <p data-testid="kiem-dang-chay-phut">{minutes}</p> : null}
        </Info>
      )
    }
    case "poll_error":
      return (
        <ReviewErrorAlert testId="kiem-loi-theo-doi" message={phase.message}>
          <RetryButton onRetry={onRetry} />
        </ReviewErrorAlert>
      )
    case "ceiling":
      return (
        <Info testId="kiem-het-tran">
          <p data-testid="kiem-het-tran-cau">
            {phase.target.mode === "mine" && phase.target.runId !== null
              ? runOwnCeiling(phase.target.runId, phase.elapsedMs)
              : RUN_OTHER_CEILING}
          </p>
          <RetryButton onRetry={onRetry} />
        </Info>
      )
    case "done":
      return (
        <Info testId="kiem-xong">
          <p>{runDoneMessage(phase.runId)}</p>
          <Link href={reviewRunHref(sessionId, phase.runId)} className="underline" data-testid="kiem-xem-ket-qua">
            {RUN_VIEW_RESULT}
          </Link>
        </Info>
      )
    case "failed":
      return (
        <ReviewErrorAlert testId="kiem-hong" message={runFailedMessage(phase.errorCode)}>
          <p>{RUN_FAILED_HINT}</p>
        </ReviewErrorAlert>
      )
    case "other_done":
      return (
        <Info testId="kiem-luot-khac-xong">
          <p>{runOtherDone(phase.runId, phase.status)}</p>
          <Link href={reviewRunHref(sessionId, phase.runId)} className="underline" data-testid="kiem-xem-ket-qua">
            {RUN_VIEW_RESULT}
          </Link>
        </Info>
      )
    case "no_new_run":
      return <Info testId="kiem-chua-co-luot-moi">{RUN_NO_NEW}</Info>
    case "submit_error": {
      const { error } = phase
      const missing = error.errorCode === "PRIORITY_RATE_NOT_CONFIGURED" ? missingCodesOf(error.data) : []
      return (
        <ReviewErrorAlert testId="kiem-loi" message={runSubmitErrorMessage(error)}>
          {missing.length ? <p data-testid="kiem-ma-thieu">{priorityMissingCodes(missing)}</p> : null}
          {error.errorCode === "PRIORITY_RATE_NOT_CONFIGURED" ? (
            <Link href={PRIORITY_CONFIG_HREF} className="underline" data-testid="kiem-lien-ket-uu-tien">
              {PRIORITY_CONFIG_LABEL}
            </Link>
          ) : null}
        </ReviewErrorAlert>
      )
    }
    case "contract_error":
      return <ReviewErrorAlert testId="kiem-loi" message={RUN_LOCATION_MISMATCH} />
    default:
      return null
  }
}
