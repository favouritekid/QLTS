import { ADMISSION_STEPS, STEP } from "@/lib/constants/admission-steps"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

/**
 * Total count for the "Vấn đề cần sửa" badge/panel = response validation errors
 * + derived Step-4 priority issues + required-data (family/academic) count.
 * Centralized so IssueSummary and MobileIssueDrawer never disagree on which
 * terms make up the badge count.
 */
export function issueTotalCount(
  validationErrorsLength: number,
  priorityIssuesLength: number,
  grouped?: { required_data?: { count: number } } | null,
): number {
  return validationErrorsLength + priorityIssuesLength + (grouped?.required_data?.count ?? 0)
}

type StepStatus = "success" | "warning" | "error" | "locked"

/**
 * Steps whose submit-required data is still empty — family info (step 2) and
 * academic history (step 3). Mirrors the backend submit gate
 * `_missing_submit_required_data` (admission_service.py) so the CTA can jump to
 * the EXACT blocking tab rather than the first amber step. Returned in step order.
 */
export function missingRequiredDataSteps(
  profile: AdmissionProfileResponse | null,
): number[] {
  if (!profile) return []
  // Match the backend: `_missing_submit_required_data` only runs for drafts, so
  // required_data.count / submit_blocked_by_data are 0 on non-draft statuses.
  // A submitted/approved profile with legacy-empty family/academic is NOT
  // submit-blocked by them, so must NOT outrank a real priority issue and send
  // the CTA to a read-only step 2/3 dead end.
  if (profile.status !== "draft") return []
  const steps: number[] = []
  if (!profile.family_info?.length) steps.push(STEP.FAMILY)
  if (!profile.academic_history?.length) steps.push(STEP.ACADEMIC)
  return steps
}

/**
 * Pick the step the "việc cần xử lý" CTA should jump to. Driven by the SAME issue
 * sources that feed {@link issueTotalCount} so the CTA can never dead-end or land
 * on an unrelated tab. Priority order:
 *   1. First "error" step — always a genuine blocker (personal/scores/docs).
 *   2. Required-data: the earliest still-empty family(2)/academic(3) step. This
 *      HARD-blocks submit but usually shows only as a step 2/3 "warning", so jump
 *      straight to it — skipping an earlier NON-blocking warning (e.g. step 1 amber
 *      for blank OPTIONAL fields) AND landing on the RIGHT tab when only academic
 *      is missing while step 2 is amber for an unrelated reason.
 *   3. Priority (step 4) issues (missing UT evidence / manual override): count
 *      toward the badge but never mark step 4 error/warning once KV is resolved,
 *      so route there explicitly instead of falling through to a dead end.
 *   4. First remaining "warning" step.
 * Returns null when no step needs attention.
 */
export function firstAttentionStep(
  stepsStatus: Record<number, StepStatus>,
  opts: { requiredDataSteps: number[]; priorityIssuesCount: number },
): number | null {
  // Iterate in pipeline order, derived from the registry so a step add/reorder
  // flows through automatically.
  const orderedIds = ADMISSION_STEPS.map((s) => s.id)
  const firstWith = (status: StepStatus) =>
    orderedIds.find((s) => stepsStatus[s] === status) ?? null

  const errorStep = firstWith("error")
  if (errorStep !== null) return errorStep

  if (opts.requiredDataSteps.length > 0) return Math.min(...opts.requiredDataSteps)

  if (opts.priorityIssuesCount > 0) return STEP.PRIORITY

  return firstWith("warning")
}

/**
 * Derive Priority (Step 4) issues from BE-set flags only.
 *
 * Trả về danh sách thông điệp Việt hóa để hiển thị trong IssueSummary /
 * MobileIssueDrawer / badge count. Chỉ flag khi BE thật sự báo unresolved
 * hoặc thiếu input nguồn — KHÔNG đếm `kv_resolved === null` ở trạng thái
 * draft vì hồ sơ chưa preview cũng null (tránh lỗi giả).
 *
 * 4 trigger nguồn (BE service `admission_service.py:1795` đánh Step 4
 * error/warning):
 *   1. requires_manual_override = engine bí, cần ấn định thủ công
 *   2. missing_priority_evidence_codes = thiếu file minh chứng UT
 *   3. !cultural_education_level = thiếu input "Trình độ văn hóa"
 *      (5-state EngineResultCard "missing" state).
 *   4. status !== "draft" + kv_resolved == null = post-submit chưa
 *      resolve (rare, defensive — chỉ flag ngoài draft).
 */
export function derivePriorityIssues(profile: AdmissionProfileResponse | null): string[] {
  if (!profile) return []

  const issues: string[] = []

  const snapshot = profile.priority_resolution_snapshot ?? null
  if (snapshot?.requires_manual_override === true) {
    issues.push("Khu vực ưu tiên chưa xác định, cần quản lý ấn định hoặc sửa dữ liệu nguồn.")
  }

  // Followup fix #4: thiếu cultural_education_level = engine không thể
  // resolve KV. Step 4 sidebar badge sẽ đỏ nhưng IssueSummary trước đây
  // không nói lý do → user không biết phải sửa gì.
  if (!profile.cultural_education_level) {
    issues.push("Chưa khai trình độ văn hóa — bắt buộc để hệ thống xác định KV.")
  }

  // Defensive: post-submit + KV chưa resolve = engine fail-closed nhưng
  // requires_manual_override flag không set. Hiếm gặp nhưng nên surface.
  const kv = typeof snapshot?.kv_resolved === "string" ? snapshot.kv_resolved : null
  if (
    profile.status !== "draft" &&
    !kv &&
    snapshot?.requires_manual_override !== true
  ) {
    issues.push("Hồ sơ đã nộp nhưng chưa resolve được KV. Liên hệ quản trị.")
  }

  const missingUt = profile.missing_priority_evidence_codes ?? []
  if (missingUt.length > 0) {
    // BE có thể trả ["07"] hoặc ["UT07"]; chuẩn hóa prefix UT cho UI.
    const labeled = missingUt.map((c) => (c.startsWith("UT") ? c : `UT${c}`))
    issues.push(`Thiếu minh chứng ưu tiên: ${labeled.join(", ")}`)
  }

  return issues
}
