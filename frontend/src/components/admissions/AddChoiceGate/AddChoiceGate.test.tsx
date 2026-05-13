/**
 * Phase 3 PR-3D-B Bundle 3 — AddChoiceGate tests.
 */
import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { AddChoiceGate } from "./AddChoiceGate"

describe("AddChoiceGate", () => {
  it("renders enabled button when profile has add_choice in available_actions_v2", () => {
    const profile = {
      available_actions_v2: [{ action: "add_choice" }],
    }
    const onAdd = vi.fn()
    render(<AddChoiceGate profile={profile} onAdd={onAdd} />)
    const btn = screen.getByTestId("add-choice-gate-button")
    expect(btn.getAttribute("disabled")).toBeNull()
    fireEvent.click(btn)
    expect(onAdd).toHaveBeenCalledOnce()
  })

  it("renders enabled button when add_choice in legacy available_actions list", () => {
    const profile = {
      available_actions: ["add_choice"],
    }
    render(<AddChoiceGate profile={profile} onAdd={() => {}} />)
    expect(
      screen
        .getByTestId("add-choice-gate-button")
        .getAttribute("disabled"),
    ).toBeNull()
  })

  it("renders disabled button when neither field grants add_choice", () => {
    const profile = {
      available_actions_v2: [{ action: "calculate_fee" }],
    }
    const onAdd = vi.fn()
    render(<AddChoiceGate profile={profile} onAdd={onAdd} />)
    const btn = screen.getByTestId("add-choice-gate-button")
    expect(btn.getAttribute("disabled")).not.toBeNull()
    expect(btn.getAttribute("aria-disabled")).toBe("true")
  })

  it("renders disabled when profile null (defensive — backend may not have populated yet)", () => {
    render(<AddChoiceGate profile={null} onAdd={() => {}} />)
    const btn = screen.getByTestId("add-choice-gate-button")
    expect(btn.getAttribute("disabled")).not.toBeNull()
  })

  it("disabled button does not fire onAdd on click attempt", () => {
    const profile = { available_actions_v2: [] }
    const onAdd = vi.fn()
    render(<AddChoiceGate profile={profile} onAdd={onAdd} />)
    fireEvent.click(screen.getByTestId("add-choice-gate-button"))
    expect(onAdd).not.toHaveBeenCalled()
  })

  it("v2 takes priority over legacy when both present (memory react-query-mutation-cache-parity hasAction contract)", () => {
    // Legacy says allowed, v2 says NOT — v2 wins → disabled
    const profile = {
      available_actions: ["add_choice"],
      available_actions_v2: [{ action: "calculate_fee" }],
    }
    render(<AddChoiceGate profile={profile} onAdd={() => {}} />)
    expect(
      screen
        .getByTestId("add-choice-gate-button")
        .getAttribute("disabled"),
    ).not.toBeNull()
  })
})
