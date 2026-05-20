/**
 * Q9 #07 Phase E.4 — PriorityHeaderBanner.deriveBannerState pure-function tests.
 *
 * Pins P1 contract (PR-3 audit cycle): preview-precedence rules trong
 * deriveBannerState(profile, preview).
 *
 * Precedence cases:
 *   1. manual_override_reason → "override" (always)
 *   2. status !== draft + snapshot.kv_resolved → "frozen" (snapshot wins post-submit)
 *   3. !cultural_education_level → "missing"
 *   4. draft + preview present → derive from preview ONLY (no snapshot fallback)
 *   5. draft + no preview → snapshot-derived (initial load defensive)
 */

import { describe, expect, it } from "vitest"
import type { PreviewPriorityKvResponse } from "@/lib/api/priority-kv"

import { deriveBannerState } from "./PriorityHeaderBanner"

const HAPPY_PREVIEW: PreviewPriorityKvResponse = {
  kv_resolved: "KV1",
  pathway: "thpt_multi_school",
  rule_applied: "longest_duration",
  requires_manual_override: false,
  reason: null,
  breakdown: null,
  area_bonus: 0.75,
  object_bonus_potential: null,
  object_bonus_verified: null,
  ut_breakdown: null,
  total_bonus_potential: 0.75,
  rule_law_citation: "TT 05/2021 Phụ lục 01 Mục 5.b",
}

const AMBIGUOUS_PREVIEW: PreviewPriorityKvResponse = {
  ...HAPPY_PREVIEW,
  kv_resolved: null,
  rule_applied: "ambiguous_requires_manual",
  requires_manual_override: true,
  reason: "tied_graduation_year_and_grade",
  area_bonus: null,
  total_bonus_potential: null,
  rule_law_citation: null,
}

describe("deriveBannerState — manual override", () => {
  it("returns 'override' when snapshot.manual_override_reason present (regardless of preview/status)", () => {
    const profile = {
      status: "draft" as const,
      cultural_education_level: "graduated_thpt",
      priority_resolution_snapshot: {
        manual_override_reason: "Admin chỉnh KV vì lớp tạo nguồn",
        kv_resolved: "KV1",
      },
    }
    expect(deriveBannerState(profile, HAPPY_PREVIEW)).toBe("override")
    expect(deriveBannerState(profile, null)).toBe("override")
  })
})

describe("deriveBannerState — frozen (post-submit snapshot wins)", () => {
  it("returns 'frozen' when status='submitted' and snapshot.kv_resolved set", () => {
    const profile = {
      status: "submitted" as const,
      cultural_education_level: "graduated_thpt",
      priority_resolution_snapshot: { kv_resolved: "KV1" },
    }
    // Even if preview disagrees, post-submit snapshot wins
    expect(deriveBannerState(profile, AMBIGUOUS_PREVIEW)).toBe("frozen")
  })

  it("does NOT return 'frozen' when status='draft' even with kv in snapshot", () => {
    const profile = {
      status: "draft" as const,
      cultural_education_level: "graduated_thpt",
      priority_resolution_snapshot: { kv_resolved: "KV1" },
    }
    expect(deriveBannerState(profile, null)).toBe("happy")
  })
})

describe("deriveBannerState — missing cultural input", () => {
  it("returns 'missing' when cultural_education_level null/empty", () => {
    const profile = {
      status: "draft" as const,
      cultural_education_level: null,
      priority_resolution_snapshot: {},
    }
    expect(deriveBannerState(profile, HAPPY_PREVIEW)).toBe("missing")
    expect(deriveBannerState(profile, null)).toBe("missing")
  })
})

describe("deriveBannerState — draft + preview precedence (P1 fix)", () => {
  const baseProfile = {
    status: "draft" as const,
    cultural_education_level: "graduated_thpt",
  }

  it("draft + preview happy → 'happy' (snapshot ignored)", () => {
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: {}, // empty snapshot — preview wins
    }
    expect(deriveBannerState(profile, HAPPY_PREVIEW)).toBe("happy")
  })

  it("draft + preview requires_manual_override → 'ambiguous'", () => {
    const profile = {
      ...baseProfile,
      // Snapshot might have stale kv from prior preview — preview takes precedence
      priority_resolution_snapshot: { kv_resolved: "KV1" },
    }
    expect(deriveBannerState(profile, AMBIGUOUS_PREVIEW)).toBe("ambiguous")
  })

  it("draft + preview present but kv_resolved=null → 'ambiguous' (NO snapshot fallback)", () => {
    // Critical contract: preview saying "no KV" should NOT silently fall
    // back to snapshot.kv_resolved (which could be stale).
    const preview: PreviewPriorityKvResponse = {
      ...HAPPY_PREVIEW,
      kv_resolved: null,
      area_bonus: null,
      requires_manual_override: false,
    }
    const profile = {
      ...baseProfile,
      // Snapshot has stale KV1 from previous engine run
      priority_resolution_snapshot: { kv_resolved: "KV1" },
    }
    expect(deriveBannerState(profile, preview)).toBe("ambiguous")
  })
})

describe("deriveBannerState — draft + no preview (initial load fallback)", () => {
  const baseProfile = {
    status: "draft" as const,
    cultural_education_level: "graduated_thpt",
  }

  it("returns 'happy' when snapshot has kv_resolved (no preview yet)", () => {
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: { kv_resolved: "KV1" },
    }
    expect(deriveBannerState(profile, null)).toBe("happy")
  })

  it("returns 'ambiguous' when snapshot.requires_manual_override=true (no preview)", () => {
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: { requires_manual_override: true },
    }
    expect(deriveBannerState(profile, null)).toBe("ambiguous")
  })

  it("returns 'ambiguous' when snapshot empty + no preview", () => {
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: {},
    }
    expect(deriveBannerState(profile, null)).toBe("ambiguous")
  })

  it("returns 'ambiguous' when preview undefined (treated same as null)", () => {
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: {},
    }
    expect(deriveBannerState(profile, undefined)).toBe("ambiguous")
  })
})
