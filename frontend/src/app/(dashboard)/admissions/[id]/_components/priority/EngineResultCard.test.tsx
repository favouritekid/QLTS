/**
 * Q9 #07 Phase E.4 — EngineResultCard.deriveEngineState pure-function tests.
 *
 * Pins P1 contract (PR-3 Step D audit cycle): preview-precedence rules
 * trong deriveEngineState. Mirror PriorityHeaderBanner contract.
 *
 * Critical regression: draft + preview present + kv_resolved=null +
 * snapshot.kv_resolved !=null → MUST return "ambiguous", NOT fallback
 * stale snapshot.
 */
import { describe, expect, it } from "vitest"
import type { PreviewPriorityKvResponse } from "@/lib/api/priority-kv"

import { deriveEngineState } from "./EngineResultCard"

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

describe("deriveEngineState — manual override always wins", () => {
  it("returns 'override' when snapshot.manual_override_reason present", () => {
    const profile = {
      status: "draft" as const,
      cultural_education_level: "graduated_thpt",
      priority_resolution_snapshot: {
        manual_override_reason: "Admin chỉnh KV vì lớp tạo nguồn",
        kv_resolved: "KV1",
      },
    }
    expect(deriveEngineState(profile, HAPPY_PREVIEW)).toBe("override")
    expect(deriveEngineState(profile, null)).toBe("override")
  })
})

describe("deriveEngineState — frozen post-submit", () => {
  it("returns 'frozen' when status='submitted' and snapshot.kv_resolved set", () => {
    const profile = {
      status: "submitted" as const,
      cultural_education_level: "graduated_thpt",
      priority_resolution_snapshot: { kv_resolved: "KV1" },
    }
    expect(deriveEngineState(profile, AMBIGUOUS_PREVIEW)).toBe("frozen")
    expect(deriveEngineState(profile, null)).toBe("frozen")
  })
})

describe("deriveEngineState — missing cultural input", () => {
  it("returns 'missing' when cultural_education_level null", () => {
    const profile = {
      status: "draft" as const,
      cultural_education_level: null,
      priority_resolution_snapshot: {},
    }
    expect(deriveEngineState(profile, HAPPY_PREVIEW)).toBe("missing")
    expect(deriveEngineState(profile, null)).toBe("missing")
  })
})

describe("deriveEngineState — draft + preview precedence (P1 fix)", () => {
  const baseProfile = {
    status: "draft" as const,
    cultural_education_level: "graduated_thpt",
  }

  it("draft + preview happy → 'happy'", () => {
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: {},
    }
    expect(deriveEngineState(profile, HAPPY_PREVIEW)).toBe("happy")
  })

  it("draft + preview requires_manual_override → 'ambiguous'", () => {
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: { kv_resolved: "KV1" },
    }
    expect(deriveEngineState(profile, AMBIGUOUS_PREVIEW)).toBe("ambiguous")
  })

  it("draft + preview kv_resolved=null + snapshot.kv stale → 'ambiguous' (NO snapshot fallback)", () => {
    // Critical regression — exact stale-snapshot bug user identified.
    const preview: PreviewPriorityKvResponse = {
      ...HAPPY_PREVIEW,
      kv_resolved: null,
      area_bonus: null,
      requires_manual_override: false,
    }
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: { kv_resolved: "KV1" }, // stale
    }
    expect(deriveEngineState(profile, preview)).toBe("ambiguous")
  })
})

describe("deriveEngineState — draft + no preview (initial load fallback)", () => {
  const baseProfile = {
    status: "draft" as const,
    cultural_education_level: "graduated_thpt",
  }

  it("returns 'happy' when snapshot.kv_resolved exists (no preview yet)", () => {
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: { kv_resolved: "KV1" },
    }
    expect(deriveEngineState(profile, null)).toBe("happy")
  })

  it("returns 'ambiguous' when snapshot.requires_manual_override (no preview)", () => {
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: { requires_manual_override: true },
    }
    expect(deriveEngineState(profile, null)).toBe("ambiguous")
  })

  it("returns 'ambiguous' when snapshot empty + no preview", () => {
    const profile = {
      ...baseProfile,
      priority_resolution_snapshot: {},
    }
    expect(deriveEngineState(profile, null)).toBe("ambiguous")
  })
})
