/**
 * DecisionActionsPanel — Step 8 decision CTA group (Hero `cta` slot, plan D2).
 *
 * The Hero is a DECISION surface, not a permission matrix. A permission flag only
 * says an action is allowed; the workflow STATE + readiness decide whether it
 * should appear here, and with what prominence (plan Hero redesign — supersedes
 * the rev-5 "render every permission equally" invariant):
 *
 *   - publish_result → "Công bố kết quả" (primary) + "Yêu cầu sửa" (secondary khi
 *       được phép — đường bounce hồ sơ multi-NV lỗi về officer). enroll → ONLY "Ghi danh".
 *   - submit   → primary "Nộp hồ sơ chính thức" (disabled + reason when !isEligible).
 *   - resubmit → primary "Nộp lại hồ sơ" (NOT gated by eligibility — invariant I2).
 *   - reviewer cluster:
 *       · approvable (eligible OR bypass) → primary Phê duyệt; secondary Yêu cầu
 *         sửa + Từ chối.
 *       · ineligible & no bypass → primary Yêu cầu sửa; secondary Từ chối; Phê
 *         duyệt tertiary (small, neutral, disabled) + reason. Approve is never a
 *         positive CTA when blocked.
 *
 * NO outer Card / sticky (the Hero owns the shell — plan rev 6 / R4). Approve tone
 * (success / warning / neutral-disabled) is composed by ApprovalDecisionButton.
 */

"use client"

