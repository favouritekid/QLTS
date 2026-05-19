/**
 * Q9 #07 Phase E.2 — Manual KV override API client.
 *
 * Wraps `POST /api/v2/admissions/{profile_id}/override-priority-kv` —
 * officer/admin write-path để override KV trên candidate's profile.
 *
 * Service-layer (Backend) enforces:
 * * Version guard FIRST → 409 ConflictError
 * * Status whitelist (officer: submitted/reviewing/revision_requested;
 *   admin bypass với acknowledge_post_publish=true)
 * * Reason 20-500 char validation
 * * Snapshot mutation + priority_audit_log INSERT + version bump
 *
 * Response: full `AdmissionProfileResponse` shape (router calls
 * `_populate_response_fields` after commit).
 */
import { api } from "@/lib/api/client"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

import type { OverridePriorityKvRequest } from "@/lib/zod/priority-override"

export const priorityOverrideApi = {
  async overrideKv(
    profileId: number,
    body: OverridePriorityKvRequest,
  ): Promise<AdmissionProfileResponse> {
    const { data } = await api.post<AdmissionProfileResponse>(
      `/api/v2/admissions/${profileId}/override-priority-kv`,
      body,
    )
    return data
  },
}
