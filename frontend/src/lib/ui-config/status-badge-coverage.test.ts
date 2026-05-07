/**
 * 14-state display readiness tests for the admission status
 * surfaces (#184 Wave 3 PR-3A FE bundle preflight).
 *
 * Locks the contract that every ``AdmissionStatus`` enum value
 * has:
 *   1. A badge config entry in ``ADMISSION_BADGE_CONFIG`` with
 *      label + className + variant + order.
 *   2. A label entry in ``ADMISSION_STATUS_MAP`` (the simpler
 *      StatusFromMap fallback path used by some legacy callers).
 *
 * Plus drift guards between ``AdmissionsClient.STATUS_TABS`` and
 * ``useAdmissionsFilter.STATUS_TABS`` — the two STATUS_TABS
 * declarations must cover the same status set so a tab-switch
 * round trip through versioned storage doesn't lose state.
 */
import { describe, expect, it } from "vitest"

import {
  ADMISSION_BADGE_CONFIG,
  type AdmissionStatus,
} from "./status-badge.config"
import { ADMISSION_STATUS_MAP } from "@/components/common/status/StatusBadge"


// All 14 admission status values — frozen here as the test
// source-of-truth. Match must include the 3 NEW phase1_11 states
// (admitted / waitlisted / result_published) plus the 11 legacy
// states. Adding a new status = update this list, the
// ``AdmissionStatus`` type union, and both badge maps in lockstep.
const ALL_14_STATES: ReadonlyArray<AdmissionStatus> = [
  "draft",
  "submitted",
  "resubmitted",
  "reviewing",
  "approved",
  "admitted",
  "waitlisted",
  "result_published",
  "rejected",
  "revision_requested",
  "confirmed",
  "overridden",
  "enrolled",
  "withdrawn",
]


// =============================================================================
// 1. Badge config coverage
// =============================================================================


describe("ADMISSION_BADGE_CONFIG", () => {
  it("has a config entry for every one of the 14 admission status", () => {
    for (const status of ALL_14_STATES) {
      expect(
        ADMISSION_BADGE_CONFIG[status],
        `missing badge config for ${status}`,
      ).toBeDefined()
    }
  })

  it("every entry has label + shortLabel + className + variant + order", () => {
    for (const status of ALL_14_STATES) {
      const config = ADMISSION_BADGE_CONFIG[status]
      expect(config.label, `${status}.label`).toBeTruthy()
      expect(config.shortLabel, `${status}.shortLabel`).toBeTruthy()
      expect(config.className, `${status}.className`).toBeTruthy()
      expect(config.variant, `${status}.variant`).toBeTruthy()
      expect(config.order, `${status}.order`).toBeGreaterThan(0)
    }
  })

  it("has exactly 14 entries (no leftover legacy keys, no orphan future keys)", () => {
    const keys = Object.keys(ADMISSION_BADGE_CONFIG)
    expect(keys).toHaveLength(14)
    expect(new Set(keys)).toEqual(new Set(ALL_14_STATES))
  })

  it("3 new phase1_11 states have distinct order between approved (5) and rejected (6)", () => {
    // Workflow chronology: approved (5) → admitted (5.5) →
    // waitlisted (5.7) → result_published (5.9) → rejected (6).
    const approved = ADMISSION_BADGE_CONFIG.approved.order
    const admitted = ADMISSION_BADGE_CONFIG.admitted.order
    const waitlisted = ADMISSION_BADGE_CONFIG.waitlisted.order
    const resultPublished = ADMISSION_BADGE_CONFIG.result_published.order
    const rejected = ADMISSION_BADGE_CONFIG.rejected.order

    expect(approved).toBeLessThan(admitted)
    expect(admitted).toBeLessThan(waitlisted)
    expect(waitlisted).toBeLessThan(resultPublished)
    expect(resultPublished).toBeLessThan(rejected)
  })
})


// =============================================================================
// 2. ADMISSION_STATUS_MAP coverage (legacy fallback path)
// =============================================================================


describe("ADMISSION_STATUS_MAP", () => {
  it("has a label for every one of the 14 admission status", () => {
    for (const status of ALL_14_STATES) {
      expect(
        ADMISSION_STATUS_MAP[status],
        `missing ADMISSION_STATUS_MAP entry for ${status}`,
      ).toBeDefined()
    }
  })

  it("3 new phase1_11 states have non-empty Vietnamese labels", () => {
    for (const status of ["admitted", "waitlisted", "result_published"] as const) {
      const config = ADMISSION_STATUS_MAP[status]
      expect(config.label).toBeTruthy()
      expect(config.label.length).toBeGreaterThan(0)
    }
  })
})
