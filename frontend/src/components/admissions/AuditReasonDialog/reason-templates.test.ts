/**
 * Phase 3 PR-3D-B FE Wave B Day 10 — reason-templates helpers tests.
 */
import { beforeEach, describe, expect, it } from "vitest"

import {
  AUDIT_ACTION_CONFIG,
  getRecentReasonsKey,
  loadRecentReasons,
  pushRecentReason,
} from "./reason-templates"

describe("reason-templates", () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it("AUDIT_ACTION_CONFIG covers all 4 audit actions", () => {
    const actions: Array<keyof typeof AUDIT_ACTION_CONFIG> = [
      "waitlist_promote",
      "waitlist_reject",
      "manual_decision",
      "admin_rollback",
    ]
    actions.forEach((a) => {
      const cfg = AUDIT_ACTION_CONFIG[a]
      expect(cfg.title.length).toBeGreaterThan(0)
      expect(cfg.minLength).toBeGreaterThan(0)
      expect(cfg.maxLength).toBeGreaterThan(cfg.minLength)
      expect(cfg.templates.length).toBeGreaterThan(0)
    })
  })

  it("loadRecentReasons returns empty array when no entries", () => {
    expect(loadRecentReasons("admin_rollback")).toEqual([])
  })

  it("pushRecentReason adds reason to head + dedupes", () => {
    pushRecentReason("admin_rollback", "First reason")
    pushRecentReason("admin_rollback", "Second reason")
    pushRecentReason("admin_rollback", "First reason") // dup
    const list = loadRecentReasons("admin_rollback")
    expect(list).toEqual(["First reason", "Second reason"])
  })

  it("pushRecentReason truncates list to 5 entries", () => {
    for (let i = 1; i <= 7; i++) {
      pushRecentReason("admin_rollback", `Reason ${i}`)
    }
    const list = loadRecentReasons("admin_rollback")
    expect(list).toHaveLength(5)
    // Most recent first
    expect(list[0]).toBe("Reason 7")
    expect(list[4]).toBe("Reason 3")
  })

  it("pushRecentReason ignores empty/whitespace-only reasons", () => {
    pushRecentReason("admin_rollback", "")
    pushRecentReason("admin_rollback", "   ")
    expect(loadRecentReasons("admin_rollback")).toEqual([])
  })

  it("recent reasons partitioned per-action (key includes action)", () => {
    pushRecentReason("admin_rollback", "Rollback reason A")
    pushRecentReason("waitlist_promote", "Promote reason B")
    expect(loadRecentReasons("admin_rollback")).toEqual(["Rollback reason A"])
    expect(loadRecentReasons("waitlist_promote")).toEqual(["Promote reason B"])
  })

  it("loadRecentReasons survives corrupted localStorage payload", () => {
    window.localStorage.setItem(
      getRecentReasonsKey("admin_rollback"),
      "not-valid-json",
    )
    expect(loadRecentReasons("admin_rollback")).toEqual([])
  })

  it("loadRecentReasons filters non-string entries from poisoned array", () => {
    window.localStorage.setItem(
      getRecentReasonsKey("admin_rollback"),
      JSON.stringify(["ok", 123, null, "also ok"]),
    )
    expect(loadRecentReasons("admin_rollback")).toEqual(["ok", "also ok"])
  })
})
