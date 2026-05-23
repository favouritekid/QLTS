/**
 * Admission permission-flag helpers (FE thin client, BE = source of truth).
 *
 * BE `_compute_frontend_fields` in `admission_service.py` aggregates the
 * decision-perm flags into `permissions.has_decision`. We trust that flag
 * when present; otherwise fall back to the OR of the 7 individual flags
 * for forward-compat with deployments that haven't shipped the aggregate
 * yet. Once `has_decision` is universally present, the fallback can be
 * dropped.
 *
 * Ref: PR #323 review P2-1 (memory `admission-review-followups-2026-05-22`).
 */
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

type AdmissionPermissions = AdmissionProfileResponse["permissions"]

export function canDecide(perms: AdmissionPermissions | undefined): boolean {
  return Boolean(
    perms?.has_decision ??
      (perms?.approve ||
        perms?.reject ||
        perms?.resubmit ||
        perms?.submit ||
        perms?.request_revision ||
        perms?.publish_result ||
        perms?.enroll),
  )
}
