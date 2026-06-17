/**
 * Phase 3 PR-3D-B FE Wave B Day 10 — AuditReasonDialog reason templates.
 *
 * Per-action canned reasons for T10 (waitlist promote), T11 (waitlist
 * reject), T12 (manual decision override), T17 (admin rollback). Templates
 * are dropdown defaults — user MUST still type a free-text justification
 * (textarea required + min length validate). Reduces typing friction for
 * common cases without sacrificing audit trail quality.
 *
 * Min-length matches BE schema (T17 `AdmissionAdminRollbackRequest.reason`
 * min=10, T10 optional but FE enforces ≥10 for parity).
 */

export type AuditAction =
  | "waitlist_promote"
  | "waitlist_reject"
  | "manual_decision"
  | "admin_rollback"
  | "request_revision"

export interface ActionConfig {
  /** Display title — set as DialogTitle when opened. */
  title: string
  /** Helper sentence under title — explain consequence. */
  description: string
  /** Min length for free-text reason (matches BE schema). */
  minLength: number
  /** Max length for free-text reason. */
  maxLength: number
  /** Canned reason templates — appended to textarea on select. */
  templates: { value: string; label: string }[]
}

export const AUDIT_ACTION_CONFIG: Record<AuditAction, ActionConfig> = {
  waitlist_promote: {
    title: "Chuyển từ chờ ghế lên trúng tuyển",
    description:
      "Hành động này sẽ chuyển nguyện vọng từ trạng thái chờ ghế sang trúng tuyển và gửi thông báo cho thí sinh.",
    minLength: 10,
    maxLength: 500,
    templates: [
      {
        value: "promote_quota_freed",
        label: "Có chỉ tiêu trống do thí sinh khác từ chối",
      },
      {
        value: "promote_admin_review",
        label: "Quyết định ban tuyển sinh sau rà soát",
      },
      {
        value: "promote_appeal_approved",
        label: "Khiếu nại đã được chấp thuận",
      },
    ],
  },
  waitlist_reject: {
    title: "Từ chối nguyện vọng đang chờ ghế",
    description:
      "Hành động này sẽ chuyển nguyện vọng từ chờ ghế sang từ chối. Thí sinh sẽ nhận thông báo.",
    minLength: 10,
    maxLength: 500,
    templates: [
      { value: "reject_quota_filled", label: "Chỉ tiêu đã đầy" },
      { value: "reject_deadline_passed", label: "Hết hạn xét bổ sung" },
      {
        value: "reject_documents_incomplete",
        label: "Hồ sơ chưa hoàn thiện sau nhắc nhở",
      },
    ],
  },
  manual_decision: {
    title: "Quyết định thủ công",
    description:
      "Ghi đè quyết định của engine xét tuyển bằng quyết định thủ công của quản trị viên.",
    minLength: 10,
    maxLength: 500,
    templates: [
      {
        value: "override_engine_error",
        label: "Engine xét tuyển sai do dữ liệu đầu vào lỗi",
      },
      {
        value: "override_admin_discretion",
        label: "Quyết định riêng của ban tuyển sinh",
      },
    ],
  },
  admin_rollback: {
    title: "Quay lại trạng thái nháp",
    description:
      "Đưa hồ sơ về trạng thái nháp để xử lý lại từ đầu. Ghi audit log đầy đủ.",
    minLength: 10,
    maxLength: 500,
    templates: [
      {
        value: "rollback_data_error",
        label: "Phát hiện sai dữ liệu cần sửa",
      },
      {
        value: "rollback_candidate_request",
        label: "Thí sinh yêu cầu rút và nộp lại",
      },
      {
        value: "rollback_system_test",
        label: "Test hệ thống / migration verification",
      },
    ],
  },
  request_revision: {
    title: "Yêu cầu sửa hồ sơ",
    description:
      "Hồ sơ chuyển về trạng thái cần sửa; thí sinh/cán bộ nhận thông báo kèm lý do để bổ sung hoặc chỉnh sửa.",
    minLength: 10,
    maxLength: 1000,
    templates: [
      { value: "revision_docs_missing", label: "Thiếu/sai giấy tờ cần bổ sung" },
      { value: "revision_info_mismatch", label: "Thông tin cá nhân chưa khớp giấy tờ" },
      { value: "revision_scores", label: "Điểm/học lực cần kiểm tra lại" },
    ],
  },
}

/** localStorage key for recent reason autocomplete (per-action partitioned). */
export function getRecentReasonsKey(action: AuditAction): string {
  return `qlts:audit-recent-reasons:${action}`
}

/** Read recent reasons from localStorage (most-recent-first, max 5). */
export function loadRecentReasons(action: AuditAction): string[] {
  if (typeof window === "undefined") return []
  try {
    const raw = window.localStorage.getItem(getRecentReasonsKey(action))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed)
      ? parsed.filter((s): s is string => typeof s === "string").slice(0, 5)
      : []
  } catch {
    return []
  }
}

/** Push a reason to recent list (dedupe + truncate to 5). */
export function pushRecentReason(action: AuditAction, reason: string): void {
  if (typeof window === "undefined") return
  const trimmed = reason.trim()
  if (!trimmed) return
  try {
    const current = loadRecentReasons(action)
    const next = [trimmed, ...current.filter((r) => r !== trimmed)].slice(0, 5)
    window.localStorage.setItem(
      getRecentReasonsKey(action),
      JSON.stringify(next),
    )
  } catch {
    // localStorage may be unavailable (private mode, quota); silently ignore.
  }
}
