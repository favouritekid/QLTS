/**
 * Regression: the /finance/fees → workspace redirect must translate legacy
 * CTA params, not copy them verbatim (PR2 P2 review).
 */
import { describe, it, expect } from "vitest"

import { legacyFeesRedirectTarget } from "./redirect-target"

describe("legacyFeesRedirectTarget", () => {
  it("maps profile_id → profile (opens the drawer, not the list filter)", () => {
    expect(legacyFeesRedirectTarget({ profile_id: "25" })).toBe(
      "/finance/invoices?profile=25",
    )
  })

  it("passes action=calculate through unchanged", () => {
    expect(legacyFeesRedirectTarget({ action: "calculate" })).toBe(
      "/finance/invoices?action=calculate",
    )
  })

  it("maps status=pending → tab=issued, NOT tab=pending (the queue sentinel)", () => {
    const target = legacyFeesRedirectTarget({ status: "pending" })
    expect(target).toBe("/finance/invoices?tab=issued")
    expect(target).not.toContain("tab=pending")
  })

  it("drops unmapped legacy status values", () => {
    expect(legacyFeesRedirectTarget({ status: "paid" })).toBe(
      "/finance/invoices",
    )
  })

  it("returns the bare workspace when there is no query", () => {
    expect(legacyFeesRedirectTarget({})).toBe("/finance/invoices")
  })

  it("combines a mapped param with a pass-through one", () => {
    const target = legacyFeesRedirectTarget({ profile_id: "7", q: "abc" })
    expect(target).toContain("profile=7")
    expect(target).toContain("q=abc")
    expect(target).not.toContain("profile_id")
  })

  it("ignores array-valued params", () => {
    expect(legacyFeesRedirectTarget({ profile_id: ["1", "2"] })).toBe(
      "/finance/invoices",
    )
  })
})
