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
  /**
   * Q9 #07 Phase E.4 PR-2 — Upload UT evidence document.
   *
   * POST multipart /api/v2/admissions/{id}/priority-evidence/{sub_code}/upload
   * BE service `upload_priority_evidence_document` (admission_service) enforces:
   * - Profile status in APPLICANT_DOC_MUTATION_STATES
   * - sub_code MUST be in priority_object_codes
   * - sub_code MUST exist in PriorityObjectConfig catalog year
   * - File: PDF/JPG/PNG ≤10MB + magic-byte sniff
   * - ADM-007 staging/finalize (file promoted post-commit)
   * - P1: re-upload trên verified/rejected status auto-reset JSONB +
   *   recompute ut_verified_bucket + bump version
   */
  async upload(
    profileId: number,
    subCode: string,
    file: File,
  ): Promise<AdmissionProfileResponse> {
    const formData = new FormData()
    formData.append("file", file)
    const { data } = await api.post<AdmissionProfileResponse>(
      `/api/v2/admissions/${profileId}/priority-evidence/${subCode}/upload`,
      formData,
      { headers: { "Content-Type": "multipart/form-data" } },
    )
    return data
  },
  /**
   * Q9 #07 Phase E.4 PR-2 — Untick UT code + cascade hard delete.
   *
   * DELETE /api/v2/admissions/{id}/priority-evidence/{sub_code}
   * Body: { version: int } — optimistic lock.
   *
   * BE service `untick_priority_evidence` (priority_override_service) atomic
   * 4-mutation contract: remove from codes + evidence JSONB + DELETE
   * profile_document row + INSERT priority_audit_log. S3 file unlink
   * best-effort POST-commit (ADM-007 finalize).
   *
   * Decision #4 UI safety: FE confirm dialog BEFORE call. Service assumes
   * caller confirmed (no double-prompt).
   */
  async untick(
    profileId: number,
    subCode: string,
    version: number,
  ): Promise<AdmissionProfileResponse> {
    const { data } = await api.delete<AdmissionProfileResponse>(
      `/api/v2/admissions/${profileId}/priority-evidence/${subCode}`,
      { data: { version } },
    )
    return data
  },
}
