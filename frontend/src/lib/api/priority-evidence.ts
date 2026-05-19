/**
 * Q9 #07 Phase E.3 — UT evidence verify/reject API client.
 *
 * Wraps PATCH endpoints:
 * * ``/api/v2/admissions/{id}/priority-objects/{sub_code}/verify``
 * * ``/api/v2/admissions/{id}/priority-objects/{sub_code}/reject``
 *
 * BE service (priority_override_service) enforces version guard +
 * sub_code-in-codes + status whitelist + reason validation + snapshot
 * ut_verified_bucket recompute + audit log + outbox dispatch.
 */
import { api } from "@/lib/api/client"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import type {
  RejectObjectEvidenceRequest,
  VerifyObjectEvidenceRequest,
} from "@/lib/zod/priority-evidence"

export const priorityEvidenceApi = {
  async verify(
    profileId: number,
    subCode: string,
    body: VerifyObjectEvidenceRequest,
  ): Promise<AdmissionProfileResponse> {
    const { data } = await api.patch<AdmissionProfileResponse>(
      `/api/v2/admissions/${profileId}/priority-objects/${subCode}/verify`,
      body,
    )
    return data
  },
  async reject(
    profileId: number,
    subCode: string,
    body: RejectObjectEvidenceRequest,
  ): Promise<AdmissionProfileResponse> {
    const { data } = await api.patch<AdmissionProfileResponse>(
      `/api/v2/admissions/${profileId}/priority-objects/${subCode}/reject`,
      body,
    )
    return data
  },
}
