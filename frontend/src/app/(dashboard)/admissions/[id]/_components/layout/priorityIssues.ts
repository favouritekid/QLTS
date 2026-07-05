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
 * Pick the step the "việc cần xử lý" CTA should jump to. Driven by the SAME issue
 * sources that feed {@link issueTotalCount} so the CTA can never dead-end or land
 * on an unrelated tab. Priority order:
 *   1. First "error" step — always a genuine blocker (personal/scores/docs).
 *   2. Required-data (family/academic): HARD-blocks submit but only surfaces as a
 *      step 2/3 "warning" — prefer it over an earlier NON-blocking warning (e.g.
 *      step 1 amber for blank OPTIONAL personal fields) so the user lands on the
 *      real blocker instead of a tab that leaves submit disabled.
 *   3. Priority (step 4) issues (missing UT evidence / manual override): count
 *      toward the badge but never mark step 4 error/warning once KV is resolved,
 *      so route there explicitly instead of falling through to a dead end.
 *   4. First remaining "warning" step.
 * Returns null when no step needs attention.
 */
export function firstAttentionStep(
  stepsStatus: Record<number, StepStatus>,
  opts: { requiredDataCount: number; priorityIssuesCount: number },
): number | null {
  const ALL_STEPS = [1, 2, 3, 4, 5, 6, 7, 8]
  const firstWith = (status: StepStatus, steps: number[]) =>
    steps.find((s) => stepsStatus[s] === status) ?? null

  const errorStep = firstWith("error", ALL_STEPS)
  if (errorStep !== null) return errorStep

  if (opts.requiredDataCount > 0) {
    const dataStep = firstWith("warning", [2, 3])
    if (dataStep !== null) return dataStep
  }

  if (opts.priorityIssuesCount > 0) return 4

  return firstWith("warning", ALL_STEPS)
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
