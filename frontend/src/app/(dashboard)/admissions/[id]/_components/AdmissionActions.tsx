"use client"

/**
 * Sticky bar — Commit 7 button consolidation.
 *
 * Render TỐI THIỂU theo BE permission flags:
 *   - Navigation: Quay lại / Tiếp tục (step 1-7) / Save / Kiểm tra toàn bộ (step 8)
 *   - Outbound communication: 4 send_* buttons (mutex per state)
 *
 * KHÔNG còn:
 *   - Decision actions (Submit/Resubmit/Approve/Reject/RequestRevision/
 *     PublishResult/Enroll) → FinalizeTab Step 8 decision panel.
 *   - Workflow utilities (Claim/Unclaim/Delete/MinorCorrection) →
 *     ProfileActionMenu trong header (⋮).
 *
 * Sticky bar còn lại ~2-4 buttons cho mọi state.
 */

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Loader2, Save, ClipboardCheck, ArrowRight, ArrowLeft } from "lucide-react"
import { usePermissions } from "@/hooks/usePermissions"
import { getStatusConfig } from "@/lib/status-config"
import { canDecide } from "@/lib/utils/admission-permissions"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { SendConfirmationButton } from "./SendConfirmationButton"
import { SendMagicLinkButton } from "./SendMagicLinkButton"

interface AdmissionActionsProps {
  profile: AdmissionProfileResponse
  currentStep: number
  onStepChange: (step: number) => void
  isSaving: boolean
  onSave: () => void
  onCheckCondition?: () => void
}

export function AdmissionActions({
  profile,
  currentStep,
  onStepChange,
  isSaving,
  onSave,
  onCheckCondition,
}: AdmissionActionsProps) {
  const { can } = usePermissions(profile)
  const statusConfig = getStatusConfig(profile.status)

  // Sticky 'Tiếp tục' gate cùng điều kiện PipelineSidebar (Step 8 unlock).
  // Helper trusts BE-aggregated `permissions.has_decision`, fallback OR-7.
  const decide = canDecide(profile.permissions)
  // Hide Tiếp tục khi step 7 + no decision perm → user không advance qua
  // Step 8 disabled. Step 1-6 navigation vẫn cho phép.
  const showNextButton = currentStep < 8 && !(currentStep === 7 && !decide)

  return (
    <div className="fixed bottom-[var(--bottom-nav-height-safe)] left-0 right-0 lg:bottom-0 border-t bg-background z-40 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.1)]">
      {/* Mobile (<640px): allow horizontal scroll inside bar so wide
          action sets stay reachable without forcing page scroll. */}
      <div className="container max-w-7xl mx-auto h-16 px-3 sm:px-6 flex items-center justify-between gap-2 overflow-x-auto">
        {/* Status Badge */}
        <div className="flex items-center gap-4 flex-shrink-0">
          <span className="text-sm font-medium text-muted-foreground hidden sm:inline-block">
            Trạng thái:
          </span>
          <StatusBadge config={statusConfig} />
        </div>

        <div className="flex items-center gap-2 sm:gap-3 flex-shrink-0">
          {/* Back Button — all steps after the first (Commit 1: step 8 cũng có) */}
          {currentStep > 1 && (
            <Button variant="outline" onClick={() => onStepChange(currentStep - 1)}>
              <ArrowLeft className="w-4 h-4 mr-2" aria-hidden="true" />
              Quay lại
            </Button>
          )}

          {/* Save — step 1-7 with edit permission */}
          {currentStep < 8 && can('save') && (
            <Button variant="outline" onClick={onSave} disabled={isSaving}>
              {isSaving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" /> : <Save className="w-4 h-4 mr-2" aria-hidden="true" />}
              Lưu thay đổi
            </Button>
          )}

          {/* Next — step 1-7 + decision-perm gate cho 7→8 transition */}
          {showNextButton && (
            <Button onClick={() => onStepChange(currentStep + 1)}>
              Tiếp tục
              <ArrowRight className="w-4 h-4 ml-2" aria-hidden="true" />
            </Button>
          )}

          {/* Kiểm tra toàn bộ — step 8 utility, navigate to first error step */}
          {currentStep === 8 && onCheckCondition && (
            <Button variant="outline" onClick={onCheckCondition}>
              <ClipboardCheck className="w-4 h-4 mr-2" aria-hidden="true" />
              Kiểm tra toàn bộ
            </Button>
          )}

          {/* Outbound communication — mutex per state, max 1-2 visible. */}
          {can('send_confirmation') && (
            <SendConfirmationButton profileId={profile.id} />
          )}
          {can('send_submit_link') && (
            <SendMagicLinkButton profileId={profile.id} action="submit" />
          )}
          {can('send_resubmit_link') && (
            <SendMagicLinkButton profileId={profile.id} action="resubmit" />
          )}
          {can('send_withdraw_link') && (
            <SendMagicLinkButton profileId={profile.id} action="withdraw" />
          )}
        </div>
      </div>
    </div>
  )
}

interface StatusBadgeProps {
  config: ReturnType<typeof getStatusConfig>
}

function StatusBadge({ config }: StatusBadgeProps) {
  return <Badge className={config.badgeColor}>{config.label}</Badge>
}
