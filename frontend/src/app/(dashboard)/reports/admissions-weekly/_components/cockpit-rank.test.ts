import { describe, expect, it } from "vitest";

import type { ReportRow } from "@/lib/zod/reports";

import { rankByQuotaGap } from "./cockpit-rank";

function mkRow(o: {
  label: string;
  quota?: number | null;
  enrolled?: number;
  bucket?: boolean;
}): ReportRow {
  return {
    group_key: o.bucket ? null : 1,
    label: o.label,
    code: null,
    degree_level: null,
    is_bucket: !!o.bucket,
    bucket_kind: o.bucket ? "unresolved" : null,
    lead: { new_in_week: 0, active_current: 0, consulting_positive_current: 0 },
    admission: {
      profiles_total: 0,
      submitted_in_week: 0,
      admitted_in_week: 0,
      enrolled_in_week: 0,
      submitted_cumulative: 0,
      admitted_cumulative: 0,
      enrolled_cumulative: o.enrolled ?? 0,
      quota: o.quota ?? null,
    },
    conversion: { submit_to_admit: null, admit_to_enroll: null },
    finance: {
      gross_in_week: "0",
      refund_in_week: "0",
      net_in_week: "0",
      application_net_in_week: "0",
      tuition_net_in_week: "0",
      net_cumulative: "0",
      profiles_paid: 0,
    },
  };
}

describe("rankByQuotaGap", () => {
  it("most-behind chỉ tiêu first; no-target then bucket last", () => {
    const out = rankByQuotaGap([
      mkRow({ label: "B-90%", quota: 100, enrolled: 90 }),
      mkRow({ label: "bucket", bucket: true }),
      mkRow({ label: "A-20%", quota: 100, enrolled: 20 }),
      mkRow({ label: "no-target", quota: null, enrolled: 5 }),
    ]).map((r) => r.label);
    expect(out).toEqual(["A-20%", "B-90%", "no-target", "bucket"]);
  });

  it("does not mutate the input array", () => {
    const input = [
      mkRow({ label: "x", quota: 100, enrolled: 50 }),
      mkRow({ label: "y", quota: 100, enrolled: 10 }),
    ];
    const before = input.map((r) => r.label);
    rankByQuotaGap(input);
    expect(input.map((r) => r.label)).toEqual(before);
  });

  it("treats quota=0 as no-target (avoids divide-by-zero)", () => {
    const out = rankByQuotaGap([
      mkRow({ label: "zero-quota", quota: 0, enrolled: 0 }),
      mkRow({ label: "behind", quota: 100, enrolled: 10 }),
    ]).map((r) => r.label);
    expect(out).toEqual(["behind", "zero-quota"]); // 0 → Infinity → sinks to bottom
  });

  it("breaks no-target (Infinity) ties by enrolled desc", () => {
    const out = rankByQuotaGap([
      mkRow({ label: "noq-5", quota: null, enrolled: 5 }),
      mkRow({ label: "noq-20", quota: null, enrolled: 20 }),
    ]).map((r) => r.label);
    expect(out).toEqual(["noq-20", "noq-5"]);
  });
});
