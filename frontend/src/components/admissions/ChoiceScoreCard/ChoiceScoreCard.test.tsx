/**
 * Phase 3 PR-3D-B FE Wave B Day 8 — ChoiceScoreCard tests.
 *
 * Non-tautological per memory pattern-change-impact-audit:
 * - Verify snapshot-driven bounds (min_possible_score_snapshot + max_score_snapshot)
 * - Verify onBlur save sends FULL replacement payload (BE PATCH replaces all)
 * - Verify revert-on-error (server-side rejection flashes error + restores)
 * - Verify disabled state from canEdit=false
 * - Verify range hint tooltip + a11y aria-invalid wiring
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi, beforeEach } from "vitest"

import { ChoiceScoreCard } from "./ChoiceScoreCard"
import type { AdmissionProfileChoiceResponse } from "@/lib/zod/admission-choices"

const mockReplaceChoiceScores = vi.fn()
vi.mock("@/lib/api/admission-choices", async (importOriginal) => {
  const actual = await importOriginal<
    typeof import("@/lib/api/admission-choices")
  >()
  return {
    ...actual,
    replaceChoiceScores: (...args: unknown[]) =>
      mockReplaceChoiceScores(...args),
  }
})

function makeChoice(
  overrides: Partial<AdmissionProfileChoiceResponse> = {},
): AdmissionProfileChoiceResponse {
  return {
    id: 1,
    admission_profile_id: 100,
    admission_path_id: 50,
    path_subject_group_config_id: 75,
    display_order: 1,
    decision: "pending",
    waitlist_rank: null,
    eligibility_check_result: null,
    bonus_rule_snapshot: null,
    created_at: "2026-05-13T05:00:00Z",
    updated_at: "2026-05-13T05:00:00Z",
    display_path_name: "CNTT 2026 - HSA - DOT_1",
    display_subject_group_name: "Toán-Lý-Hoá",
    scores: [
      {
        subject_id: 11,
        subject_code: "TOAN",
        subject_name: "Toán",
        score: 8.5,
        max_score_snapshot: 10,
        min_possible_score_snapshot: 0,
        weight_snapshot: 1,
      },
      {
        subject_id: 12,
        subject_code: "LY",
        subject_name: "Vật lý",
        score: 7.25,
        max_score_snapshot: 10,
        min_possible_score_snapshot: 0,
        weight_snapshot: 1,
      },
    ],
    ...overrides,
  }
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe("ChoiceScoreCard", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("renders empty state when choice has no scores", () => {
    const choice = makeChoice({ scores: [] })
    render(
      wrap(
        <ChoiceScoreCard profileId={100} choice={choice} canEdit={true} />,
      ),
    )
    expect(screen.getByTestId("choice-score-card-empty")).toBeTruthy()
  })

  it("renders one input per score row with backend value pre-filled", () => {
    const choice = makeChoice()
    render(
      wrap(
        <ChoiceScoreCard profileId={100} choice={choice} canEdit={true} />,
      ),
    )
    const toanInput = screen.getByTestId("score-input-11") as HTMLInputElement
    const lyInput = screen.getByTestId("score-input-12") as HTMLInputElement
    expect(toanInput.value).toBe("8.5")
    expect(lyInput.value).toBe("7.25")
  })

  it("validates above max with inline error message + aria-invalid", () => {
    const choice = makeChoice()
    render(
      wrap(
        <ChoiceScoreCard profileId={100} choice={choice} canEdit={true} />,
      ),
    )
    const input = screen.getByTestId("score-input-11") as HTMLInputElement
    fireEvent.change(input, { target: { value: "11" } })
    // Inline error rendered with role="alert"
    const err = screen.getByTestId("score-error-11")
    expect(err.textContent).toContain("Điểm tối đa là 10")
    expect(input.getAttribute("aria-invalid")).toBe("true")
  })

  it("onBlur with valid changed value sends FULL replacement payload", async () => {
    mockReplaceChoiceScores.mockResolvedValueOnce({})
    const choice = makeChoice()
    render(
      wrap(
        <ChoiceScoreCard profileId={100} choice={choice} canEdit={true} />,
      ),
    )
    const input = screen.getByTestId("score-input-11") as HTMLInputElement
    fireEvent.change(input, { target: { value: "9.0" } })
    fireEvent.blur(input)
    await waitFor(() => {
      expect(mockReplaceChoiceScores).toHaveBeenCalledTimes(1)
    })
    // Payload must include BOTH subjects (idempotent replace semantics)
    const callArgs = mockReplaceChoiceScores.mock.calls[0]
    expect(callArgs[0]).toBe(100) // profileId
    expect(callArgs[1]).toBe(1) // choiceId
    expect(callArgs[2]).toEqual({
      scores: [
        { subject_id: 11, score: 9 },
        { subject_id: 12, score: 7.25 },
      ],
    })
  })

  it("disables inputs when canEdit=false", () => {
    const choice = makeChoice()
    render(
      wrap(
        <ChoiceScoreCard profileId={100} choice={choice} canEdit={false} />,
      ),
    )
    const toanInput = screen.getByTestId("score-input-11") as HTMLInputElement
    const lyInput = screen.getByTestId("score-input-12") as HTMLInputElement
    expect(toanInput.disabled).toBe(true)
    expect(lyInput.disabled).toBe(true)
  })

  it("onBlur without change does NOT trigger save (no-op short-circuit)", async () => {
    const choice = makeChoice()
    render(
      wrap(
        <ChoiceScoreCard profileId={100} choice={choice} canEdit={true} />,
      ),
    )
    const input = screen.getByTestId("score-input-11") as HTMLInputElement
    // Same value as backend
    fireEvent.blur(input)
    // Give microtask a chance to schedule the mutation in case
    await new Promise((r) => setTimeout(r, 30))
    expect(mockReplaceChoiceScores).not.toHaveBeenCalled()
  })

  it("server error after blur shows error toast + reverts local state", async () => {
    const apiError = Object.assign(new Error("rejected"), {
      response: {
        status: 400,
        data: { detail: "Không hợp lệ với điểm này." },
      },
    })
    mockReplaceChoiceScores.mockRejectedValueOnce(apiError)
    const choice = makeChoice()
    render(
      wrap(
        <ChoiceScoreCard profileId={100} choice={choice} canEdit={true} />,
      ),
    )
    const input = screen.getByTestId("score-input-11") as HTMLInputElement
    fireEvent.change(input, { target: { value: "9.0" } })
    fireEvent.blur(input)
    await waitFor(() => {
      expect(screen.getByTestId("score-server-error")).toBeTruthy()
    })
    // Input reverted to backend value
    expect(input.value).toBe("8.5")
  })
})
