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

  it("renders only backend-selected subjects on best_n snapshots (ignored subjects hidden)", () => {
    // Applicant submitted 4 subjects. Backend `best_n` mode picked the
    // 3 highest (math 9, literature 8, english 7) and chose NOT to use
    // physics 6. Backend total_score = 9×2 + 8×1 + 7×1 = 33.
    // If we render all 4 rows we'd explain the total as 33 + 6×1 = 39,
    // which is a lie. Filter to selected_subjects.
    const profile = buildProfile({
      total_score: 33,
      admission_scores: {
        subject_scores: {
          math: 9,
          literature: 8,
          english: 7,
          physics: 6, // submitted but NOT selected
        },
        selected_group: "D01",
      },
      applied_rules: {
        method_type: "subject_based",
        scoring_method: "weighted",
        subject_weights: {
          math: 2,
          literature: 1,
          english: 1,
          physics: 1,
        },
      },
      snapshot_score: {
        selected_subjects: ["math", "literature", "english"],
      },
      score_snapshot_status: {
        total_status: "passing",
        subject_statuses: {
          math: "passing",
          literature: "passing",
          english: "passing",
        },
        min_score: 18,
        min_subject_score: 1,
      },
    })

    render(<ScoreSnapshot profile={profile} />)
    openCollapsible()

    // Selected subjects show with weighted values
    expect(screen.getByText("×2")).toBeInTheDocument() // math
    expect(screen.getByText("18.00")).toBeInTheDocument() // 9 × 2
    expect(screen.getByText("8.00")).toBeInTheDocument() // 8 × 1
    expect(screen.getByText("7.00")).toBeInTheDocument() // 7 × 1

    // Physics (ignored) must not appear — would otherwise show 6.00 as
    // its weighted cell and break the explanation.
    expect(screen.queryByText("6.00")).not.toBeInTheDocument()

    // Backend total still source of truth
    expect(screen.getByText("33.00")).toBeInTheDocument()
  })

  it("falls back to subject_statuses keys when selected_subjects is absent", () => {
    // Pre-snapshot_score back-compat path: only subject_statuses tells
    // us which subjects the backend actually scored. `best_n` paths that
    // predate the explicit `selected_subjects` field still need to
    // filter — otherwise ignored subjects creep into the breakdown.
    const profile = buildProfile({
      total_score: 33,
      admission_scores: {
        subject_scores: {
          math: 9,
          literature: 8,
          english: 7,
          physics: 6, // not in subject_statuses below → ignored
        },
        selected_group: "D01",
      },
      applied_rules: {
        method_type: "subject_based",
        scoring_method: "weighted",
        subject_weights: { math: 2, literature: 1, english: 1, physics: 1 },
      },
      // snapshot_score intentionally omitted
      score_snapshot_status: {
        total_status: "passing",
        subject_statuses: {
          math: "passing",
          literature: "passing",
          english: "passing",
        },
        min_score: 18,
        min_subject_score: 1,
      },
    })

    render(<ScoreSnapshot profile={profile} />)
    openCollapsible()

    expect(screen.queryByText("6.00")).not.toBeInTheDocument()
    expect(screen.getByText("18.00")).toBeInTheDocument() // math × 2
    expect(screen.getByText("33.00")).toBeInTheDocument()
  })

  it("keeps legacy layout filtering on sum method with best_n snapshots (no weight columns)", () => {
    // Defense in depth: even when `selected_subjects` is present, the
    // legacy 3-column layout must still respect it so the displayed
    // rows are consistent with total_score, regardless of weights.
    const profile = buildProfile({
      total_score: 24,
      admission_scores: {
        subject_scores: {
          math: 8,
          literature: 7,
          english: 9,
          physics: 6, // ignored
        },
        selected_group: "D01",
      },
      applied_rules: {
        method_type: "subject_based",
        scoring_method: "sum",
      },
      snapshot_score: {
        selected_subjects: ["math", "literature", "english"],
      },
      score_snapshot_status: {
        total_status: "passing",
        subject_statuses: {
          math: "passing",
          literature: "passing",
          english: "passing",
        },
        min_score: 18,
        min_subject_score: 1,
      },
    })

    render(<ScoreSnapshot profile={profile} />)
    openCollapsible()

    // No weight columns
    expect(screen.queryByRole("columnheader", { name: "Hệ số" })).not.toBeInTheDocument()
    // Ignored subject hidden
    expect(screen.queryByText("6.0")).not.toBeInTheDocument()
    // Total still backend
    expect(screen.getByText("24.00")).toBeInTheDocument()
  })
})
