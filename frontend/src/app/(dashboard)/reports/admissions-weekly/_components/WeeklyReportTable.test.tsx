import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReportRow } from "@/lib/zod/reports";

import { WeeklyReportTable } from "./WeeklyReportTable";

function mkRow(o: {
  label?: string;
  quota?: number | null;
  enrolled?: number;
}): ReportRow {
  return {
    group_key: 1,
    label: o.label ?? "Ngành A",
    code: "X",
    degree_level: null,
    is_bucket: false,
    bucket_kind: null,
    lead: { new_in_week: 0, active_current: 0, consulting_positive_current: 0 },
    admission: {
      profiles_total: 0,
      submitted_in_week: 0,
      admitted_in_week: 0,
      enrolled_in_week: 0,
      submitted_cumulative: 0,
      fee_paid_not_submitted: 0,
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

describe("WeeklyReportTable", () => {
  it("ytd + major + quota → quota-progress column (with Nộp)", () => {
    const totals = mkRow({ quota: 100, enrolled: 40 });
    render(
      <WeeklyReportTable
        rows={[mkRow({ quota: 100, enrolled: 40 })]}
        totals={totals}
        groupBy="major"
        period="ytd"
      />,
    );
    expect(screen.getByText("Tiến độ chỉ tiêu (Nhập học)")).toBeTruthy();
    expect(screen.getByText("Nộp")).toBeTruthy();
    // standalone "Nhập học" count header only exists in the no-quota layout
    expect(screen.queryByText("Nhập học")).toBeNull();
  });

  it("ytd without quota → count layout (standalone Nhập học)", () => {
    const totals = mkRow({ quota: null, enrolled: 0 });
    render(
      <WeeklyReportTable
        rows={[mkRow({ quota: null, enrolled: 0 })]}
        totals={totals}
        groupBy="major"
        period="ytd"
      />,
    );
    expect(screen.queryByText("Tiến độ chỉ tiêu (Nhập học)")).toBeNull();
    expect(screen.getByText("Nhập học")).toBeTruthy();
  });

  it("week period → activity headers", () => {
    const totals = mkRow({});
    render(
      <WeeklyReportTable
        rows={[mkRow({})]}
        totals={totals}
        groupBy="major"
        period="week"
      />,
    );
    expect(screen.getByText("Lead (tư vấn)")).toBeTruthy();
    expect(screen.getByText("Tư vấn+")).toBeTruthy();
  });

  it("ytd quota: bucket row renders placeholder (no NaN bar) + totals row", () => {
    const bucket: ReportRow = {
      ...mkRow({ label: "Chưa phân loại", quota: null, enrolled: 0 }),
      is_bucket: true,
      bucket_kind: "unresolved",
      group_key: null,
    };
    const totals = mkRow({ label: "TỔNG", quota: 100, enrolled: 40 });
    render(
      <WeeklyReportTable
        rows={[bucket]}
        totals={totals}
        groupBy="major"
        period="ytd"
      />,
    );
    // bucket gets an em-dash placeholder instead of a quota bar → no crash
    expect(screen.getByText("Chưa phân loại")).toBeTruthy();
    expect(screen.getByText("TỔNG")).toBeTruthy();
  });
});
