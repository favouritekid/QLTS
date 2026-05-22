/**
 * engineDisplay — pure helper anchor tests (Commit 8 followup).
 *
 * Pin precedence rules cho 4 derived display values theo frozen snapshot
 * vs draft preview semantics.
 */

import { describe, it, expect } from "vitest"
import type { PreviewPriorityKvResponse } from "@/lib/api/priority-kv"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

import { resolveEngineDisplay, deriveLawCitationFallback } from "./engineDisplay"

const HAPPY_PREVIEW: PreviewPriorityKvResponse = {
  kv_resolved: "KV1",
  pathway: "thpt_multi_school",
  rule_applied: "longest_duration",
  requires_manual_override: false,
  reason: "Tốt nghiệp THPT 2024, trường KV1",
  breakdown: null,
  area_bonus: 0.75,
  object_bonus_potential: null,
  object_bonus_verified: null,
  ut_breakdown: null,
  total_bonus_potential: 0.75,
  rule_law_citation: "TT 05/2021 Phụ lục 01 Mục 5.b (preview)",
  path_bonus_rule: null,
}

type SnapshotInput = AdmissionProfileResponse["priority_resolution_snapshot"]
type ProfileInput = Pick<AdmissionProfileResponse, "status" | "priority_resolution_snapshot">

function buildProfile(status: string, snapshot: SnapshotInput = {} as SnapshotInput): ProfileInput {
  return {
    status,
    priority_resolution_snapshot: snapshot,
  } as ProfileInput
}

describe("deriveLawCitationFallback", () => {
  it("returns mapped citation cho 4 rule_applied chuẩn", () => {
    expect(deriveLawCitationFallback("longest_duration")).toMatch(/Mục 5\.b/)
    expect(deriveLawCitationFallback("tiebreak_graduation_school")).toMatch(/Mục 5\.a/)
    expect(deriveLawCitationFallback("commune_lookup")).toMatch(/Mục 4/)
    expect(deriveLawCitationFallback("manual_override")).toMatch(/Mục 6/)
  })

  it("returns null cho 'ambiguous_requires_manual'", () => {
    expect(deriveLawCitationFallback("ambiguous_requires_manual")).toBeNull()
  })

  it("returns null cho rule_applied unknown", () => {
    expect(deriveLawCitationFallback("foo_unknown_rule")).toBeNull()
  })
})

describe("resolveEngineDisplay — post-draft (frozen snapshot)", () => {
  it("ưu tiên snapshot.rule_law_citation hơn fallback", () => {
    const profile = buildProfile("submitted", {
      kv_resolved: "KV1",
      rule_applied: "longest_duration",
      rule_law_citation: "BE-canonical citation",
      basis_reason: "BE reason",
      breakdown: { area_bonus: 0.75 },
    } as SnapshotInput)
    const r = resolveEngineDisplay(profile, null)
    expect(r.kv).toBe("KV1")
    expect(r.lawCitation).toBe("BE-canonical citation")
    expect(r.reason).toBe("BE reason")
    expect(r.areaBonus).toBe(0.75)
  })

  it("fallback deriveLawCitationFallback khi rule_law_citation thiếu (legacy snapshot)", () => {
    const profile = buildProfile("submitted", {
      kv_resolved: "KV1",
      rule_applied: "longest_duration",
    } as SnapshotInput)
    const r = resolveEngineDisplay(profile, null)
    expect(r.lawCitation).toMatch(/Mục 5\.b/)
  })

  it("ignore preview khi post-draft (defensive)", () => {
    const profile = buildProfile("submitted", {
      kv_resolved: "KV2-NT",
      basis_reason: "snapshot reason",
    } as SnapshotInput)
    const r = resolveEngineDisplay(profile, HAPPY_PREVIEW)
    expect(r.kv).toBe("KV2-NT")
    expect(r.reason).toBe("snapshot reason")
    expect(r.lawCitation).toBeNull() // không fall sang preview
  })

  it("basis_reason chiếm ưu thế snapshot.reason", () => {
    const profile = buildProfile("submitted", {
      basis_reason: "BE canonical",
      reason: "legacy error fallback",
    } as SnapshotInput)
    expect(resolveEngineDisplay(profile, null).reason).toBe("BE canonical")
  })

  it("fallback snapshot.reason khi basis_reason missing", () => {
    const profile = buildProfile("submitted", {
      reason: "legacy error fallback",
    } as SnapshotInput)
    expect(resolveEngineDisplay(profile, null).reason).toBe("legacy error fallback")
  })

  it("areaBonus đọc snapshot.breakdown.area_bonus, fallback 0", () => {
    const r1 = resolveEngineDisplay(buildProfile("submitted", { breakdown: { area_bonus: 1.5 } } as SnapshotInput), null)
    expect(r1.areaBonus).toBe(1.5)
    const r2 = resolveEngineDisplay(buildProfile("submitted", {} as SnapshotInput), null)
    expect(r2.areaBonus).toBe(0)
    const r3 = resolveEngineDisplay(buildProfile("submitted", { breakdown: {} } as SnapshotInput), null)
    expect(r3.areaBonus).toBe(0)
  })
})

describe("resolveEngineDisplay — draft + preview", () => {
  it("preview chiếm ưu thế snapshot stale", () => {
    const profile = buildProfile("draft", {
      kv_resolved: "STALE_KV",
      basis_reason: "stale snapshot",
    } as SnapshotInput)
    const r = resolveEngineDisplay(profile, HAPPY_PREVIEW)
    expect(r.kv).toBe("KV1")
    expect(r.lawCitation).toBe(HAPPY_PREVIEW.rule_law_citation)
    expect(r.reason).toBe(HAPPY_PREVIEW.reason)
    expect(r.areaBonus).toBe(0.75)
  })

  it("draft + preview.kv null: trả null thay vì fallback stale snapshot", () => {
    const ambiguousPreview: PreviewPriorityKvResponse = {
      ...HAPPY_PREVIEW,
      kv_resolved: null,
      area_bonus: null,
      rule_law_citation: null,
      reason: "ambiguous_requires_manual",
    }
    const profile = buildProfile("draft", {
      kv_resolved: "STALE_KV", // KHÔNG được dùng
    } as SnapshotInput)
    const r = resolveEngineDisplay(profile, ambiguousPreview)
    expect(r.kv).toBeNull()
    expect(r.areaBonus).toBe(0)
  })
})

describe("resolveEngineDisplay — draft no preview", () => {
  it("fallback snapshot cho kv/lawCitation/reason (initial load defensive)", () => {
    const profile = buildProfile("draft", {
      kv_resolved: "KV1",
      rule_law_citation: "TT cached",
      basis_reason: "cached reason",
      breakdown: { area_bonus: 0.5 },
    } as SnapshotInput)
    const r = resolveEngineDisplay(profile, null)
    expect(r.kv).toBe("KV1")
    expect(r.lawCitation).toBe("TT cached")
    expect(r.reason).toBe("cached reason")
    // Original behavior: areaBonus draft+no preview = 0 (KHÔNG fallback
    // snapshot.breakdown). Logic kế thừa từ EngineResultCard original
    // — preview là source-of-truth cho bonus trong draft mode.
    expect(r.areaBonus).toBe(0)
  })
})
