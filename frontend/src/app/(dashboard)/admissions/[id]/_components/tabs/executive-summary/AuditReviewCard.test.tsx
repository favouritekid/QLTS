/**
 * AuditReviewCard — anchor tests (Commit 8 followup).
 *
 * Pin: priority_audit_log slice last 3 + entry shape (action_type/
 * actor_name/actor_id/created_at) + empty fallback.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import type { AdmissionProfileResponse, PriorityAuditEntry } from "@/lib/zod/admissions"

import { AuditReviewCard } from "./AuditReviewCard"

function buildEntry(overrides: Partial<PriorityAuditEntry> = {}): PriorityAuditEntry {
  // Use 'actor_name' in overrides để phân biệt "explicit null" vs "not provided".
  // `??` chỉ fallback khi `undefined`, không phải null.
  return {
    id: overrides.id ?? 1,
    action_type: overrides.action_type ?? "kv_manual_override",
    actor_id: "actor_id" in overrides ? overrides.actor_id! : 15,
    actor_name: "actor_name" in overrides ? overrides.actor_name! : "Phạm Thái Hà",
    old_value: null,
    new_value: null,
    audit_metadata: null,
    created_at: overrides.created_at ?? "2026-05-20T15:19:00+00:00",
  }
}

function buildProfile(log: PriorityAuditEntry[]): AdmissionProfileResponse {
  return {
    id: 1,
    status: "submitted",
    version: 1,
    academic_year: 2026,
    permissions: {},
    eligibility_status: "eligible",
    validation_errors: [],
    available_actions: [],
    completion_percent: 100,
    applied_rules: {},
    family_info: [],
    academic_history: [],
    documents_checklist: [],
    missing_priority_evidence_codes: [],
    priority_resolution_snapshot: {},
    priority_audit_log: log,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as AdmissionProfileResponse
}

describe("AuditReviewCard", () => {
  it("Empty log: hiển thị 'Chưa có thao tác audit' italic", () => {
    render(<AuditReviewCard profile={buildProfile([])} />)
    expect(screen.getByText("Chưa có thao tác audit.")).toBeInTheDocument()
  })

  it("Render đúng số entries từ priority_audit_log (max 3 last)", () => {
    const log = [
      buildEntry({ id: 1, action_type: "ut_evidence_verified" }),
      buildEntry({ id: 2, action_type: "ut_evidence_rejected" }),
      buildEntry({ id: 3, action_type: "kv_manual_override" }),
      buildEntry({ id: 4, action_type: "ut_evidence_warning_dismissed" }),
      buildEntry({ id: 5, action_type: "ut_evidence_verified" }),
    ]
    render(<AuditReviewCard profile={buildProfile(log)} />)
    // last 3 = id 3, 4, 5 (reversed = 5, 4, 3)
    const card = screen.getByTestId("audit-review-card")
    const items = card.querySelectorAll("li")
    expect(items).toHaveLength(3)
    // First displayed should be id=5 (newest, reverse of slice -3)
    expect(items[0].textContent).toContain("ut_evidence_verified")
  })

  it("Hiển thị actor_name khi có, fallback '#actorId' nếu chỉ có id", () => {
    const log = [
      buildEntry({ id: 1, actor_id: 15, actor_name: "Phạm Thái Hà" }),
      buildEntry({ id: 2, actor_id: 42, actor_name: null }),
    ]
    render(<AuditReviewCard profile={buildProfile(log)} />)
    expect(screen.getByText("Phạm Thái Hà")).toBeInTheDocument()
    // Fallback "#42" khi actor_name=null + actor_id=42
    expect(screen.getByText("#42")).toBeInTheDocument()
  })

  it("Hiển thị created_at qua locale 'vi-VN'", () => {
    const log = [
      buildEntry({ created_at: "2026-05-20T15:19:00+00:00" }),
    ]
    render(<AuditReviewCard profile={buildProfile(log)} />)
    // Vietnamese date format e.g. "20/5/2026"
    expect(screen.getByText(/20\/5\/2026|21\/5\/2026/)).toBeInTheDocument()
  })

  it("Hiển thị summary footer 'Xem đầy đủ ở N thao tác'", () => {
    const log = [buildEntry({ id: 1 }), buildEntry({ id: 2 })]
    render(<AuditReviewCard profile={buildProfile(log)} />)
    expect(screen.getByText(/Xem đầy đủ ở 2 thao tác/)).toBeInTheDocument()
  })
})
