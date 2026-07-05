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
