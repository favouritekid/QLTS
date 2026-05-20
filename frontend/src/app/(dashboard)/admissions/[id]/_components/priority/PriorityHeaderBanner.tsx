/**
 * Q9 #07 Phase E.4 — Priority workbench compact header banner.
 *
 * 1-dòng "Tạm tính: KV1 + UT04 = +1,75đ · UT07 chờ duyệt" với state badge.
 *
 * State badges (per spec Section II wireframe):
 *   🟢 happy        — engine OK + có verified UT
 *   🟠 ambiguous    — engine cần manual override
 *   ⚠ missing      — input data (cultural/vocational) chưa ghi nhận
 *   🔒 frozen       — post-submit, KV chốt
 *   🔧 override     — admin đã ấn định thủ công
 *
 * Accepts live `preview` (PR-3 P1 fix): draft state ưu tiên `preview.kv_resolved`,
 * `preview.requires_manual_override`, `preview.area_bonus`, `preview.ut_breakdown`
 * over snapshot. Post-submit (frozen/override) snapshot wins. KHÔNG fallback
 * snapshot stale khi preview present nhưng kv_resolved=null. Thin Client per
 * spec — chỉ status mapping, no business logic.
 */
"use client"

import type { PreviewPriorityKvResponse } from "@/lib/api/priority-kv"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

export type PriorityBannerState =
  | "happy"
  | "ambiguous"
  | "missing"
  | "frozen"
  | "override"

const STATE_BADGES: Record<PriorityBannerState, { icon: string; label: string; tone: string }> = {
  happy:     { icon: "🟢", label: "KV đã xác định",        tone: "text-emerald-700 bg-emerald-50 border-emerald-200" },
  ambiguous: { icon: "🟠", label: "Cần xác minh thủ công", tone: "text-orange-700 bg-orange-50 border-orange-200" },
  missing:   { icon: "⚠", label: "Thiếu thông tin",        tone: "text-amber-700 bg-amber-50 border-amber-200" },
  frozen:    { icon: "🔒", label: "Đã chốt",               tone: "text-slate-700 bg-slate-50 border-slate-200" },
  override:  { icon: "🔧", label: "Cán bộ ấn định",        tone: "text-purple-700 bg-purple-50 border-purple-200" },
}

/** Pure helper — derive banner state from profile + live preview.
 *
 * Precedence (per PR-3 audit cycle P1 fix):
 *   1. manual_override_reason on snapshot → "override" (always — even draft)
 *   2. status !== draft + snapshot.kv_resolved → "frozen" (post-submit
 *      snapshot is source of truth; preview ignored)
 *   3. cultural_education_level missing → "missing"
 *   4. status === draft AND preview present → derive from PREVIEW (live engine);
 *      don't fallback to snapshot when preview.kv_resolved=null (snapshot stale)
 *   5. otherwise → snapshot-derived (initial load, preview unavailable)
 *
 * Exported for tests.
 */
export function deriveBannerState(
  profile: Pick<
    AdmissionProfileResponse,
    "status" | "cultural_education_level" | "priority_resolution_snapshot"
  >,
  preview?: PreviewPriorityKvResponse | null,
): PriorityBannerState {
  const snapshot = profile.priority_resolution_snapshot ?? {}
  const isPostDraft = profile.status !== "draft"
  const hasOverride = Boolean(snapshot.manual_override_reason)
  const hasCulturalInput = Boolean(profile.cultural_education_level)

  if (hasOverride) return "override"
  if (isPostDraft && snapshot.kv_resolved) return "frozen"
  if (!hasCulturalInput) return "missing"

  // Draft: preview takes precedence — engine live recompute reflects
  // current §1 input. Snapshot can lag (frozen at last submit T1 hoặc
  // engine T6). Without preview-priority, banner shows stale state.
  if (preview) {
    if (preview.requires_manual_override) return "ambiguous"
    if (preview.kv_resolved) return "happy"
    // Preview present but no kv_resolved → engine can't determine → ambiguous.
    // Critically: do NOT fallback to snapshot stale.
    return "ambiguous"
  }

  // No preview yet (initial load) — derive from snapshot defensively.
  if (snapshot.requires_manual_override) return "ambiguous"
  if (snapshot.kv_resolved) return "happy"
  return "ambiguous"
}

export interface PriorityHeaderBannerProps {
  profile: AdmissionProfileResponse
  /**
   * P1 fix (PR-3 Step C audit cycle): live preview from /preview-priority-kv
   * — banner ưu tiên preview values cho "Tạm tính" để officer thấy kết quả
   * mới ngay khi đổi §1 inputs, KHÔNG stale snapshot. Fallback to snapshot
   * khi preview null (initial render hoặc preview disabled).
   */
  preview?: PreviewPriorityKvResponse | null
}

