import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

/**
 * Derive Priority (Step 4) issues from BE-set flags only.
 *
 * Trả về danh sách thông điệp Việt hóa để hiển thị trong IssueSummary /
 * MobileIssueDrawer / badge count. Chỉ flag khi BE thật sự báo unresolved
 * (`requires_manual_override`) hoặc thiếu evidence UT
 * (`missing_priority_evidence_codes`) — KHÔNG đếm `kv_resolved === null`
 * vì hồ sơ chưa preview cũng null (tránh lỗi giả).
 */
export function derivePriorityIssues(profile: AdmissionProfileResponse | null): string[] {
  if (!profile) return []

  const issues: string[] = []

  const snapshot = profile.priority_resolution_snapshot ?? null
  if (snapshot?.requires_manual_override === true) {
    issues.push("Khu vực ưu tiên chưa xác định, cần quản lý ấn định hoặc sửa dữ liệu nguồn.")
  }

  const missingUt = profile.missing_priority_evidence_codes ?? []
  if (missingUt.length > 0) {
    // BE có thể trả ["07"] hoặc ["UT07"]; chuẩn hóa prefix UT cho UI.
    const labeled = missingUt.map((c) => (c.startsWith("UT") ? c : `UT${c}`))
    issues.push(`Thiếu minh chứng ưu tiên: ${labeled.join(", ")}`)
  }

  return issues
}
