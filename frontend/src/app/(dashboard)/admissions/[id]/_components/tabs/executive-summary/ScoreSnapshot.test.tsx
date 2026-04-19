// src/app/(dashboard)/admissions/[id]/_components/tabs/executive-summary/ScoreSnapshot.test.tsx
/**
 * ScoreSnapshot — weighted scoring display tests (PR6 Step 3).
 *
 * Contract:
 *   - `applied_rules.scoring_method === "weighted"` AND
 *     `applied_rules.subject_weights` is non-empty
 *       → breakdown table shows 5 columns
 *         (Môn học | Điểm | Hệ số | Điểm sau nhân | Trạng thái)
 *   - Missing subject code in weights map → fallback weight 1.0
 *   - Anything else (sum / average / pre-migration snapshot)
 *       → legacy 3-column layout preserved
 *   - `total_score` is always rendered from profile.total_score
 *     (thin-client; FE never recomputes).
 */

import { describe, it, expect } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"

import { ScoreSnapshot } from "./ScoreSnapshot"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type Profile = Parameters<typeof ScoreSnapshot>[0]["profile"]

function buildProfile(overrides: Partial<Record<string, unknown>> = {}): Profile {
  const base = {
    id: 1,
    status: "submitted",
    version: 1,
    total_score: 32,
    admission_scores: {
      subject_scores: { math: 8, physics: 7, chemistry: 9 },
      selected_group: "A00",
    },
    applied_rules: {
      method_type: "subject_based",
      scoring_method: "weighted",
      subject_weights: { math: 2, physics: 1, chemistry: 1 },
    },
    score_snapshot_status: {
      total_status: "passing",
      subject_statuses: { math: "passing", physics: "passing", chemistry: "passing" },
      min_score: 18,
      min_subject_score: 1,
    },
  }
  return { ...base, ...overrides } as unknown as Profile
}

function openCollapsible() {
  // Trigger is the only button when the panel is first rendered.
  const trigger = screen.getByRole("button", { name: /snapshot điểm chuẩn/i })
  fireEvent.click(trigger)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ScoreSnapshot — weighted breakdown (PR6 Step 3)", () => {
  it("shows Hệ số + Điểm sau nhân columns when scoring_method=weighted and weights are present", () => {
    render(<ScoreSnapshot profile={buildProfile()} />)
    openCollapsible()

    // 5-column header
    expect(screen.getByRole("columnheader", { name: "Môn học" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "Điểm" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "Hệ số" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "Điểm sau nhân" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "Trạng thái" })).toBeInTheDocument()

    // math: 8 × 2 = 16
    expect(screen.getByText("×2")).toBeInTheDocument()
    expect(screen.getByText("16.00")).toBeInTheDocument()

    // physics: 7 × 1 = 7 ; chemistry: 9 × 1 = 9 — two ×1 cells, one 7.00, one 9.00
    expect(screen.getAllByText("×1").length).toBe(2)
    expect(screen.getByText("7.00")).toBeInTheDocument()
    expect(screen.getByText("9.00")).toBeInTheDocument()

    // Total row uses backend-computed total_score (thin client)
    expect(screen.getByText("32.00")).toBeInTheDocument()
    expect(screen.getByText(/đã áp hệ số/i)).toBeInTheDocument()
  })

  it("falls back to weight=1.0 when a subject is missing from subject_weights", () => {
    const profile = buildProfile({
      applied_rules: {
        method_type: "subject_based",
        scoring_method: "weighted",
        // physics + chemistry missing — must render as ×1 per contract
        subject_weights: { math: 2 },
      },
    })

    render(<ScoreSnapshot profile={profile} />)
    openCollapsible()

    // math row: explicit ×2
    expect(screen.getByText("×2")).toBeInTheDocument()
    // physics + chemistry: fallback to ×1
    expect(screen.getAllByText("×1").length).toBe(2)
    // weighted scores: 8×2=16, 7×1=7, 9×1=9
    expect(screen.getByText("16.00")).toBeInTheDocument()
    expect(screen.getByText("7.00")).toBeInTheDocument()
    expect(screen.getByText("9.00")).toBeInTheDocument()
  })

  it("keeps legacy 3-column layout when scoring_method=sum", () => {
    const profile = buildProfile({
      applied_rules: {
        method_type: "subject_based",
        scoring_method: "sum",
        // Even if weights exist, sum method must NOT show them —
        // matches the backend contract that sum ignores weights.
        subject_weights: { math: 2, physics: 1, chemistry: 1 },
      },
      total_score: 24,
    })

    render(<ScoreSnapshot profile={profile} />)
    openCollapsible()

    // No weight columns
    expect(screen.queryByRole("columnheader", { name: "Hệ số" })).not.toBeInTheDocument()
    expect(
      screen.queryByRole("columnheader", { name: "Điểm sau nhân" }),
    ).not.toBeInTheDocument()
    expect(screen.queryByText("×2")).not.toBeInTheDocument()

    // Plain total shown
    expect(screen.getByText("24.00")).toBeInTheDocument()
  })

  it("keeps legacy layout for pre-migration snapshots (no subject_weights field)", () => {
    const profile = buildProfile({
      applied_rules: {
        method_type: "subject_based",
        scoring_method: "weighted", // method says weighted, but no weights frozen
        // subject_weights intentionally omitted — pre-PR6 snapshot shape
      },
    })

    render(<ScoreSnapshot profile={profile} />)
    openCollapsible()

    // Degrade gracefully — no weight columns, no-op layout.
    expect(screen.queryByRole("columnheader", { name: "Hệ số" })).not.toBeInTheDocument()
    expect(screen.queryByText("×1")).not.toBeInTheDocument()
  })

  it("still renders GPA-only message without touching weights", () => {
    const profile = buildProfile({
      applied_rules: { method_type: "gpa_only" },
    })

    render(<ScoreSnapshot profile={profile} />)
    openCollapsible()

    expect(
      screen.getByText(/chỉ xét học bạ \(gpa\)/i),
    ).toBeInTheDocument()
  })
})
