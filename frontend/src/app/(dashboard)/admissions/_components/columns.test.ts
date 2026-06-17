/**
 * Admissions list status labels — coverage pin.
 *
 * The list status cell renders via <StatusDot> (roster-parts), which reads
 * ADMISSION_STATUS_CONFIG for its label. Pin that EVERY admission state — incl.
 * the multi-NV states (reviewing / result_published / admitted / waitlisted) the
 * old inline map omitted — has a real, non-enum label, so the list never renders
 * a raw English enum.
 */

import { describe, it, expect } from "vitest"
import { ADMISSION_STATUS_CONFIG } from "@/lib/status-config"

describe("admissions list status labels (ADMISSION_STATUS_CONFIG)", () => {
  it("covers the multi-NV states with non-enum labels", () => {
    for (const s of ["reviewing", "result_published", "admitted", "waitlisted"]) {
      expect(ADMISSION_STATUS_CONFIG[s]?.label).toBeTruthy()
      expect(ADMISSION_STATUS_CONFIG[s].label).not.toBe(s) // not the raw enum
    }
  })

  it("keeps the core states", () => {
    expect(ADMISSION_STATUS_CONFIG.submitted?.label).toBe("Chờ duyệt")
    expect(ADMISSION_STATUS_CONFIG.draft?.label).toBe("Nháp")
  })
})
