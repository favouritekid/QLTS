/**
 * Unit tests for #184 Wave 4 PR #15c — FE migrate `admission_profile` →
 * `admission_profiles` plural.
 *
 * The component reads the most-recent profile (latest year) from the
 * plural list, falling back to the legacy singular field while the
 * backend still emits the dual-response shape introduced by Wave 4
 * PR #15b. Wave 4 PR #15d will remove the legacy field once all
 * consumers migrate.
 *
 * Tests guard the dual-read pattern so a future regression that
 * silently drops the plural read does not surface only after the
 * backend removes the legacy field.
 */
import { describe, expect, it } from "vitest"

import type { Lead, AdmissionProfileShallow } from "@/types/lead.types"

// The pure derivation helper isn't exported, so we exercise it through
// the component file's text. A non-tautological text-grep test is the
// pragmatic way to catch a regression that re-introduces the singular
// access pattern without paying the cost of mounting the React tree.
import { readFileSync } from "fs"
import path from "path"

const COMPONENT_PATH = path.resolve(
  __dirname,
  "AdmissionReadinessChecklist.tsx",
)
const componentSource = readFileSync(COMPONENT_PATH, "utf-8")

describe("AdmissionReadinessChecklist — Wave 4 #15c plural migrate", () => {
  it("reads from admission_profiles plural with legacy fallback", () => {
    // The dual-read pattern must keep both fields in scope. If a
    // refactor drops the plural read, this guard surfaces it before
    // the backend removes the singular field.
    expect(componentSource).toContain("lead.admission_profiles?.[0]")
    expect(componentSource).toContain("lead.admission_profile")
    // Plural read MUST come first in the nullish-coalesce expression
    // so the latest-year profile wins — legacy is fallback only.
    const pluralIdx = componentSource.indexOf(
      "lead.admission_profiles?.[0]",
    )
    const singularIdx = componentSource.indexOf(
      "?? lead.admission_profile",
    )
    expect(pluralIdx).toBeGreaterThan(0)
    expect(singularIdx).toBeGreaterThan(pluralIdx)
  })
})


describe("Lead type — admission_profiles plural shape", () => {
  it("type allows plural list with legacy singular fallback", () => {
    // Profile shape mirrors `AdmissionProfileShallow` interface
    // (`types/lead.types.ts:340-345` + BE `app/schemas/lead.py:133-144`):
    // {id, status, student_code?, created_at}. `lead_id` and
    // `academic_year` are NOT in the shallow nested response — they
    // live on the full `AdmissionProfileResponse`. Wave 4 #15c plural
    // shape exposes the per-year list via `Lead.admission_profiles[]`
    // but each item still uses the shallow projection.
    const profile_2026: AdmissionProfileShallow = {
      id: 100,
      status: "draft",
      created_at: "2026-01-01T00:00:00Z",
    }

    const lead_with_plural: Pick<Lead, "id" | "admission_profiles" | "admission_profile"> = {
      id: 1,
      admission_profiles: [profile_2026],
    }
    const lead_legacy_only: Pick<Lead, "id" | "admission_profiles" | "admission_profile"> = {
      id: 1,
      admission_profile: profile_2026,
    }
    const lead_both: Pick<Lead, "id" | "admission_profiles" | "admission_profile"> = {
      id: 1,
      admission_profiles: [profile_2026],
      admission_profile: profile_2026,
    }

    // Type-check — runtime assertions are trivial; the ts compile
    // catches the schema drift.
    expect(lead_with_plural.admission_profiles?.[0]?.id).toBe(100)
    expect(lead_legacy_only.admission_profile?.id).toBe(100)
    expect(lead_both.admission_profiles?.[0]?.id).toBe(100)
    expect(lead_both.admission_profile?.id).toBe(100)
  })
})
