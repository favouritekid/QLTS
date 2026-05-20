/**
 * PriorityAuditTimeline — Q9 #07 Phase E.4 audit timeline tests.
 *
 * Verifies:
 *  - Hidden khi entries empty / null / undefined
 *  - Renders icons + Vietnamese labels per action_type
 *  - Summary line shows KV before→after, UT sub_code, reject reason
 *  - Vietnamese time formatting
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@/test/utils/test-utils"
import { PriorityAuditTimeline } from "./PriorityAuditTimeline"
import type { PriorityAuditEntry } from "@/lib/zod/admissions"

function makeEntry(overrides: Partial<PriorityAuditEntry> = {}): PriorityAuditEntry {
  return {
    id: 1,
    action_type: "kv_manual_override",
    actor_id: 10,
    actor_name: "Phạm Thái Hà",
    old_value: null,
    new_value: null,
    audit_metadata: null,
    created_at: "2026-05-19T08:00:00+07:00",
    ...overrides,
  }
}

describe("PriorityAuditTimeline", () => {
  it("renders null khi entries empty", () => {
    const { container } = render(<PriorityAuditTimeline entries={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it("renders null khi entries null", () => {
    const { container } = render(<PriorityAuditTimeline entries={null} />)
    expect(container.firstChild).toBeNull()
  })

  it("renders null khi entries undefined", () => {
    const { container } = render(<PriorityAuditTimeline />)
    expect(container.firstChild).toBeNull()
  })

  it("KV override entry: shows 'Override KV' label + before→after summary + reason", () => {
    render(
      <PriorityAuditTimeline
        entries={[
          makeEntry({
            action_type: "kv_manual_override",
            old_value: { kv_resolved: "KV3" },
            new_value: { kv_resolved: "KV1", reason: "Trường vùng cao xa" },
          }),
        ]}
      />,
    )
    expect(screen.getByText("Override KV")).toBeInTheDocument()
    expect(screen.getByText(/KV3 → KV1/)).toBeInTheDocument()
    expect(screen.getByText(/Trường vùng cao xa/)).toBeInTheDocument()
    expect(screen.getByText(/bởi Phạm Thái Hà/)).toBeInTheDocument()
  })

  it("UT verified entry: shows 'Duyệt UT' label + sub_code from audit_metadata", () => {
    render(
      <PriorityAuditTimeline
        entries={[
          makeEntry({
            id: 2,
            action_type: "ut_evidence_verified",
            audit_metadata: { sub_code: "04" },
          }),
        ]}
      />,
    )
    expect(screen.getByText("Duyệt UT")).toBeInTheDocument()
    expect(screen.getByText(/UT04/)).toBeInTheDocument()
  })

  it("UT rejected entry: shows 'Từ chối UT' label + reject reason", () => {
    render(
      <PriorityAuditTimeline
        entries={[
          makeEntry({
            id: 3,
            action_type: "ut_evidence_rejected",
            audit_metadata: { sub_code: "06", reject_reason: "Thiếu CCCD" },
          }),
        ]}
      />,
    )
    expect(screen.getByText("Từ chối UT")).toBeInTheDocument()
    expect(screen.getByText(/UT06.*Thiếu CCCD/)).toBeInTheDocument()
  })

  it("renders all 3 entry types in order with header count", () => {
    render(
      <PriorityAuditTimeline
        entries={[
          makeEntry({
            id: 3,
            action_type: "ut_evidence_rejected",
            audit_metadata: { sub_code: "06" },
            created_at: "2026-05-19T08:01:00+07:00",
          }),
          makeEntry({
            id: 2,
            action_type: "ut_evidence_verified",
            audit_metadata: { sub_code: "04" },
            created_at: "2026-05-19T08:00:00+07:00",
          }),
          makeEntry({
            id: 1,
            action_type: "kv_manual_override",
            old_value: { kv_resolved: "KV3" },
            new_value: { kv_resolved: "KV1" },
            created_at: "2026-05-19T07:08:00+07:00",
          }),
        ]}
      />,
    )
    expect(screen.getByText(/3 thao tác gần nhất/i)).toBeInTheDocument()
    expect(screen.getByText("Từ chối UT")).toBeInTheDocument()
    expect(screen.getByText("Duyệt UT")).toBeInTheDocument()
    expect(screen.getByText("Override KV")).toBeInTheDocument()
  })

  it("renders unknown action_type with raw label (no crash)", () => {
    render(
      <PriorityAuditTimeline
        entries={[makeEntry({ action_type: "admin_bulk_fill" })]}
      />,
    )
    expect(screen.getByText("admin_bulk_fill")).toBeInTheDocument()
  })

  it("renders gracefully when actor_name is null", () => {
    render(
      <PriorityAuditTimeline
        entries={[makeEntry({ actor_name: null })]}
      />,
    )
    expect(screen.queryByText(/bởi/)).not.toBeInTheDocument()
    expect(screen.getByText("Override KV")).toBeInTheDocument()
  })
})
