/**
 * Pure helper resolveEngineDisplay — extract từ EngineResultCard.
 *
 * Tính 4 derived display values cho engine card:
 *   - kv          : KV resolved (frozen snapshot post-draft, preview trong draft)
 *   - lawCitation : BE-first `snapshot.rule_law_citation` → fallback FE
 *                   `deriveLawCitationFallback(rule_applied)` cho legacy snapshot
 *   - reason      : BE-first `snapshot.basis_reason` → fallback `snapshot.reason`
 *                   (error-only). Trong draft → đọc `preview.reason`.
 *   - areaBonus   : `snapshot.breakdown.area_bonus` post-draft; `preview.area_bonus`
 *                   trong draft.
 *
 * Frozen contract — snapshot AUTHORITATIVE post-submit; preview chỉ consulted
 * trong draft. Defensive vs preview accidentally fired post-submit (PriorityTab
 * gates query, nhưng helper cũng defensive).
 *
 * BE source-of-truth: priority_service.py:836-866 + resolve_law_citation()
 * (line 843).
 */

import type { PreviewPriorityKvResponse } from "@/lib/api/priority-kv"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

export interface EngineDisplay {
  kv: string | null
  lawCitation: string | null
  reason: string | null
  areaBonus: number
}

/**
 * Fallback law citation cho frozen snapshot khi BE chưa trả `rule_law_citation`
 * (legacy snapshot pre-Commit-3 deploy). Map MUST align BE
 * priority_service.RULE_LAW_CITATION (5 keys).
 */
export function deriveLawCitationFallback(ruleApplied: string): string | null {
  const map: Record<string, string | null> = {
    longest_duration: "TT 05/2021 Phụ lục 01 Mục 5.b",
    tiebreak_graduation_school: "TT 05/2021 Phụ lục 01 Mục 5.a",
    commune_lookup: "TT 05/2021 Phụ lục 01 Mục 4",
    manual_override: "TT 05/2021 Phụ lục 01 Mục 6 (admin override)",
    ambiguous_requires_manual: null,
  }
  return map[ruleApplied] ?? null
}

export function resolveEngineDisplay(
  profile: Pick<AdmissionProfileResponse, "status" | "priority_resolution_snapshot">,
  preview: PreviewPriorityKvResponse | null,
): EngineDisplay {
  const snapshot = profile.priority_resolution_snapshot ?? {}
  const isPostDraft = profile.status !== "draft"

  const kv = (() => {
    if (isPostDraft) return snapshot.kv_resolved ?? null
    if (preview) return preview.kv_resolved ?? null
    return snapshot.kv_resolved ?? null
  })()

  const lawCitation = (() => {
    const snapshotCitation =
      typeof snapshot.rule_law_citation === "string" && snapshot.rule_law_citation
        ? snapshot.rule_law_citation
        : null
    const snapshotFallback =
      snapshot.rule_applied && typeof snapshot.rule_applied === "string"
        ? deriveLawCitationFallback(snapshot.rule_applied as string)
        : null

    if (isPostDraft) {
      return snapshotCitation ?? snapshotFallback
    }
    if (preview) return preview.rule_law_citation
    return snapshotCitation ?? snapshotFallback
  })()

  const reason = (() => {
    if (isPostDraft) return snapshot.basis_reason ?? snapshot.reason ?? null
    if (preview) return preview.reason ?? null
    return snapshot.basis_reason ?? snapshot.reason ?? null
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

  return { kv: kv ?? null, lawCitation, reason, areaBonus }
}
