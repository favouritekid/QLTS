/**
 * admission-helpers — method label + choice summary.
 *
 * Pins the "Nguyện vọng: 201" fix: getAdmissionMethodLabel must NEVER return a raw
 * numeric TS2026 method code (falls back to method_type), and getChoiceSummaryLabel
 * surfaces the candidate's actual choice(s), not the method.
 */

import { describe, it, expect } from "vitest"
import {
  getAdmissionMethodLabel,
  getChoiceSummaryLabel,
  getChoiceDisplayName,
  getSubjectLabel,
  formatRoundLabel,
} from "./admission-helpers"
import type { AppliedRules } from "@/lib/zod/admissions"

const ar = (o: Partial<AppliedRules>) => o as AppliedRules

describe("getAdmissionMethodLabel", () => {
  it("legacy enum → specific label", () => {
    expect(getAdmissionMethodLabel(ar({ admission_method: "HOC_BA" }))).toBe("Xét học bạ THPT")
  })

  it("TS2026 numeric code → method_type label, NEVER the raw code", () => {
    const label = getAdmissionMethodLabel(ar({ admission_method: "201", method_type: "subject_based" }))
    expect(label).toBe("Xét theo tổ hợp môn")
    expect(label).not.toBe("201")
  })

  it("gpa_only method_type → 'Xét học bạ'", () => {
    expect(getAdmissionMethodLabel(ar({ admission_method: "100", method_type: "gpa_only" }))).toBe("Xét học bạ")
  })

  it("unknown method + no method_type → generic 'Xét tuyển' (never raw)", () => {
    expect(getAdmissionMethodLabel(ar({ admission_method: "999", method_type: null }))).toBe("Xét tuyển")
    expect(getAdmissionMethodLabel(ar({ admission_method: null, method_type: null }))).toBe("Xét tuyển")
  })
})

describe("getChoiceSummaryLabel", () => {
  it("multi-NV: first program — degree + '+N NV'", () => {
    expect(
      getChoiceSummaryLabel({
        choices: [
          { display_program_name: "Công nghệ ô tô", display_degree_level: "Trung cấp" },
          { display_program_name: "Điện công nghiệp", display_degree_level: "Cao đẳng" },
        ],
      }),
    ).toBe("Công nghệ ô tô — Trung cấp +1 NV")
  })

  it("single choice: program — degree, no suffix", () => {
    expect(
      getChoiceSummaryLabel({
        choices: [{ display_program_name: "Công nghệ ô tô", display_degree_level: "Trung cấp" }],
      }),
    ).toBe("Công nghệ ô tô — Trung cấp")
  })

  it("no choices → profile.program_name", () => {
    expect(getChoiceSummaryLabel({ choices: [], program_name: "Kế toán" })).toBe("Kế toán")
  })

  it("nothing available → '—'", () => {
    expect(getChoiceSummaryLabel({})).toBe("—")
  })
})

describe("getChoiceDisplayName", () => {
  it("program + degree → 'Ngành — Bậc'", () => {
    expect(
      getChoiceDisplayName({ display_program_name: "Công nghệ ô tô", display_degree_level: "Trung cấp" }),
    ).toBe("Công nghệ ô tô — Trung cấp")
  })
  it("program only → program", () => {
    expect(getChoiceDisplayName({ display_program_name: "Kế toán", display_degree_level: "" })).toBe("Kế toán")
  })
  it("empty → '—' (never the machine composite)", () => {
    expect(getChoiceDisplayName({})).toBe("—")
  })
})

describe("getSubjectLabel (THCS additions)", () => {
  it("natural_science → 'Khoa học tự nhiên' (not the raw code)", () => {
    expect(getSubjectLabel("natural_science")).toBe("Khoa học tự nhiên")
  })
  it("social_science → 'Khoa học xã hội'", () => {
    expect(getSubjectLabel("social_science")).toBe("Khoa học xã hội")
  })
  it("known THPT subject still works", () => {
    expect(getSubjectLabel("math")).toBe("Toán")
  })
})

describe("formatRoundLabel", () => {
  it("round_name present → name", () => {
    expect(formatRoundLabel({ name: "Đợt tuyển sinh sớm", code: "DOT_1" })).toBe("Đợt tuyển sinh sớm")
  })
  it("no name → humanizes DOT_n code (not raw 'DOT_2')", () => {
    expect(formatRoundLabel({ name: null, code: "DOT_2" })).toBe("Đợt 2")
    expect(formatRoundLabel({ name: "", code: "DOT-3" })).toBe("Đợt 3")
  })
  it("unknown code format → code as-is; nothing → 'Đợt #id'", () => {
    expect(formatRoundLabel({ code: "SPRING" })).toBe("SPRING")
    expect(formatRoundLabel({ id: 9 })).toBe("Đợt #9")
  })
})
