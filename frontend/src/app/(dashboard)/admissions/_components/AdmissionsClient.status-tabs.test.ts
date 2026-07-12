/**
 * ADMISSION_STATUS_TABS — single shared source for the admissions list tabs.
 *
 * Previously the tab → status mapping was DUPLICATED in AdmissionsClient (rendered
 * tabs) and useAdmissionsFilter (filter), and the two copies DRIFTED: the hook
 * lacked a `confirmed` tab and folded `confirmed` into `approved`. Result:
 *   - clicking "Đã xác nhận" → handleTabClick found no tab → empty filter → the
 *     list showed ALL profiles instead of only confirmed;
 *   - the "Đã duyệt" count (UI, excludes confirmed) disagreed with its filtered
 *     result (hook, includes confirmed).
 * Both now import this ONE constant, so cross-file drift is impossible. These
 * tests pin the intended grouping + 14-state coverage on the shared source.
 */
import { describe, expect, it } from "vitest"
import { ADMISSION_STATUS_TABS } from "@/hooks/admissions/filterDefaults"

const byKey = new Map(ADMISSION_STATUS_TABS.map((t) => [t.key, new Set(t.statuses)]))

describe("ADMISSION_STATUS_TABS — grouping", () => {
  it("'confirmed' is its OWN tab = ['confirmed']", () => {
    expect(byKey.get("confirmed")).toEqual(new Set(["confirmed"]))
  })

  it("'approved' = approved/admitted/overridden and does NOT include confirmed", () => {
    expect(byKey.get("approved")).toEqual(new Set(["approved", "admitted", "overridden"]))
  })

  it("'pending' bundles submitted/resubmitted/reviewing/revision_requested", () => {
    expect(byKey.get("pending")).toEqual(
      new Set(["submitted", "resubmitted", "reviewing", "revision_requested"]),
    )
  })

  it("'rejected' bundles rejected/withdrawn/withdrawal_pending", () => {
    expect(byKey.get("rejected")).toEqual(
      new Set(["rejected", "withdrawn", "withdrawal_pending"]),
    )
  })

  it("'all' tab = empty (no filter)", () => {
    expect(byKey.get("all")?.size).toBe(0)
  })
})

describe("ADMISSION_STATUS_TABS — 14-state coverage", () => {
  const inSpecificTabs = new Set<string>()
  for (const t of ADMISSION_STATUS_TABS) {
    if (t.key === "all") continue
    for (const s of t.statuses) inSpecificTabs.add(s)
  }

  // result_published is intentionally in NO tab (broadcast marker; reachable via
  // "Tất cả" / the status drop-down only — Codex Q1 chốt).
  const TAB_REACHABLE_STATES = [
    "draft",
    "submitted",
    "resubmitted",
    "reviewing",
    "approved",
    "admitted",
    "waitlisted",
    "rejected",
    "revision_requested",
    "confirmed",
    "overridden",
    "enrolled",
    "withdrawn",
    "withdrawal_pending", // PR-B: grouped in the "Từ chối" tab with withdrawn
  ] as const

  it("every workflow-target status appears in at least one specific tab", () => {
    for (const status of TAB_REACHABLE_STATES) {
      expect(
        inSpecificTabs.has(status),
        `status ${status} not reachable from any specific tab`,
      ).toBe(true)
    }
  })

  it("'result_published' is intentionally NOT in any specific tab", () => {
    expect(inSpecificTabs.has("result_published")).toBe(false)
  })
})
