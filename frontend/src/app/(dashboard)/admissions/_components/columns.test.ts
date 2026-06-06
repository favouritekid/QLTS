/**
 * Admissions list STATUS_CONFIG — completeness pin.
 *
 * Derived from the canonical ADMISSION_STATUS_CONFIG so the list status badge
 * covers EVERY admission state (incl. the multi-NV states the old inline map
 * omitted, which rendered the raw English enum on the list).
 */

import { describe, it, expect } from "vitest"
import { STATUS_CONFIG } from "./columns"
import { ADMISSION_STATUS_CONFIG } from "@/lib/status-config"

describe("admissions list STATUS_CONFIG", () => {
  it("covers the multi-NV states that were previously missing (no raw enum on the list)", () => {
    for (const s of ["reviewing", "result_published", "admitted", "waitlisted"]) {
      expect(STATUS_CONFIG[s]?.label).toBeTruthy()
      expect(STATUS_CONFIG[s].label).not.toBe(s) // not the raw enum
    }
  })

  it("stays in parity with the canonical ADMISSION_STATUS_CONFIG (single source)", () => {
    for (const [status, cfg] of Object.entries(ADMISSION_STATUS_CONFIG)) {
      expect(STATUS_CONFIG[status]?.label).toBe(cfg.label)
      expect(STATUS_CONFIG[status]?.color).toBe(cfg.badgeColor)
    }
  })

  it("keeps the core states", () => {
    expect(STATUS_CONFIG.submitted?.label).toBe("Chờ duyệt")
    expect(STATUS_CONFIG.draft?.label).toBe("Nháp")
  })
})
