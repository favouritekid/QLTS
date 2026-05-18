/**
 * Priority KV preview API client (Q9 #07 Phase D.4)
 *
 * Wraps POST /api/v2/admissions/{id}/preview-priority-kv — real-time KV
 * resolution cho candidate FE PriorityTab draft state.
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
}

export interface PreviewPriorityKvResponse {
  kv_resolved: string | null
  pathway: string | null
  rule_applied: string | null
  requires_manual_override: boolean
  reason: string | null
  breakdown: Record<string, unknown> | null
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