export function PriorityHeaderBanner({ profile, preview }: PriorityHeaderBannerProps) {
  const state = deriveBannerState(profile, preview)
  const badge = STATE_BADGES[state]
  const snapshot = profile.priority_resolution_snapshot ?? {}
  const isPostDraft = profile.status !== "draft"

  // P1 fix (PR-3 Step D audit): KV display precedence — snapshot
  // AUTHORITATIVE post-submit (frozen contract); preview ONLY in draft.
  // Critical: draft + preview present + kv=null → no snapshot fallback.
  const kv = (() => {
    if (isPostDraft) {
      // Post-submit: snapshot is frozen truth; preview ignored even if present.
      return snapshot.kv_resolved
    }
    if (preview) {
      return preview.kv_resolved
    }
    // Draft + no preview → snapshot defensive fallback (initial load).
    return snapshot.kv_resolved
  })()
  const areaBonus = (() => {
    if (isPostDraft) {
      const breakdown = snapshot.breakdown
      if (breakdown && typeof breakdown === "object" && "area_bonus" in breakdown) {
        const v = (breakdown as Record<string, unknown>).area_bonus
        return typeof v === "number" ? v : null
      }
      return null
    }
    if (typeof preview?.area_bonus === "number") return preview.area_bonus
    if (!preview) {
      const breakdown = snapshot.breakdown
      if (breakdown && typeof breakdown === "object" && "area_bonus" in breakdown) {
        const v = (breakdown as Record<string, unknown>).area_bonus
        return typeof v === "number" ? v : null
      }
    }
    return null
  })()

  const verifiedBucket = (() => {
    // Post-submit: snapshot ut_verified_bucket is frozen truth; preview ignored.
    if (isPostDraft) {
      const bucket = snapshot.ut_verified_bucket
      if (bucket && typeof bucket === "object") {
        const b = bucket as {
          applied_code?: string | null
          applied_rate?: number | null
        }
        if (b.applied_code && typeof b.applied_rate === "number") {
          return { code: b.applied_code, rate: b.applied_rate }
        }
      }
      return null
    }
    // Draft: preview live engine result wins; snapshot fallback only when
    // preview absent (initial load).
    const previewCode = preview?.ut_breakdown?.applied_code_verified ?? null
    const previewRate = preview?.object_bonus_verified
    if (previewCode && typeof previewRate === "number") {
      return { code: previewCode, rate: previewRate }
    }
    if (!preview) {
      const bucket = snapshot.ut_verified_bucket
      if (bucket && typeof bucket === "object") {
        const b = bucket as {
          applied_code?: string | null
          applied_rate?: number | null
        }
        if (b.applied_code && typeof b.applied_rate === "number") {
          return { code: b.applied_code, rate: b.applied_rate }
        }
      }
    }
    return null
  })()

  const pendingCodes = (() => {
    const evidence = profile.priority_object_evidence ?? {}
    return (profile.priority_object_codes ?? [])
      .filter((code) => evidence[code]?.status === "pending")
  })()

  const tongTamTinh = (areaBonus ?? 0) + (verifiedBucket?.rate ?? 0)

  return (
    <div
      data-testid="priority-header-banner"
      data-state={state}
      className={`flex items-center gap-3 rounded-md border px-4 py-2 text-sm font-medium ${badge.tone}`}
    >
      <span className="text-base leading-none" aria-hidden="true">
        {badge.icon}
      </span>
      <span className="font-semibold">{badge.label}:</span>
      {kv ? (
        <>
          <span>{kv}</span>
          {typeof areaBonus === "number" && (
            <span className="tabular-nums">+{areaBonus.toFixed(2)}đ</span>
          )}
        </>
      ) : (
        <span className="italic text-muted-foreground">Chưa có KV</span>
      )}
      {verifiedBucket && (
        <>
          <span className="opacity-60">·</span>
          <span>UT{verifiedBucket.code}</span>
          <span className="tabular-nums">+{verifiedBucket.rate.toFixed(2)}đ</span>
        </>
      )}
      <span className="opacity-60">=</span>
      <span className="tabular-nums font-bold">
        +{tongTamTinh.toFixed(2)}đ
      </span>
      {pendingCodes.length > 0 && (
        <span className="ml-auto text-xs font-normal opacity-80">
          {pendingCodes.map((c) => `UT${c}`).join(", ")} chờ duyệt
        </span>
      )}
    </div>
  )
}
