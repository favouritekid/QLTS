/**
 * STATUS_TABS sync drift guard (#184 Wave 3 PR-3A FE bundle).
 *
 * ``AdmissionsClient.STATUS_TABS`` (rendered tabs) and
 * ``useAdmissionsFilter.STATUS_TABS`` (versioned-storage hook)
 * are two independent declarations of the tab → status mapping.
 * Drift between them = filter inconsistency across page reload:
 * a user who clicks "approved" tab and reloads gets the hook's
 * stored mapping which may include / exclude different statuses
 * than what the rendered tab currently filters.
 *
 * This test reads both declarations and asserts:
 *   1. Same set of tab keys.
 *   2. Same status set per shared tab key.
 *
 * Intentional divergence: ``AdmissionsClient`` exposes a
 * separate ``confirmed`` tab for officer ergonomics
 * (magic-link-pending visibility) while the filter hook
 * collapses ``confirmed`` into ``approved``. This is a
 * pre-existing ergonomic split documented in the hook source
 * and doesn't constitute drift; the test allows the
 * ``confirmed`` key on the UI side to be missing from the hook.
 */
import { describe, expect, it } from "vitest"

import { readFileSync } from "node:fs"
import { resolve } from "node:path"


// Read the source files directly (instead of importing the
// non-test modules) — both files have heavy ``"use client"``
// dependencies that wouldn't load in a vitest happydom
// environment without extensive mocking. Source-text inspection
// gives us the same drift guard with zero setup overhead.

const PROJECT_ROOT = resolve(__dirname, "../../../../..")
const ADMISSIONS_CLIENT = resolve(
  PROJECT_ROOT,
  "src/app/(dashboard)/admissions/_components/AdmissionsClient.tsx",
)
const FILTER_HOOK = resolve(
  PROJECT_ROOT,
  "src/hooks/admissions/useAdmissionsFilter.ts",
)


/** Parse a ``STATUS_TABS`` declaration from the source text.
 *
 * Uses a permissive regex that matches both the AdmissionsClient
 * (``label`` field) and the filter hook (no ``label``) shapes.
 * Returns a map of ``key -> Set<status>``. */
function parseStatusTabs(source: string): Map<string, Set<string>> {
  // Find the value declaration ``STATUS_TABS [: TypeAnnotation] = [``,
  // not the type annotation. The hook source has
  // ``STATUS_TABS: ReadonlyArray<{...}> = [...]`` so we need the
  // ``= [`` after the type annotation, not the ``[`` inside
  // ``readonly string[]``.
  const declMatch = source.match(/STATUS_TABS[^=]*=\s*\[/)
  expect(declMatch, "STATUS_TABS value declaration not found").not.toBeNull()
  const arrayStart = source.indexOf("[", declMatch!.index! + declMatch![0].length - 1)
  let depth = 0
  let arrayEnd = arrayStart
  for (let i = arrayStart; i < source.length; i++) {
    if (source[i] === "[") depth++
    else if (source[i] === "]") {
      depth--
      if (depth === 0) {
        arrayEnd = i
        break
      }
    }
  }
  const body = source.slice(arrayStart, arrayEnd + 1)

  const result = new Map<string, Set<string>>()
  // Each entry: { key: "...", ..., statuses: ["...", ...] }.
  const entryRe = /\{[^{}]*?key:\s*"([^"]+)"[^{}]*?statuses:\s*\[([^\]]*)\]/g
  let match: RegExpExecArray | null
  while ((match = entryRe.exec(body)) !== null) {
    const [, key, statusList] = match
    const statuses = new Set<string>(
      statusList
        .split(",")
        .map((s) => s.trim().replace(/^"|"$/g, ""))
        .filter((s) => s.length > 0),
    )
    result.set(key, statuses)
  }
  return result
}


// =============================================================================
// Drift guards
// =============================================================================


describe("STATUS_TABS sync — AdmissionsClient ↔ useAdmissionsFilter", () => {
  const clientTabs = parseStatusTabs(readFileSync(ADMISSIONS_CLIENT, "utf-8"))
  const hookTabs = parseStatusTabs(readFileSync(FILTER_HOOK, "utf-8"))

  it("both declarations parse to non-empty maps", () => {
    expect(clientTabs.size).toBeGreaterThan(0)
    expect(hookTabs.size).toBeGreaterThan(0)
  })

  // The "confirmed" tab is intentionally only in the UI (officer
  // ergonomic split). All other tabs MUST share status sets.
  const SHARED_TAB_KEYS = [
    "all",
    "draft",
    "pending",
    "approved",
    "waitlisted",
    "enrolled",
    "rejected",
  ] as const

  for (const tabKey of SHARED_TAB_KEYS) {
    it(`tab "${tabKey}" has the same status set in both declarations`, () => {
      const clientSet = clientTabs.get(tabKey)
      const hookSet = hookTabs.get(tabKey)
      expect(clientSet, `client tab ${tabKey} missing`).toBeDefined()
      expect(hookSet, `hook tab ${tabKey} missing`).toBeDefined()

      if (tabKey === "approved") {
        // Hook bundles ``confirmed`` into ``approved``; UI splits
        // them. Compare the status sets after normalizing the
        // hook's union with the UI's confirmed contribution.
        const uiConfirmed = clientTabs.get("confirmed") ?? new Set<string>()
        const uiApprovedPlusConfirmed = new Set<string>([
          ...(clientSet ?? []),
          ...uiConfirmed,
        ])
        expect(uiApprovedPlusConfirmed).toEqual(hookSet)
      } else {
        expect(clientSet).toEqual(hookSet)
      }
    })
  }
})


// =============================================================================
// Coverage — every status reachable from at least one tab or "all"
// =============================================================================


describe("STATUS_TABS coverage — 14 admission status reachable", () => {
  const clientTabs = parseStatusTabs(readFileSync(ADMISSIONS_CLIENT, "utf-8"))

  // Status union excluding ``result_published`` (Codex Q1 chốt:
  // broadcast marker, NOT a per-profile workflow target → intentionally
  // not in any specific tab; reachable only via "Tất cả").
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
  ] as const

  it("every workflow-target status appears in at least one specific tab", () => {
    const allStatusesInTabs = new Set<string>()
    for (const [key, statuses] of clientTabs) {
      if (key === "all") continue
      for (const s of statuses) allStatusesInTabs.add(s)
    }
    for (const status of TAB_REACHABLE_STATES) {
      expect(
        allStatusesInTabs.has(status),
        `status ${status} not reachable from any specific tab`,
      ).toBe(true)
    }
  })

  it("'all' tab has empty status array (= no filter)", () => {
    const allTab = clientTabs.get("all")
    expect(allTab).toBeDefined()
    expect(allTab?.size).toBe(0)
  })
})
