"use client"

/**
 * Phase 7: Permission-Based Rendering (ADR-FE-002)
 *
 * Sticky bar render theo BE `can()` flags, KHÔNG đoán theo profile.status.
 *
 * Commit 2 — Decision Surface refactor:
 * Approve/Reject/Submit/Resubmit ĐÃ chuyển sang [FinalizeTab](./tabs/FinalizeTab.tsx)
 * (Step 8 decision panel) cùng bypass_warning guard. Sticky bar còn lại
 * chỉ navigation + non-decision workflow actions (publish_result,
 * request_revision, claim, enroll, send_confirmation, ...).
 */

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Loader2, Save, GraduationCap, ClipboardCheck, XCircle, Trash, ArrowRight, ArrowLeft } from "lucide-react"
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
import { usePermissions } from "@/hooks/usePermissions"
import { getStatusConfig } from "@/lib/status-config"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { SendConfirmationButton } from "./SendConfirmationButton"
import { SendMagicLinkButton } from "./SendMagicLinkButton"
import { MinorCorrectionDialog } from "./MinorCorrectionDialog"

interface AdmissionActionsProps {
  profile: AdmissionProfileResponse
  currentStep: number
  onStepChange: (step: number) => void
  isSaving: boolean
  isEnrolling: boolean
  onSave: () => void
  onEnroll: () => void
  onCheckCondition?: () => void
  // Phase 3 multi-NV: 1-click publish-result (bỏ start-review YAGNI 2026-05-15)
  onPublishResult?: () => void
  isPublishingResult?: boolean
  // E2E #10 — Request revision (manager → officer fix flow)
  onRequestRevision?: () => void
  isRequestingRevision?: boolean
  // Claim/unclaim actions
  onClaim?: () => void
  onUnclaim?: () => void
  isClaiming?: boolean
  isUnclaiming?: boolean
  // Delete action
  onDelete?: () => void
  isDeleting?: boolean
}

