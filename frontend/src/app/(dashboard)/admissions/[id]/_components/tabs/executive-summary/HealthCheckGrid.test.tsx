/**
 * HealthCheckGrid — Commit 4 cockpit composition test.
 *
 * Pin: 8 cards mount theo thứ tự (Legal, Academic, Priority, Score,
 * Document, Fee, Admin, Audit). Anti-regression nếu refactor sau làm
 * mất card.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

// Mock heavy sub-components — chỉ cần testid để verify composition.
vi.mock("./LegalDocsCard", () => ({ LegalDocsCard: () => <div data-testid="legal-docs-card" /> }))
vi.mock("./AcademicCard", () => ({ AcademicCard: () => <div data-testid="academic-card" /> }))
vi.mock("./AdminCard", () => ({ AdminCard: () => <div data-testid="admin-card" /> }))
vi.mock("./PriorityReviewCard", () => ({ PriorityReviewCard: () => <div data-testid="priority-review-card" /> }))
vi.mock("./ScoreReviewCard", () => ({ ScoreReviewCard: () => <div data-testid="score-review-card" /> }))
vi.mock("./DocumentReviewCard", () => ({ DocumentReviewCard: () => <div data-testid="document-review-card" /> }))
vi.mock("./FeeReviewCard", () => ({ FeeReviewCard: () => <div data-testid="fee-review-card" /> }))
vi.mock("./AuditReviewCard", () => ({ AuditReviewCard: () => <div data-testid="audit-review-card" /> }))

import { HealthCheckGrid } from "./HealthCheckGrid"

function buildProfile(): AdmissionProfileResponse {
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
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as AdmissionProfileResponse
}

describe("HealthCheckGrid — Commit 4 cockpit composition", () => {
  it("renders all 8 review cards", () => {
    render(<HealthCheckGrid profile={buildProfile()} />)
    expect(screen.getByTestId("health-check-grid")).toBeInTheDocument()
    expect(screen.getByTestId("legal-docs-card")).toBeInTheDocument()
    expect(screen.getByTestId("academic-card")).toBeInTheDocument()
    expect(screen.getByTestId("priority-review-card")).toBeInTheDocument()
    expect(screen.getByTestId("score-review-card")).toBeInTheDocument()
    expect(screen.getByTestId("document-review-card")).toBeInTheDocument()
    expect(screen.getByTestId("fee-review-card")).toBeInTheDocument()
    expect(screen.getByTestId("admin-card")).toBeInTheDocument()
    expect(screen.getByTestId("audit-review-card")).toBeInTheDocument()
  })
})
