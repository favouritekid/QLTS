/**
 * Unit tests for ``admission-audience`` constants (#184 Wave 1
 * PR-1B'-FE).
 *
 * Locks the 5-value Vietnamese label table + the
 * ``AUDIENCE_OPTIONS`` re-export. Adding / renaming an audience
 * MUST flag here BEFORE the BE migration ships, so admin UI
 * doesn't render an audience the BE doesn't accept.
 */
import { describe, expect, it } from "vitest"

import {
  AUDIENCE_LABELS_VI,
  AUDIENCE_OPTIONS,
} from "./admission-audience"
import {
  admissionAudienceEnum,
  type AdmissionAudience,
} from "@/lib/zod/admission-path"

describe("AUDIENCE_LABELS_VI", () => {
  it("covers all 5 admission_audience enum values", () => {
    const expectedKeys: AdmissionAudience[] = [
      "POST_THCS",
      "POST_THPT",
      "LIEN_THONG_TC",
      "LIEN_THONG_CD",
      "VLVH",
    ]
    expect(Object.keys(AUDIENCE_LABELS_VI).sort()).toEqual(
      expectedKeys.slice().sort(),
    )
  })

  it("every label is non-empty Vietnamese text", () => {
    for (const value of Object.values(AUDIENCE_LABELS_VI)) {
      expect(value.length).toBeGreaterThan(0)
      // Sanity guard — label must include diacritics or a Vietnamese
      // word so a stray English fallback ("Post HS") catches in CI.
      // ``vừa làm`` / ``Sau`` / ``Liên thông`` all qualify.
      expect(value).toMatch(/[ăâđêôơưĂÂĐÊÔƠƯàáảãạèéẻẽẹìíỉĩịòóỏõọùúủũụỳýỷỹỵửữựụAUSL]/i)
    }
  })

  it("matches admissionAudienceEnum.options exactly", () => {
    // Cross-check: any drift between the Zod enum and the label
    // table would render an audience without a label or vice-versa.
    expect([...AUDIENCE_OPTIONS].sort()).toEqual(
      [...admissionAudienceEnum.options].sort(),
    )
  })
})

describe("AUDIENCE_OPTIONS", () => {
  it("re-exports the Zod enum options ReadonlyArray", () => {
    // Identity-equal to the Zod source — admin form iterates this
    // to guarantee stable order without an Object.entries detour.
    expect(AUDIENCE_OPTIONS).toEqual(admissionAudienceEnum.options)
  })

  it("contains exactly 5 audience values", () => {
    expect(AUDIENCE_OPTIONS).toHaveLength(5)
  })

  it("each option has a corresponding label", () => {
    for (const audience of AUDIENCE_OPTIONS) {
      expect(AUDIENCE_LABELS_VI[audience]).toBeTruthy()
    }
  })
})
