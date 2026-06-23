import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReportRow } from "@/lib/zod/reports";

import { SummaryBand } from "./SummaryBand";

function mkRow(o: {
  label?: string;
  quota?: number | null;
  enrolled?: number;
  admitted?: number;
  submitted?: number;
  active?: number;
  netCum?: string;
}): ReportRow {
  return {
    group_key: 1,
    label: o.label ?? "Ngành",
    code: null,
    degree_level: null,
    is_bucket: false,
    bucket_kind: null,
    lead: {
      new_in_week: 0,
      active_current: o.active ?? 0,
      consulting_positive_current: 0,
    },
    admission: {
      profiles_total: 0,
      submitted_in_week: 0,
      admitted_in_week: 0,
      enrolled_in_week: 0,
      submitted_cumulative: o.submitted ?? 0,
      admitted_cumulative: o.admitted ?? 0,
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
      net_cumulative: o.netCum ?? "0",
      profiles_paid: 0,
    },
  };
}

describe("SummaryBand", () => {
  it("major + quota → Nhập học/Chỉ tiêu, Đã thu money, ngành đạt count", () => {
    const rows = [
      mkRow({ label: "A", quota: 100, enrolled: 95 }), // 95% → đạt
      mkRow({ label: "B", quota: 100, enrolled: 40 }),
      mkRow({ label: "C", quota: 100, enrolled: 10 }),
    ];
    const totals = mkRow({
      quota: 300,
      enrolled: 145,
      admitted: 280,
      active: 700,
      netCum: "6260000",
    });
    render(<SummaryBand rows={rows} totals={totals} groupBy="major" />);
    expect(screen.getByText("Nhập học / Chỉ tiêu")).toBeTruthy();
    expect(screen.getByText("6.260.000 ₫")).toBeTruthy(); // Đã thu (money string)
    expect(screen.getByText("/ 3 ngành có chỉ tiêu")).toBeTruthy();
    // scope the count to its own card so it can't collide with other numbers
    const card = screen.getByText("Ngành đạt ≥90%").parentElement as HTMLElement;
    expect(within(card).getByText("1")).toBeTruthy(); // exactly 1 ngành ≥90%
  });

  it("officer (no quota) → count fallback cards", () => {
    const totals = mkRow({ quota: null, enrolled: 50, submitted: 120, active: 300 });
    render(<SummaryBand rows={[]} totals={totals} groupBy="officer" />);
    expect(screen.queryByText("Nhập học / Chỉ tiêu")).toBeNull();
    expect(screen.getByText("Nhập học")).toBeTruthy();
    expect(screen.getByText("Hồ sơ nộp")).toBeTruthy();
  });

  it("quota=0 totals → treated as no quota (count fallback)", () => {
    const totals = mkRow({ quota: 0, enrolled: 0 });
    render(<SummaryBand rows={[]} totals={totals} groupBy="major" />);
    expect(screen.queryByText("Nhập học / Chỉ tiêu")).toBeNull();
    expect(screen.getByText("Nhập học")).toBeTruthy();
  });
});
