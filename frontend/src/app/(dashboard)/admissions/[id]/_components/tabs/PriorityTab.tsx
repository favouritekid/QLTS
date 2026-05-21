"use client"

/**
 * Priority Tab (Q9 #07 Phase E.4 workbench compose — PR-3).
 *
 * Officer-driven workbench layout per spec V3 Section II. Replaces pre-E.4
 * 2-col KvDecisionPanel + UtPolicyPanel + PrioritySnapshotCard với 1-cột
 * linear flow:
 *
 *   ┌────────────────────────────────────────────────────────────┐
 *   │ PriorityHeaderBanner — 1-dòng "Tạm tính KV + UT = +1,75đ" │
 *   │ § 1. PriorityInputsSection — cultural + vocational + comm. │
 *   │ § 2. EngineResultCard — 5 KV states + law citation         │
 *   │ § 3. UtEvidenceCards — verify + reject + untick + warning  │
 *   │ § 4. PrioritySummaryPanel — tổng + audit + law disclosure  │
 *   └────────────────────────────────────────────────────────────┘
 *
 * Global [Lưu thay đổi] / [Tiếp tục →] buttons render via parent
 * AdmissionActions (per PR-3 adjustment #5, no duplicate action bar).
 *
 * Override dialog state lives here (not in EngineResultCard) cho version
 * guard + currentKv ownership.
 */
import { useState } from "react"
import { UseFormReturn } from "react-hook-form"

import { usePreviewPriorityKv } from "@/lib/hooks/use-preview-priority-kv"
import type { PreviewPriorityKvRequest } from "@/lib/api/priority-kv"
import { useAuthStore } from "@/lib/stores/auth.store"
import type {
  AdmissionProfileResponse,
  AdmissionProfileUpdateInput,
} from "@/lib/zod/admissions"

import { EngineResultCard } from "../priority/EngineResultCard"
import { PriorityHeaderBanner } from "../priority/PriorityHeaderBanner"
import { PriorityInputsSection } from "../priority/PriorityInputsSection"
import { PrioritySummaryPanel } from "../priority/PrioritySummaryPanel"
import { UtEvidenceCards } from "../priority/UtEvidenceCards"
import { PriorityOverrideDialog } from "../PriorityOverrideDialog"

interface PriorityTabProps {
  form: UseFormReturn<AdmissionProfileUpdateInput>
  profile: AdmissionProfileResponse
  isEditable: boolean
  /**
   * Adjustment #3 (PR-3 audit cycle): parent (AdmissionDetailClient) wires
   * setCurrentStep(6) callback. UtEvidenceCards "Mở tab Giấy tờ để upload"
   * navigation invokes this. Required prop — no default to surface gaps.
   */
  onNavigateToDocuments: () => void
}

export function PriorityTab({
  form,
  profile,
  isEditable,
  onNavigateToDocuments,
}: PriorityTabProps) {
  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false)
  const userRole = useAuthStore((s) => s.user?.role)

  // Form watches drive live preview query. Same fields as Phase E.3 PriorityTab.
  // Phase E.4 Finding 2 fix: KHÔNG watch + KHÔNG gửi `area_resolution_basis` vì
  // engine giờ tự suy ra basis từ cultural + vocational + permanent_commune_code
  // (yêu cầu nghiệp vụ #3 + #6). Field area_resolution_basis legacy có thể
  // còn `manual_override` (đặt qua PriorityOverrideDialog OUTPUT bypass) hoặc
  // `permanent_address_special` (legacy stale từ commit trước radio bị xoá);
  // truyền nó vào preview = ép engine đi nhánh cũ → engine fail-closed sai.
  const cultural = form.watch("cultural_education_level")
  const vocational = form.watch("vocational_qualification")
  const communeCode = form.watch("permanent_commune_code")
  const academicHistory = form.watch("academic_history")
  const utCodes = form.watch("priority_object_codes")

  // Live preview (debounced 500ms internally). P1 fix (PR-3 Step D audit):
  // gate enabled by status==='draft' — preview is a DRAFT-only feature.
  // Post-submit profiles → snapshot is frozen contract authoritative;
  // preview query không fire để tránh race với snapshot semantics.
  const isDraft = profile.status === "draft"
  const { data: preview } = usePreviewPriorityKv(
    profile.id,
    {
      cultural_education_level: cultural ?? null,
      vocational_qualification: vocational ?? null,
      // area_resolution_basis intentionally omitted (null) — auto-basis ở BE
      area_resolution_basis: null,
      permanent_commune_code: communeCode ?? null,
      academic_history:
        (academicHistory as PreviewPriorityKvRequest["academic_history"]) ?? null,
      priority_object_codes: utCodes ?? null,
    },
    !!cultural && isDraft,
  )

  const canOverride = Boolean(profile.permissions?.override_priority_kv)
  const canVerify = Boolean(profile.permissions?.verify_priority_object)

  const handleCodesChange = (newCodes: string[]) => {
    form.setValue("priority_object_codes", newCodes, {
      shouldDirty: true,
      shouldValidate: true,
    })
  }

  // Frozen snapshot KV cho PriorityOverrideDialog version guard (per
  // existing E.2 contract — dialog reads currentKv to compute diff).
  const frozenSnapshot = profile.priority_resolution_snapshot ?? {}
  const currentKv =
    (frozenSnapshot.kv_resolved as string | null | undefined) ??
    preview?.kv_resolved ??
    null

  return (
    <div className="space-y-4" data-testid="priority-tab-workbench">
      {/* Compact header — 1-dòng "Tạm tính KV + UT = +X,XXđ" with state badge */}
      <PriorityHeaderBanner profile={profile} preview={preview ?? null} />

      {/* § 1 Inputs — cultural + vocational + special-case + commune */}
      <PriorityInputsSection form={form} isEditable={isEditable} />

      {/* § 2 Engine result — 5 KV states + law citation + override disclosure */}
      <EngineResultCard
        profile={profile}
        preview={preview ?? null}
        canOverride={canOverride}
        onOpenOverride={() => setOverrideDialogOpen(true)}
      />

      {/* § 3 UT evidence — verify/reject/untick per code + missing warning */}
      <UtEvidenceCards
        profile={profile}
        canVerify={canVerify}
        isEditable={isEditable}
        onNavigateToDocuments={onNavigateToDocuments}
        onCodesChange={handleCodesChange}
      />

      {/* § 4 Summary — tổng + audit disclosure + law disclosure (no actions) */}
      <PrioritySummaryPanel profile={profile} preview={preview ?? null} />

      {/* Override dialog — version guard + currentKv state lives here */}
      <PriorityOverrideDialog
        open={overrideDialogOpen}
        onOpenChange={setOverrideDialogOpen}
        profileId={profile.id}
        profileVersion={profile.version ?? 0}
        profileStatus={profile.status}
        currentKv={currentKv}
        mode={userRole === "admin" ? "admin" : "officer"}
      />
    </div>
  )
}
