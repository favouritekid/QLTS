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

type StepStatus = "success" | "warning" | "error" | "locked"

/**
 * Whether a step-navigation surface should DISABLE a step button. Single source
 * of truth shared by PipelineSidebar (desktop) and MobileStepStrip so the two
 * can't drift on which steps are reachable.
 *
 * Step 8 (Finalize) stays reachable for decision-capable users even when the
 * backend marks it "locked" (ineligible) — a UI-only navigation override so a
 * manager/admin can reach the decision surface. The BE mutation APIs
 * (approve/reject/submit/enroll/…) still validate the state machine + IDOR
 * independently, so this never bypasses authorization. Every other step locks
 * strictly on the backend "locked" status.
 *
 * NOTE: AdmissionActions' "Tiếp tục" gate is a DIFFERENT rule (advance past
 * step 7) — do not fold it in here.
 */
export function isStepNavLocked(
  stepId: number,
  status: StepStatus,
  decide: boolean,
): boolean {
  const isStep8Override = stepId === 8 && decide
  return !isStep8Override && status === "locked"
}
