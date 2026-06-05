/**
 * AuditReviewCard — one-line latest-event tests.
 *
 * Pin: latest entry (last element) only, with a TRANSLATED label (never the raw
 * action_type enum), actor + date; empty fallback.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import type { AdmissionProfileResponse, PriorityAuditEntry } from "@/lib/zod/admissions"

import { AuditReviewCard } from "./AuditReviewCard"

function buildEntry(overrides: Partial<PriorityAuditEntry> = {}): PriorityAuditEntry {
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

describe("AuditReviewCard — one-line", () => {
  it("empty log: 'chưa có thao tác' fallback", () => {
    render(<AuditReviewCard profile={buildProfile([])} />)
    expect(screen.getByText(/chưa có thao tác/i)).toBeInTheDocument()
  })

  it("translates action_type to a label (never raw enum)", () => {
    render(<AuditReviewCard profile={buildProfile([buildEntry({ action_type: "kv_manual_override" })])} />)
    const card = screen.getByTestId("audit-review-card")
    expect(screen.getByText("Ấn định KV")).toBeInTheDocument()
    expect(card.textContent).not.toContain("kv_manual_override")
    expect(card.textContent).toContain("Phạm Thái Hà")
  })

  it("shows the NEWEST entry only — BE returns DESC, so newest is the FIRST element", () => {
    // Mirror the backend contract: priority_audit_log is ordered created_at DESC
    // (admission_service.py:2824), i.e. element [0] is the most recent event.
    const log = [
      buildEntry({ id: 2, action_type: "kv_manual_override" }), // newest (index 0)
      buildEntry({ id: 1, action_type: "ut_evidence_verified" }), // older
    ]
    render(<AuditReviewCard profile={buildProfile(log)} />)
    const card = screen.getByTestId("audit-review-card")
    expect(card.textContent).toContain("Ấn định KV")
    expect(card.textContent).not.toContain("Duyệt minh chứng UT")
  })

  it("maps the live ut_evidence_untick event to a specific label (not the generic fallback)", () => {
    render(<AuditReviewCard profile={buildProfile([buildEntry({ action_type: "ut_evidence_untick" })])} />)
    const card = screen.getByTestId("audit-review-card")
    expect(screen.getByText("Bỏ minh chứng UT")).toBeInTheDocument()
    expect(card.textContent).not.toContain("Cập nhật hồ sơ ưu tiên")
  })

  it("maps ut_evidence_warning_dismissed to a specific label", () => {
    render(<AuditReviewCard profile={buildProfile([buildEntry({ action_type: "ut_evidence_warning_dismissed" })])} />)
    expect(screen.getByText("Bỏ qua cảnh báo thiếu UT")).toBeInTheDocument()
  })

  it("unknown action_type → generic label, no raw enum", () => {
    render(<AuditReviewCard profile={buildProfile([buildEntry({ action_type: "some_new_action" })])} />)
    const card = screen.getByTestId("audit-review-card")
    expect(screen.getByText("Cập nhật hồ sơ ưu tiên")).toBeInTheDocument()
    expect(card.textContent).not.toContain("some_new_action")
  })

  it("actor_name null → '#actorId' fallback", () => {
    render(<AuditReviewCard profile={buildProfile([buildEntry({ actor_id: 42, actor_name: null })])} />)
    expect(screen.getByTestId("audit-review-card").textContent).toContain("#42")
  })
})