import type { ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { Send, Loader2, XCircle, GraduationCap, ClipboardCheck } from "lucide-react"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { ApprovalDecisionButton } from "../../ApprovalDecisionButton"
import { SubmitWithDebtDialog } from "./SubmitWithDebtDialog"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import type { PrimaryAction } from "./useSubmissionReadiness"

type Prominence = "primary" | "secondary" | "tertiary"

const PRIMARY_CLASS = "w-full sm:w-auto min-w-[200px]"
const SECONDARY_CLASS = "w-full sm:w-auto"

export interface DecisionActionsPanelProps {
  profile: AdmissionProfileResponse
  isEligible: boolean
  /** The Hero's primary action — picks which cluster/prominence layout to render. */
  primaryAction: PrimaryAction
  /** Layout className from the Hero CTA slot (no shell/sticky of its own). */
  className?: string

  onSubmit: () => void
  isSubmitting: boolean
  canSubmit: boolean

  /**
   * Fast-track nợ giấy tờ — confirm a document debt and submit
   * (TUITION_PREPAY_FASTTRACK_PLAN.md §4). Surfaced as a distinct
   * "Nộp kèm nợ giấy tờ" CTA, gated by `canSubmitWithDocumentDebt`
   * (= `profile.can_submit_with_document_debt`, an API flag — NOT role).
   */
  onSubmitWithDebt?: (payload: {
    acknowledge_missing_docs: true
    document_debt_reason: string
  }) => void
  canSubmitWithDocumentDebt?: boolean

  onResubmit?: () => void
  isResubmitting?: boolean
  canResubmit: boolean

  onApprove?: () => void
  isApproving?: boolean
  canApprove: boolean

  onReject?: () => void
  isRejecting?: boolean
  canReject: boolean

  onRequestRevision?: () => void
  isRequestingRevision?: boolean
  canRequestRevision: boolean

  onPublishResult?: () => void
  isPublishingResult?: boolean
  canPublishResult: boolean

  onEnroll?: () => void
  isEnrolling?: boolean
  canEnroll: boolean
}

function Shell({ children, reason, className }: { children: ReactNode; reason?: ReactNode; className?: string }) {
  return (
    <div className={cn("w-full space-y-2", className)}>
      <div className="flex flex-col sm:flex-row flex-wrap items-center justify-center gap-3">
        {children}
      </div>
      {reason}
    </div>
  )
}

function Reason({ children }: { children: ReactNode }) {
  return <p className="text-center text-xs text-warning-700">{children}</p>
}

export function DecisionActionsPanel({
  profile,
  isEligible,
  primaryAction,
  className,
  onSubmit,
  isSubmitting,
  canSubmit,
  onSubmitWithDebt,
  canSubmitWithDocumentDebt = false,
  onResubmit,
  isResubmitting = false,
  canResubmit,
  onApprove,
  isApproving = false,
  canApprove,
  onReject,
  isRejecting = false,
  canReject,
  onRequestRevision,
  isRequestingRevision = false,
  canRequestRevision,
  onPublishResult,
  isPublishingResult = false,
  canPublishResult,
  onEnroll,
  isEnrolling = false,
  canEnroll,
}: DecisionActionsPanelProps) {
  // Draft còn thiếu dữ liệu bắt buộc (quá trình học tập / gia đình) — BE chặn
  // submit nhưng không nằm trong eligibility, nên gate nút + hiện lý do rõ ràng
  // ở đây (bypass-aware: cờ đã tính allow_unverified_submission ở backend).
  const submitBlockedByData = profile.submit_blocked_by_data ?? false
  const requiredDataErrors = profile.grouped_validation_errors?.required_data?.errors ?? []

  // ----- per-action renderers (closures) -------------------------------------
  const submitButton = () => (
    <Button
      key="submit"
      size="lg"
      disabled={!isEligible || submitBlockedByData || isSubmitting}
      onClick={onSubmit}
      className={PRIMARY_CLASS}
    >
      {isSubmitting ? (
        <>
          <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
          Đang xử lý…
        </>
      ) : (
        <>
          <Send className="w-4 h-4 mr-2" aria-hidden="true" />
          Nộp hồ sơ chính thức
        </>
      )}
    </Button>
  )

  const resubmitButton = () => (
    <AlertDialog key="resubmit">
      <AlertDialogTrigger asChild>
        <Button size="lg" disabled={isResubmitting} className={PRIMARY_CLASS}>
          {isResubmitting ? (
            <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
          ) : (
            <Send className="w-4 h-4 mr-2" aria-hidden="true" />
          )}
          Nộp lại hồ sơ
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Nộp lại hồ sơ?</AlertDialogTitle>
          <AlertDialogDescription>
            Hồ sơ đã bị từ chối trước đó. Sau khi nộp lại, hồ sơ sẽ được chuyển sang trạng
            thái chờ duyệt.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Hủy</AlertDialogCancel>
          <AlertDialogAction onClick={onResubmit}>Nộp lại</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )

  const publishButton = () => (
    <AlertDialog key="publish">
      <AlertDialogTrigger asChild>
        <Button
          size="lg"
          disabled={isPublishingResult}
          className={cn(PRIMARY_CLASS, "bg-purple-600 hover:bg-purple-700")}
        >
          {isPublishingResult ? (
            <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
          ) : (
            <GraduationCap className="w-4 h-4 mr-2" aria-hidden="true" />
          )}
          Công bố kết quả
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Công bố kết quả xét tuyển?</AlertDialogTitle>
          <AlertDialogDescription>
            Hệ thống sẽ chạy <strong>engine xét tuần tự các nguyện vọng</strong> theo thứ tự
            ưu tiên. Mỗi NV sẽ có quyết định riêng: <strong>Đậu</strong> / <strong>Trượt</strong>{" "}
            / <strong>Bị bỏ qua</strong> / <strong>Dự bị</strong>. Hành động không thể hoàn tác
            (chỉ admin có thể rollback về Nháp).
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Hủy</AlertDialogCancel>
          <AlertDialogAction
            onClick={(e) => {
              e.preventDefault()
              onPublishResult?.()
            }}
            className="bg-purple-600 hover:bg-purple-700"
          >
            Công bố kết quả
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )

  const enrollButton = () => (
    <Button
      key="enroll"
      size="lg"
      onClick={onEnroll}
      disabled={isEnrolling}
      className={cn(PRIMARY_CLASS, "bg-info-600 hover:bg-info-700")}
    >
      {isEnrolling ? (
        <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
      ) : (
        <GraduationCap className="w-4 h-4 mr-2" aria-hidden="true" />
      )}
      Ghi danh
    </Button>
  )

  const approveButton = (prominence: Prominence) => (
    <ApprovalDecisionButton
      key="approve"
      profile={profile}
      onApprove={onApprove!}
      isApproving={isApproving}
      isEligible={isEligible}
      disabled={(!isEligible && !profile.bypass_warning) || isRejecting}
      size={prominence === "primary" ? "lg" : "sm"}
      className={prominence === "primary" ? PRIMARY_CLASS : SECONDARY_CLASS}
    />
  )

  const requestRevisionButton = (prominence: Prominence) => (
    <AlertDialog key="revision">
      <AlertDialogTrigger asChild>
        <Button
          size={prominence === "primary" ? "lg" : "default"}
          variant={prominence === "primary" ? "default" : "outline"}
          disabled={isRequestingRevision || isApproving || isRejecting}
          className={prominence === "primary" ? PRIMARY_CLASS : SECONDARY_CLASS}
        >
          {isRequestingRevision ? (
            <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
          ) : (
            <ClipboardCheck className="w-4 h-4 mr-2" aria-hidden="true" />
          )}
          Yêu cầu sửa
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Yêu cầu sửa hồ sơ?</AlertDialogTitle>
          <AlertDialogDescription>
            Hồ sơ sẽ chuyển sang trạng thái <strong>Cần sửa</strong>. Officer phụ trách sẽ
            nhận thông báo và có thể chỉnh sửa rồi nộp lại.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Hủy</AlertDialogCancel>
          <AlertDialogAction
            onClick={(e) => {
              e.preventDefault()
              onRequestRevision?.()
            }}
          >
            Yêu cầu sửa
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )

  const rejectButton = (prominence: Prominence) => (
    <Button
      key="reject"
      size={prominence === "primary" ? "lg" : "default"}
      variant="outline"
      disabled={isRejecting || isApproving}
      onClick={onReject}
      className={cn(
        "border-error-300 text-error-600 hover:bg-error-50 hover:text-error-700",
        prominence === "primary" ? PRIMARY_CLASS : SECONDARY_CLASS,
      )}
    >
      {isRejecting ? (
        <>
          <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
          Đang xử lý…
        </>
      ) : (
        <>
          <XCircle className="w-4 h-4 mr-2" aria-hidden="true" />
          Từ chối hồ sơ
        </>
      )}
    </Button>
  )

  // ----- single-action states (only the state's own action) -------------------
  if (primaryAction === "publish_result" && canPublishResult && onPublishResult) {
    // Công bố là primary, NHƯNG reviewer vẫn cần đường trả hồ sơ multi-NV lỗi về
    // officer TRƯỚC khi chạy engine cascade không hoàn tác — surface "Yêu cầu sửa"
    // làm secondary khi được phép (state submitted có quyền này; reviewing thì
    // KHÔNG → vẫn publish-only). "Từ chối" giữ ẩn để bề mặt publish không biến
    // thành ma trận permission.
    return (
      <Shell className={className}>
        {publishButton()}
        {canRequestRevision && onRequestRevision && requestRevisionButton("secondary")}
      </Shell>
    )
  }
  if (primaryAction === "enroll" && canEnroll && onEnroll) {
    return <Shell className={className}>{enrollButton()}</Shell>
  }
  if (primaryAction === "submit" && canSubmit) {
    // Fast-track: when the profile is eligible on every axis EXCEPT missing
    // mandatory docs, the backend grants `can_submit_with_document_debt`. Offer
    // "Nộp kèm nợ giấy tờ" alongside the (disabled) normal submit. The reason
    // line then points at the debt option instead of a dead "chưa đủ điều kiện".
    // When required data (family/academic) is still missing, submit is blocked
    // regardless of docs — hide the doc-debt CTA (it would also be rejected) and
    // point the user at the missing data instead.
    const showDebt = canSubmitWithDocumentDebt && !!onSubmitWithDebt && !submitBlockedByData
    const reasonNode = showDebt ? (
      <Reason>Còn thiếu giấy tờ — có thể nộp kèm nợ giấy tờ.</Reason>
    ) : submitBlockedByData ? (
      <Reason>Còn thiếu: {requiredDataErrors.join(" · ")}</Reason>
    ) : !isEligible ? (
      <Reason>Chưa đủ điều kiện để nộp.</Reason>
    ) : undefined
    return (
      <Shell className={className} reason={reasonNode}>
        {submitButton()}
        {showDebt && (
          <SubmitWithDebtDialog
            profile={profile}
            onConfirm={onSubmitWithDebt!}
            isSubmitting={isSubmitting}
          />
        )}
      </Shell>
    )
  }
  if (primaryAction === "resubmit" && canResubmit && onResubmit) {
    return <Shell className={className}>{resubmitButton()}</Shell>
  }

  // ----- reviewer cluster (approve / request_revision / reject) ----------------
  const approvable = isEligible || !!profile.bypass_warning
  const cluster: ReactNode[] = []
  let reason: ReactNode = undefined

  if (canApprove && onApprove) {
    if (approvable) {
      cluster.push(approveButton("primary"))
      if (canRequestRevision && onRequestRevision) cluster.push(requestRevisionButton("secondary"))
      if (canReject && onReject) cluster.push(rejectButton("secondary"))
    } else {
      // ineligible & no bypass — de-emphasize approve (not a positive CTA).
      let primaryTaken = false
      if (canRequestRevision && onRequestRevision) {
        cluster.push(requestRevisionButton("primary"))
        primaryTaken = true
      }
      if (canReject && onReject) cluster.push(rejectButton(primaryTaken ? "secondary" : "primary"))
      cluster.push(approveButton("tertiary"))
      reason = <Reason>Chưa đủ điều kiện để phê duyệt.</Reason>
    }
  } else {
    // No approve permission — revision / reject only.
    let primaryTaken = false
    if (canRequestRevision && onRequestRevision) {
      cluster.push(requestRevisionButton("primary"))
      primaryTaken = true
    }
    if (canReject && onReject) cluster.push(rejectButton(primaryTaken ? "secondary" : "primary"))
  }

  if (cluster.length === 0) return null

  return (
    <Shell className={className} reason={reason}>
      {cluster}
    </Shell>
  )
}
