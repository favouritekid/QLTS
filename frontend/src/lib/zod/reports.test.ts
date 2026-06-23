import { describe, expect, it } from "vitest";

import { admissionWeeklyReportSchema } from "./reports";

const row = {
  group_key: 1,
  label: "Công nghệ ô tô (6510216)",
  code: "6510216",
  degree_level: "Cao đẳng",
  is_bucket: false,
  bucket_kind: null,
  lead: { new_in_week: 8, active_current: 196, consulting_positive_current: 115 },
  admission: {
    profiles_total: 32,
    submitted_in_week: 19,
    admitted_in_week: 0,
    enrolled_in_week: 0,
    submitted_cumulative: 19,
    admitted_cumulative: 0,
    enrolled_cumulative: 0,
  },
  finance: {
    gross_in_week: "1680000",
    refund_in_week: "0",
    net_in_week: "800000",
    application_net_in_week: "1680000",
    tuition_net_in_week: "16400000",
    net_cumulative: "18080000",
    profiles_paid: 13,
  },
};

const payload = {
  academic_year: 2026,
  round_code: "DOT_2",
  group_by: "major",
  week: {
    iso_year: 2026,
    iso_week: 25,
    week_start: "2026-06-15",
    week_end: "2026-06-21",
    timezone: "Asia/Ho_Chi_Minh",
  },
  scope_unit_id: null,
  attribution: "recomputed-current",
  rows: [row],
  totals: row,
  data_quality: {
    total_profiles: 1,
    ambiguous_profiles: 0,
    unresolved_profiles: 0,
    unassigned_profiles: 0,
  },
};

describe("admissionWeeklyReportSchema", () => {
  it("parses a valid backend payload (money as strings)", () => {
    const parsed = admissionWeeklyReportSchema.parse(payload);
    expect(parsed.rows[0].finance.net_in_week).toBe("800000");
    expect(parsed.totals.admission.profiles_total).toBe(32);
    expect(parsed.group_by).toBe("major");
  });

  it("rejects a money field sent as a number (contract drift)", () => {
    const bad = structuredClone(payload);
    (bad.rows[0].finance as Record<string, unknown>).net_in_week = 800000;
    expect(() => admissionWeeklyReportSchema.parse(bad)).toThrow();
  });

  it("accepts bucket rows with null group_key", () => {
    const bad = structuredClone(payload);
    const r = bad.rows[0] as Record<string, unknown>;
    r.group_key = null;
    r.is_bucket = true;
    r.bucket_kind = "unresolved";
    r.code = null;
    expect(() => admissionWeeklyReportSchema.parse(bad)).not.toThrow();
  });
});
