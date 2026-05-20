/**
 * Q9 #07 Phase E.4 — § 2 Khu vực ưu tiên (KV) card with 5 states.
 *
 * Officer-friendly UX refactor: keeps the engine result + reason on
 * the main surface, but pushes the law citation and admin-override
 * affordance into disclosures so the main flow stays focused on
 * "what KV applies right now" instead of legal references.
 *
 * 5 states (per spec Section II wireframe):
 *
 *   🟢 happy        — engine OK, KV resolved
 *   🟠 ambiguous    — requires_manual_override; primary CTA "Chọn KV thủ công"
 *   ⚠ missing      — cultural/vocational chưa fill; redirect to §1
 *   🔒 frozen       — post-submit, read-only; show frozen snapshot
 *   🔧 override     — manual_override_reason non-null; show overrider + reason
 *
 * Override CTA via disclosure (collapsed default for happy/frozen;
 * expanded primary for ambiguous). Dialog state lifted to caller
 * (PriorityTab) — this component dispatches `onOpenOverride` callback.
 */
"use client"

import { ChevronDown, FileText, ShieldAlert, ShieldCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import type { PreviewPriorityKvResponse } from "@/lib/api/priority-kv"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

export type EngineResultState =
  | "happy"
  | "ambiguous"
  | "missing"
  | "frozen"
  | "override"

const STATE_HEADERS: Record<
  EngineResultState,
  { icon: string; title: string; tone: string }
> = {
  happy:     { icon: "🟢", title: "Khu vực ưu tiên (KV)",        tone: "border-emerald-200 bg-emerald-50/40" },
  ambiguous: { icon: "🟠", title: "Cần xác minh thủ công",       tone: "border-orange-300 bg-orange-50/60" },
  missing:   { icon: "⚠", title: "Thiếu thông tin trình độ",    tone: "border-amber-300 bg-amber-50/40" },
  frozen:    { icon: "🔒", title: "Khu vực ưu tiên (đã chốt)",  tone: "border-slate-300 bg-slate-50/60" },
  override:  { icon: "🔧", title: "Cán bộ đã ấn định KV",        tone: "border-purple-300 bg-purple-50/40" },
}

/**
 * Pure derivation — exported for unit tests.
 *
 * Precedence (mirror PriorityHeaderBanner P1 contract):
 *   1. manual_override_reason → "override" (always)
 *   2. status !== draft + snapshot.kv_resolved → "frozen" (snapshot wins post-submit)
 *   3. !cultural_education_level → "missing"
 *   4. status === draft AND preview present → derive from PREVIEW only;
 *      KHÔNG fallback snapshot stale khi preview.kv_resolved=null
 *   5. draft + no preview → snapshot-derived (initial load defensive)
 */
export function deriveEngineState(
  profile: Pick<
    AdmissionProfileResponse,
    "status" | "cultural_education_level" | "priority_resolution_snapshot"
  >,
  preview: PreviewPriorityKvResponse | null,
): EngineResultState {
  const snapshot = profile.priority_resolution_snapshot ?? {}
  const hasOverride = Boolean(snapshot.manual_override_reason)
  if (hasOverride) return "override"

  const isPostDraft = profile.status !== "draft"
  if (isPostDraft && snapshot.kv_resolved) return "frozen"

  if (!profile.cultural_education_level) return "missing"

  // Draft + preview present → preview takes precedence (live engine).
  // Critical: don't fallback snapshot when preview says "no KV" — UI must
  // reflect engine's current view, not stale frozen snapshot.
  if (preview) {
    if (preview.requires_manual_override) return "ambiguous"
    if (preview.kv_resolved) return "happy"
    return "ambiguous"
  }

  // No preview (initial load) — snapshot defensive fallback.
  if (snapshot.requires_manual_override) return "ambiguous"
  if (snapshot.kv_resolved) return "happy"
  return "ambiguous"
}

export interface EngineResultCardProps {
  profile: AdmissionProfileResponse
  /** Live preview from /preview-priority-kv (post §1 edit). */
  preview: PreviewPriorityKvResponse | null
  /** Officer/admin permission flag — toggles override disclosure. */
  canOverride: boolean
  /** Caller opens dialog (state lifted to PriorityTab). */
  onOpenOverride: () => void
}

export function EngineResultCard({
  profile,
  preview,
  canOverride,
  onOpenOverride,
}: EngineResultCardProps) {
  const state = deriveEngineState(profile, preview)
  const header = STATE_HEADERS[state]
  const snapshot = profile.priority_resolution_snapshot ?? {}
  const isPostDraft = profile.status !== "draft"

  // P1 fix (PR-3 Step D audit): frozen contract — snapshot AUTHORITATIVE
  // post-submit; preview only consulted trong draft. Defensive vs preview
  // accidentally fired post-submit (PriorityTab gates query, but components
  // also defensive).
  const kv = (() => {
    if (isPostDraft) return snapshot.kv_resolved ?? null
    if (preview) return preview.kv_resolved ?? null
    return snapshot.kv_resolved ?? null
  })()
  const lawCitation = (() => {
    if (isPostDraft) {
      if (snapshot.rule_applied && typeof snapshot.rule_applied === "string") {
        return deriveLawCitationFallback(snapshot.rule_applied as string)
      }
      return null
    }
    if (preview) return preview.rule_law_citation
    if (snapshot.rule_applied && typeof snapshot.rule_applied === "string") {
      return deriveLawCitationFallback(snapshot.rule_applied as string)
    }
    return null
  })()
  const reason = (() => {
    if (isPostDraft) return snapshot.reason ?? null
    if (preview) return preview.reason ?? null
    return snapshot.reason ?? null
  })()
  const areaBonus = (() => {
    if (isPostDraft) {
      const breakdown = snapshot.breakdown
      if (breakdown && typeof breakdown === "object" && "area_bonus" in breakdown) {
        const v = (breakdown as Record<string, unknown>).area_bonus
        return typeof v === "number" ? v : 0
      }
      return 0
    }
    if (typeof preview?.area_bonus === "number") return preview.area_bonus
    return 0
  })()

  return (
    <section
      data-testid="engine-result-card"
      data-state={state}
      className={`space-y-3 rounded-lg border p-4 ${header.tone}`}
    >
      <div className="flex items-baseline gap-2 text-base font-semibold">
        <span aria-hidden="true">{header.icon}</span>
        <span>{header.title}</span>
      </div>

      {/* Happy / frozen / override → KV + bonus + reason. Law citation
          MOVED into the disclosure below to keep main flow focused. */}
      {(state === "happy" || state === "frozen" || state === "override") && (
        <div className="space-y-2 text-sm">
          {kv ? (
            <p className="flex items-baseline gap-2">
              <span className="font-bold">{kv}</span>
              {typeof areaBonus === "number" && areaBonus > 0 && (
                <span className="tabular-nums">(+{areaBonus.toFixed(2)}đ)</span>
              )}
              {state === "frozen" && snapshot.frozen_at && (
                <span className="ml-2 text-xs opacity-70">
                  · chốt {formatTimestamp(snapshot.frozen_at as string)}
                </span>
              )}
            </p>
          ) : (
            <p className="italic text-muted-foreground">Chưa có KV.</p>
          )}

          {reason && (
            <p className="text-sm">
              <span className="font-medium">Lý do:</span> {reason}
            </p>
          )}

          {state === "override" && snapshot.manual_override_reason && (
            <div className="mt-2 rounded-md border border-purple-200 bg-purple-50/60 p-2 text-xs">
              <p>
                <span className="font-medium">Ấn định bởi:</span>{" "}
                {(snapshot.manual_override_by as string | number | null) ?? "—"}
                {snapshot.manual_override_at && (
                  <span className="ml-2 opacity-70">
                    · {formatTimestamp(snapshot.manual_override_at as string)}
                  </span>
                )}
              </p>
              <p className="mt-1">
                <span className="font-medium">Lý do ấn định:</span>{" "}
                {String(snapshot.manual_override_reason)}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Ambiguous — primary CTA visible, reason from engine */}
      {state === "ambiguous" && (
        <div className="space-y-2 text-sm">
          {reason && (
            <p>
              <span className="font-medium">Lý do:</span> {reason}
            </p>
          )}
          {canOverride && (
            <Button
              type="button"
              size="sm"
              onClick={onOpenOverride}
              data-testid="engine-result-ambiguous-cta"
              className="bg-orange-600 hover:bg-orange-700 text-white"
            >
              <ShieldAlert className="h-4 w-4 mr-2" />
              Chọn KV thủ công
            </Button>
          )}
        </div>
      )}

      {/* Missing — instructional, no primary CTA */}
      {state === "missing" && (
        <p className="text-sm text-muted-foreground">
          Vui lòng khai trình độ văn hóa ở phần trên + lịch sử học THPT ở tab
          &quot;Học tập&quot; để hệ thống xác định KV.
        </p>
      )}

      {/* Căn cứ chi tiết disclosure — collapsed default, expands to show
          the law citation. Kept out of main flow per PR-3 audit P1 UX. */}
      {lawCitation && (
        <Collapsible>
          <CollapsibleTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              data-testid="engine-result-citation-disclosure"
              className="gap-2 text-muted-foreground hover:text-foreground"
            >
              <FileText className="h-4 w-4" />
              Căn cứ chi tiết
              <ChevronDown className="h-4 w-4" />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent
            className="pt-2 text-xs text-muted-foreground"
            data-testid="engine-result-citation-content"
          >
            {lawCitation}
          </CollapsibleContent>
        </Collapsible>
      )}

      {/* Override admin affordance — collapsed default cho happy/frozen.
          Wording avoids "dialog" / "override" English jargon. */}
      {canOverride &&
        (state === "happy" || state === "frozen" || state === "override") && (
          <Collapsible>
            <CollapsibleTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="sm"
                data-testid="engine-result-override-disclosure"
                className="gap-2"
              >
                <ChevronDown className="h-4 w-4" />
                {state === "override"
                  ? "Ấn định lại KV"
                  : "Ấn định KV thủ công"}
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-2">
              <Button
                type="button"
                variant="default"
                size="sm"
                onClick={onOpenOverride}
                data-testid="engine-result-override-trigger"
              >
                <ShieldCheck className="h-4 w-4 mr-2" />
                Mở hộp thoại ấn định KV
              </Button>
            </CollapsibleContent>
          </Collapsible>
        )}
    </section>
  )
}

// =============================================================================
// PURE HELPERS
// =============================================================================

/**
 * Fallback law citation cho frozen snapshot khi preview null. Map MUST align
 * BE priority_service.RULE_LAW_CITATION (5 keys).
 */
function deriveLawCitationFallback(ruleApplied: string): string | null {
  const map: Record<string, string | null> = {
    longest_duration: "TT 05/2021 Phụ lục 01 Mục 5.b",
    tiebreak_graduation_school: "TT 05/2021 Phụ lục 01 Mục 5.a",
    commune_lookup: "TT 05/2021 Phụ lục 01 Mục 4",
    manual_override: "TT 05/2021 Phụ lục 01 Mục 6 (admin override)",
    ambiguous_requires_manual: null,
  }
  return map[ruleApplied] ?? null
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString("vi-VN", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  } catch {
    return iso
  }
}