export function AdmissionActions({
  profile,
  currentStep,
  onStepChange,
  isSaving,
  isEnrolling,
  onSave,
  onEnroll,
  onCheckCondition,
  onPublishResult,
  isPublishingResult = false,
  onRequestRevision,
  isRequestingRevision = false,
  onClaim,
  onUnclaim,
  isClaiming = false,
  isUnclaiming = false,
  onDelete,
  isDeleting = false,
}: AdmissionActionsProps) {
  const { can } = usePermissions(profile)
  const statusConfig = getStatusConfig(profile.status)

  return (
    <div className="fixed bottom-0 left-0 right-0 border-t bg-background z-40 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.1)]">
      {/* Mobile (<640px): allow horizontal scroll inside bar so wide
          action sets (e.g. step 7 with 5 buttons) stay reachable without
          forcing the user to scroll the whole page. Wave 6 S-BUG-1 fix
          (action bar 549px overflow at 375px viewport). */}
      <div className="container max-w-7xl mx-auto h-16 px-3 sm:px-6 flex items-center justify-between gap-2 overflow-x-auto">
        {/* Status Badge */}
        <div className="flex items-center gap-4 flex-shrink-0">
          <span className="text-sm font-medium text-muted-foreground hidden sm:inline-block">
            Trạng thái:
          </span>
          <StatusBadge config={statusConfig} />
        </div>

        {/* Action Buttons - Phase 2: Context-Based.
            flex-shrink-0 prevents buttons collapsing into ellipsis;
            scroll lives on the outer container. */}
        <div className="flex items-center gap-2 sm:gap-3 flex-shrink-0">
          {/* DELETE - Always available if can('delete') */}
          {can('delete') && onDelete && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="ghost" size="sm" disabled={isDeleting} aria-label="Xóa hồ sơ">
                  {isDeleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash className="w-4 h-4" />}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Bạn có chắc chắn muốn xóa hồ sơ này?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Hành động này không thể hoàn tác. Hồ sơ tuyển sinh sẽ bị xóa vĩnh viễn khỏi hệ thống.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Hủy</AlertDialogCancel>
                  <AlertDialogAction onClick={onDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
                    Xóa hồ sơ
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}

          {/* Back Button - available for all steps after the first (step 8
              cũng cần Quay lại để officer/manager review xong có thể sửa). */}
          {currentStep > 1 && (
            <Button variant="outline" onClick={() => onStepChange(currentStep - 1)}>
              <ArrowLeft className="w-4 h-4 mr-2" />
              Quay lại
            </Button>
          )}

          {/* Save Changes - only when profile is editable. */}
          {currentStep < 8 && can('save') && (
            <Button variant="outline" onClick={onSave} disabled={isSaving}>
              {isSaving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
              Lưu thay đổi
            </Button>
          )}

          {/* Next Step Button - steps 1-7, advances to next. */}
          {currentStep < 8 && (
            <Button onClick={() => onStepChange(currentStep + 1)}>
              Tiếp tục
              <ArrowRight className="w-4 h-4 ml-2" />
            </Button>
          )}

          {/* Kiểm tra toàn bộ — step 8 only (navigate to first error step).
              Submit/Approve/Reject/Resubmit ĐÃ chuyển sang FinalizeTab
              decision panel (Commit 2). */}
          {currentStep === 8 && onCheckCondition && (
            <Button variant="outline" onClick={onCheckCondition}>
              <ClipboardCheck className="w-4 h-4 mr-2" />
              Kiểm tra toàn bộ
            </Button>
          )}

          {/* Phase 3 multi-NV: Publish Result (T6) — Thin Client compliance
              gate via can('publish_result') BE flag. Permission tự refine
              theo profile.uses_choice_engine + status IN (submitted,
              reviewing) + role manager/admin (xem
              admission_service._compute_frontend_fields). 1-click flow:
              BE auto-transition submitted→reviewing internal nếu cần →
              engine cascade per NV → admitted/rejected. KHÔNG REVERSIBLE
              (chỉ admin rollback qua T17 = về draft, mất mọi decision). */}
          {can('publish_result') && onPublishResult && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  disabled={isPublishingResult}
                  className="bg-success-600 hover:bg-success-700"
                >
                  {isPublishingResult ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <GraduationCap className="w-4 h-4 mr-2" />}
                  Công bố kết quả
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Công bố kết quả xét tuyển?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Hệ thống sẽ chạy <strong>engine xét tuần tự các nguyện vọng</strong>
                    {" "}theo thứ tự ưu tiên. Mỗi NV sẽ có quyết định riêng:
                    {" "}<strong>Đậu</strong> / <strong>Trượt</strong> / <strong>Bị bỏ qua</strong>
                    {" "}/ <strong>Dự bị</strong>. Hồ sơ sẽ chuyển sang trạng thái
                    {" "}<strong>Đã công bố</strong> rồi <strong>Trúng tuyển</strong>
                    {" "}hoặc <strong>Bị từ chối</strong>. Hành động không thể
                    hoàn tác (chỉ admin có thể rollback về Nháp).
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Hủy</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={(e) => {
                      // E2E #3 fix 2026-05-15 — defensive wrapper. Symptom:
                      // Radix AlertDialogAction onClick sometimes did not
                      // invoke handler in browser session. preventDefault
                      // ensures dialog close handler doesn't swallow event;
                      // explicit invoke guarantees mutate fires. Pattern
                      // mirrored on request-revision below.
                      e.preventDefault()
                      onPublishResult?.()
                    }}
                    className="bg-success-600 hover:bg-success-700"
                  >
                    Công bố kết quả
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}

          {/* E2E #10 — Request Revision (Yêu cầu sửa) for manager/admin.
              Mirrors claim/unclaim AlertDialog pattern. Permission flag
              `request_revision` already in _compute_frontend_fields:1443. */}
          {can('request_revision') && onRequestRevision && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" disabled={isRequestingRevision}>
                  {isRequestingRevision ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <ClipboardCheck className="w-4 h-4 mr-2" />
                  )}
                  Yêu cầu sửa
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Yêu cầu sửa hồ sơ?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Hồ sơ sẽ chuyển sang trạng thái <strong>Cần sửa</strong>.
                    Officer phụ trách sẽ nhận thông báo và có thể chỉnh sửa
                    rồi nộp lại.
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
          )}

          {/* Claim/Unclaim Actions */}
          {can('claim') && onClaim && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" disabled={isClaiming}>
                  {isClaiming ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <ClipboardCheck className="w-4 h-4 mr-2" />}
                  Nhận duyệt
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Nhận duyệt hồ sơ?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Bạn sẽ được gán là người duyệt hồ sơ này. Bạn có thể bỏ nhận bất cứ lúc nào.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Hủy</AlertDialogCancel>
                  <AlertDialogAction onClick={onClaim}>
                    Nhận duyệt
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}

          {can('unclaim') && onUnclaim && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" disabled={isUnclaiming}>
                  {isUnclaiming ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <XCircle className="w-4 h-4 mr-2" />}
                  Bỏ nhận
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Bỏ nhận duyệt?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Bạn sẽ không còn là người duyệt hồ sơ này. Manager khác có thể nhận duyệt.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Hủy</AlertDialogCancel>
                  <AlertDialogAction onClick={onUnclaim}>
                    Bỏ nhận
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}

          {/* Send magic-link. Visibility is driven by the backend
              `send_confirmation` permission (see _compute_frontend_fields:
              status=='approved' && manager/admin). Previously gated on
              `can('enroll')`, which is never true on `approved` per backend
              contract — the button was unreachable on real approved profiles.
              See project_send_confirmation_ops_gaps. */}
          {can('send_confirmation') && (
            <SendConfirmationButton profileId={profile.id} />
          )}

          {/* W2-1 fix Wave 7 (2026-05-16) — Generate magic-link cho 3
              candidate self-service actions. BE-driven permission flags
              `send_submit_link` / `send_resubmit_link` / `send_withdraw_link`
              tự kiểm tra state + role (mirror service precheck), nên FE
              hiển thị button đúng lúc đúng action. Mỗi button tự handle
              dialog + copy URL pattern (reuse SendConfirmationButton UX). */}
          {can('send_submit_link') && (
            <SendMagicLinkButton profileId={profile.id} action="submit" />
          )}
          {can('send_resubmit_link') && (
            <SendMagicLinkButton profileId={profile.id} action="resubmit" />
          )}
          {can('send_withdraw_link') && (
            <SendMagicLinkButton profileId={profile.id} action="withdraw" />
          )}

          {/* Post-approval minor correction. External `can()` gate
              mirrors SendConfirmationButton's pattern — caller decides
              visibility so the dialog component (and its
              useMinorCorrection mutation hook) never mounts when the
              backend hasn't authorized this profile. Without the gate,
              tests without a QueryClientProvider crash on hook
              instantiation; with the gate, only profiles whose backend
              flag is true ever invoke the hook. The dialog also
              double-checks `minor_correction_fields` length internally
              so a flag=true / fields=[] state stays renderable but
              empty (matching the contract documented in
              `_resolve_minor_correction_state`). */}
          {can('minor_correction') && (
            <MinorCorrectionDialog profile={profile} />
          )}

          {/* Enroll - can('enroll') when status ∈ {approved, confirmed, overridden}.
              Label is "Ghi danh" (not "Xác nhận nhập học") so officers don't
              confuse it with the applicant-facing "xác nhận" magic-link step. */}
          {can('enroll') && (
            <Button onClick={onEnroll} disabled={isEnrolling} className="bg-info-600 hover:bg-info-700">
              {isEnrolling ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <GraduationCap className="w-4 h-4 mr-2" />}
              Ghi danh
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * StatusBadge - Uses status-config for consistent styling
 */
interface StatusBadgeProps {
  config: ReturnType<typeof getStatusConfig>
}

function StatusBadge({ config }: StatusBadgeProps) {
  return <Badge className={config.badgeColor}>{config.label}</Badge>
}
