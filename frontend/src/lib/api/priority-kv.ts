/**
 * Priority KV+UT preview API client (Q9 #07 Phase D.4 + Phase E wireframe)
 *
 * Wraps POST /api/v2/admissions/{id}/preview-priority-kv — real-time KV+UT
 * resolution cho FE PriorityTab + UtPolicyPanel (workbench).
 *
 * Mirrors `app/schemas/admission.py::PreviewPriorityKvRequest/Response`.
 */
import { api } from "@/lib/api/client"

export interface PreviewPriorityKvRequest {
  cultural_education_level?: string | null
  vocational_qualification?: string | null
  area_resolution_basis?: string | null
  permanent_commune_code?: string | null
  academic_history?: Array<{
    school_id?: number | null
    school_name: string
    level?: string | null
    year_from: number
    year_to: number
    grade_to?: number | null
    gpa?: number | null
    graduation_type?: string | null
  }> | null
  // Phase E wireframe — UT live preview override
  priority_object_codes?: string[] | null
}

export interface UtBreakdown {
  codes_submitted: string[]
  applied_code_potential: string | null
  applied_rate_potential: string | null
  verified_codes: string[]
  applied_code_verified: string | null
  applied_rate_verified: string | null
}

export interface PreviewPriorityKvResponse {
  // KV (existing Phase D)
  kv_resolved: string | null
  pathway: string | null
  rule_applied: string | null
  requires_manual_override: boolean
  reason: string | null
  breakdown: Record<string, unknown> | null
  // Phase E wireframe — bonus points + UT
  area_bonus: number | null
  object_bonus_potential: number | null
  object_bonus_verified: number | null
  ut_breakdown: UtBreakdown | null
  total_bonus_potential: number | null
  // Q9 #07 Phase E.4 — law citation resolved from rule_applied. FE
  // EngineResultCard hiển thị "Căn cứ: <citation>" để officer scan/trust.
  // Null khi rule_applied không match map (vd ambiguous_requires_manual).
  rule_law_citation: string | null
  // Code review 2026-05-22 — path's bonus cap rule denorm trong preview
  // để PrioritySummaryPanel render cap consistent giữa draft và frozen.
  // Shape match snapshot.path_bonus_rule. Null nếu chain chưa eager-load
  // (preview best-effort).
  path_bonus_rule: { max_total_bonus?: number | null } | null
}

export const priorityKvApi = {
  async preview(
    profileId: number,
    body: PreviewPriorityKvRequest,
  ): Promise<PreviewPriorityKvResponse> {
    const { data } = await api.post<PreviewPriorityKvResponse>(
      `/api/v2/admissions/${profileId}/preview-priority-kv`,
      body,
    )
    return data
  },
}
