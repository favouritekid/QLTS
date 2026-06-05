/**
 * AuditReviewCard — latest decision/priority audit event, ONE line.
 *
 * Reviewer cockpit only needs "what happened last" at a glance, with a
 * translated label (never the raw `action_type` enum). Full timeline lives in
 * the priority panel / InspectionDetails. Reads profile.priority_audit_log
 * which the BE returns NEWEST-FIRST (admission_service.py:2824 — order_by
 * created_at.desc()), so the latest event is element [0].
 */

"use client"

import { History } from "lucide-react"
import type { AdmissionProfileResponse, PriorityAuditEntry } from "@/lib/zod/admissions"

interface AuditReviewCardProps {
  profile: AdmissionProfileResponse
}

/**
 * Translate the audit action_type → a Vietnamese label (never render the raw enum).
 * Covers ALL 6 values the backend CHECK constraint allows
 * (Backend_FastAPI/app/models/priority_audit.py:58-69) so live events like
 * `ut_evidence_untick` / `ut_evidence_warning_dismissed` are not masked by a
 * generic fallback.
 */
function auditActionLabel(actionType: string): string {
  switch (actionType) {
    case "kv_manual_override":
      return "Ấn định KV"
    case "ut_evidence_verified":
      return "Duyệt minh chứng UT"
    case "ut_evidence_rejected":
      return "Từ chối minh chứng UT"
    case "ut_evidence_untick":
      return "Bỏ minh chứng UT"
    case "ut_evidence_warning_dismissed":
      return "Bỏ qua cảnh báo thiếu UT"
    case "admin_bulk_fill":
      return "Admin điền hồ sơ hàng loạt"
    default:
      return "Cập nhật hồ sơ ưu tiên"
  }
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("vi-VN")
  } catch {
    return iso
  }
}

export function AuditReviewCard({ profile }: AuditReviewCardProps) {
  const log = profile.priority_audit_log ?? []
  // BE returns DESC (newest first) — the latest event is the FIRST element.
  const latest: PriorityAuditEntry | null = log.length > 0 ? log[0] : null

  if (!latest) {
    return (
      <p data-testid="audit-review-card" className="text-xs text-muted-foreground">
        Gần đây: chưa có thao tác duyệt/ưu tiên.
      </p>
    )
  }

  const actor = latest.actor_name ?? (latest.actor_id != null ? `#${latest.actor_id}` : null)

  return (
    <p
      data-testid="audit-review-card"
      className="flex items-center gap-1.5 text-xs text-muted-foreground"
    >
      <History className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span className="min-w-0 break-words">
        Gần đây:{" "}
        <span className="font-medium text-foreground">{auditActionLabel(latest.action_type)}</span>
        {actor ? ` bởi ${actor}` : ""} · {formatDate(latest.created_at)}
      </span>
    </p>
  )
}
