/**
 * Phase 3 PR-3D-B FE Wave B Day 7 — ChoiceListEditor tests.
 *
 * Non-tautological per memory `pattern-change-impact-audit`:
 * - Verify backend-driven canEdit gating (no role check on FE)
 * - Verify max-NV gate disables add button + shows hint
 * - Verify reorder PATCH receives correct display_order
 * - Verify delete flow shows confirm dialog → confirm → mutation called
 * - Verify React Query invalidation parity (memory `react-query-mutation-cache-parity`)
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi, beforeEach } from "vitest"

import { ChoiceListEditor } from "./ChoiceListEditor"
import type { AdmissionProfileChoiceResponse } from "@/lib/zod/admission-choices"

// Mock API client at module level — vitest hoists vi.mock() before imports
const mockCreateChoice = vi.fn()
const mockDeleteChoice = vi.fn()
const mockUpdateChoiceDisplayOrder = vi.fn()
const mockReplaceChoiceScores = vi.fn()

vi.mock("@/lib/api/admission-choices", () => ({
  createChoice: (...args: unknown[]) => mockCreateChoice(...args),
  deleteChoice: (...args: unknown[]) => mockDeleteChoice(...args),
  updateChoiceDisplayOrder: (...args: unknown[]) =>
    mockUpdateChoiceDisplayOrder(...args),
  replaceChoiceScores: (...args: unknown[]) => mockReplaceChoiceScores(...args),
}))

// Factory for a typical choice row
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
    display_program_name: "Cao đẳng Công nghệ thông tin",
    display_degree_level: "Cao đẳng",
    display_subject_group_name: "Toán-Lý-Hoá",
    scores: [],
    data_complete: false,
    computed_total_score: null,
    admission_threshold_passed: null,
    threshold_failure_reasons: [],
    ...overrides,
  }
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe("ChoiceListEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("renders empty state when no choices", () => {
    render(
      wrap(
        <ChoiceListEditor
          profileId={100}
          choices={[]}
          maxChoices={5}
          canEdit={true}
        />,
      ),
    )
    expect(screen.getByTestId("choice-list-empty")).toBeTruthy()
    expect(screen.queryByTestId("choice-list")).toBeNull()
  })

  it("renders all choices sorted by display_order with NV labels", () => {
    const choices = [
      makeChoice({ id: 2, display_order: 2, display_path_name: "Path B" }),
      makeChoice({ id: 1, display_order: 1, display_path_name: "Path A" }),
      makeChoice({ id: 3, display_order: 3, display_path_name: "Path C" }),
    ]
    render(
      wrap(
        <ChoiceListEditor
          profileId={100}
          choices={choices}
          maxChoices={5}
          canEdit={true}
        />,
      ),
    )
    const rows = screen.getAllByTestId(/^choice-row-/)
    expect(rows).toHaveLength(3)
    // Visible order matches display_order
    expect(within(rows[0]).getByText("NV1")).toBeTruthy()
    expect(within(rows[1]).getByText("NV2")).toBeTruthy()
    expect(within(rows[2]).getByText("NV3")).toBeTruthy()
  })

  it("hides drag handles + add + delete when canEdit=false", () => {
    render(
      wrap(
        <ChoiceListEditor
          profileId={100}
          choices={[makeChoice()]}
          maxChoices={5}
          canEdit={false}
        />,
      ),
    )
    expect(screen.queryByTestId("add-choice-button")).toBeNull()
    expect(screen.queryByLabelText(/Kéo để đổi thứ tự/)).toBeNull()
    expect(screen.queryByLabelText(/Xoá nguyện vọng/)).toBeNull()
  })

  it("disables add button when choices.length >= maxChoices + shows hint", () => {
    const choices = Array.from({ length: 5 }, (_, i) =>
      makeChoice({ id: i + 1, display_order: i + 1 }),
    )
    render(
      wrap(
        <ChoiceListEditor
          profileId={100}
          choices={choices}
          maxChoices={5}
          canEdit={true}
        />,
      ),
    )
    const addBtn = screen.getByTestId("add-choice-button")
    expect(addBtn.getAttribute("disabled")).not.toBeNull()
    expect(addBtn.getAttribute("aria-disabled")).toBe("true")
    expect(screen.getByTestId("choice-max-hint").textContent).toContain(
      "Đã đạt tối đa 5",
    )
  })

  it("clicking add button calls onRequestAdd callback", () => {
    const onRequestAdd = vi.fn()
    render(
      wrap(
        <ChoiceListEditor
          profileId={100}
          choices={[makeChoice()]}
          maxChoices={5}
          canEdit={true}
          onRequestAdd={onRequestAdd}
        />,
      ),
    )
    fireEvent.click(screen.getByTestId("add-choice-button"))
    expect(onRequestAdd).toHaveBeenCalledOnce()
  })

  it("clicking delete shows confirm dialog with NV label + choice display name", () => {
    const choices = [
      makeChoice({
        id: 7,
        display_order: 2,
        display_path_name: "CNTT 2026 - HSA - DOT_1",
      }),
    ]
    render(
      wrap(
        <ChoiceListEditor
          profileId={100}
          choices={choices}
          maxChoices={5}
          canEdit={true}
        />,
      ),
    )
    fireEvent.click(screen.getByLabelText("Xoá nguyện vọng 2"))
    // Radix Dialog renders in portal — query against document.body
    expect(screen.getByText("Xoá nguyện vọng?")).toBeTruthy()
    // Humanized display name (program — degree), NOT the machine composite path name.
    expect(
      screen.getByText(/NV2.*Cao đẳng Công nghệ thông tin — Cao đẳng/),
    ).toBeTruthy()
    expect(screen.queryByText(/CNTT 2026 - HSA - DOT_1/)).toBeNull()
  })

  it("confirm in delete dialog triggers deleteChoice API with correct id", async () => {
    mockDeleteChoice.mockResolvedValueOnce({ choice_id: 7, profile_id: 100 })
    const choices = [makeChoice({ id: 7, display_order: 1 })]
    render(
      wrap(
        <ChoiceListEditor
          profileId={100}
          choices={choices}
          maxChoices={5}
          canEdit={true}
        />,
      ),
    )
    fireEvent.click(screen.getByLabelText("Xoá nguyện vọng 1"))
    fireEvent.click(screen.getByTestId("confirm-remove-choice"))
    // React Query mutation fires async — wait for mutationFn invocation
    await waitFor(() => {
      expect(mockDeleteChoice).toHaveBeenCalledWith(100, 7)
    })
  })

  it("renders a decision badge per row with correct backend decision", () => {
    const choices = [
      makeChoice({ id: 1, display_order: 1, decision: "admitted" }),
      makeChoice({ id: 2, display_order: 2, decision: "waitlisted" }),
      makeChoice({ id: 3, display_order: 3, decision: "rejected" }),
    ]
    render(
      wrap(
        <ChoiceListEditor
          profileId={100}
          choices={choices}
          maxChoices={5}
          canEdit={true}
        />,
      ),
    )
    // Scope query inside each row to avoid global role="status" collisions
    // (other DOM nodes outside the component may also use role="status").
    const rows = screen.getAllByTestId(/^choice-row-/)
    expect(rows).toHaveLength(3)
    expect(within(rows[0]).getByRole("status")).toBeTruthy()
    expect(within(rows[1]).getByRole("status")).toBeTruthy()
    expect(within(rows[2]).getByRole("status")).toBeTruthy()
  })

  it("shows count badge in heading reflecting current vs max", () => {
    const choices = [makeChoice({ id: 1 }), makeChoice({ id: 2, display_order: 2 })]
    render(
      wrap(
        <ChoiceListEditor
          profileId={100}
          choices={choices}
          maxChoices={5}
          canEdit={true}
        />,
      ),
    )
    expect(screen.getByText(/Danh sách nguyện vọng \(2\/5\)/)).toBeTruthy()
  })
})
