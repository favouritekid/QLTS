import { describe, it, expect } from "vitest"
import {
  ADMISSION_STEPS,
  ADMISSION_STEP_IDS,
  STEP,
  GROUPED_SECTION_TO_STEP,
} from "./admission-steps"

/**
 * The pipeline step-id space is encoded in THREE places (ADMISSION_STEPS[].id,
 * the STEP name→id map, GROUPED_SECTION_TO_STEP section→id). These pins fail if a
 * reorder/edit touches one but not the others — turning a silent drift (CTA routes
 * to the wrong tab) into a red test.
 */
describe("admission-steps registry ↔ STEP map", () => {
  it("STEP values are exactly the ADMISSION_STEPS ids", () => {
    const ids = ADMISSION_STEPS.map((s) => s.id)
    expect([...Object.values(STEP)].sort((a, b) => a - b)).toEqual(ids)
  })

  it("names point at the expected positions", () => {
    expect(STEP.FAMILY).toBe(2)
    expect(STEP.ACADEMIC).toBe(3)
    expect(STEP.PRIORITY).toBe(4)
  })

  it("ADMISSION_STEP_IDS mirrors the registry order", () => {
    expect(ADMISSION_STEP_IDS).toEqual(ADMISSION_STEPS.map((s) => s.id))
  })

  it("GROUPED_SECTION_TO_STEP maps only to real, correctly-named step ids", () => {
    const ids = new Set(ADMISSION_STEPS.map((s) => s.id))
    for (const step of Object.values(GROUPED_SECTION_TO_STEP)) {
      expect(ids.has(step)).toBe(true)
    }
    expect(GROUPED_SECTION_TO_STEP.personal_info).toBe(STEP.PERSONAL)
    expect(GROUPED_SECTION_TO_STEP.scores).toBe(STEP.SCORES)
    expect(GROUPED_SECTION_TO_STEP.documents).toBe(STEP.DOCUMENTS)
  })
})
