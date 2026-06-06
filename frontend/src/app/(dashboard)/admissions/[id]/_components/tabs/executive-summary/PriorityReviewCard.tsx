/**
 * PriorityReviewCard — compact "Ưu tiên / KV" cockpit signal.
 *
 * BE-driven: reads priority_resolution_snapshot (kv_resolved, ut_verified_bucket,
 * requires_manual_override) + missing_priority_evidence_codes. Detail (bonus
 * breakdown / cap / override reason) lives in InspectionDetails, NOT here — the
 * cockpit only answers "đủ duyệt chưa, vướng gì".
 */

"use client"

import { SignalCell, type SignalTone } from "./SignalCell"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface PriorityReviewCardProps {
  profile: AdmissionProfileResponse
}

export function PriorityReviewCard({ profile }: PriorityReviewCardProps) {
  const snapshot = profile.priority_resolution_snapshot ?? {}
  const kv = typeof snapshot.kv_resolved === "string" ? snapshot.kv_resolved : null
  const requiresManualOverride = snapshot.requires_manual_override === true
  const hasManualOverride = Boolean(snapshot.manual_override_reason)
  const missingUtCount = profile.missing_priority_evidence_codes?.length ?? 0

  const utBucket = (() => {
    const b = snapshot.ut_verified_bucket
    if (b && typeof b === "object" && "applied_code" in b) {
      const code = (b as { applied_code?: string | null }).applied_code
      const rate = (b as { applied_rate?: number | null }).applied_rate
      if (typeof code === "string" && typeof rate === "number") return { code, rate }
    }
    return null
  })()

  // Bonus cap (mirror the legacy card): area_bonus + UT rate vs path max_total_bonus.
  const areaBonus = (() => {
    const bd = snapshot.breakdown
    if (bd && typeof bd === "object" && "area_bonus" in bd) {
      const v = (bd as Record<string, unknown>).area_bonus
      return typeof v === "number" ? v : 0
    }
    return 0
  })()
  const maxTotalBonus = (() => {
    const r = snapshot.path_bonus_rule
    if (r && typeof r === "object" && "max_total_bonus" in r) {
      const v = (r as { max_total_bonus?: number | null }).max_total_bonus
      return typeof v === "number" ? v : null
    }
    return null
  })()
  const isCapped = typeof maxTotalBonus === "number" && areaBonus + (utBucket?.rate ?? 0) > maxTotalBonus

  const tone: SignalTone = requiresManualOverride
    ? "error"
    : missingUtCount > 0
      ? "warning"
      : kv
        ? "success"
        : "warning"

  // `||` (not `??`) so an empty-string kv_resolved also falls back — matches the
  // tone check below which already treats "" as falsy ("Chưa xác định KV").
  const primary = kv || "Chưa xác định KV"
  // Secondary = the most urgent ISSUE (base), then DURABLE provenance/cap suffixes so
  // the cell self-contains the decision state. The audit line is only "gần đây" (the
  // latest event) — it can't be the sole carrier of "override applied" because the
  // next audit event would hide it. Order: issue → provenance → cap.
  const base = requiresManualOverride
    ? "Cần ấn định KV thủ công"
    : missingUtCount > 0
      ? `Thiếu ${missingUtCount} minh chứng UT`
      : utBucket
        ? `UT${utBucket.code} hợp lệ (+${utBucket.rate.toFixed(2)}đ)`
        : kv
          ? "Ưu tiên hợp lệ"
          : "Chưa có dữ liệu ưu tiên"
  const secondary =
    base +
    (hasManualOverride ? " · KV cán bộ ấn định" : "") +
    (isCapped ? " · bị cap" : "")

  return (
    <SignalCell
      testId="priority-review-card"
      title="Ưu tiên / KV"
      tone={tone}
      primary={primary}
      secondary={secondary}
    />
  )
}
