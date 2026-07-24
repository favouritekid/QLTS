import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReportRow } from "@/lib/zod/reports";

import { WeeklyReportTable } from "./WeeklyReportTable";

function mkRow(o: {
  label?: string;
  quota?: number | null;
  enrolled?: number;
  submitted?: number;
  draft?: number;
  feePartial?: number;
  feeFull?: number;
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
      submitted_cumulative: o.submitted ?? 0,
      fee_paid_not_submitted: 0,
      admitted_cumulative: 0,
      enrolled_cumulative: o.enrolled ?? 0,
      draft: o.draft ?? 0,
      fee_hk1_partial: o.feePartial ?? 0,
      fee_hk1_full: o.feeFull ?? 0,
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
  // Chi tiết hoá (khớp heatmap): cột Nháp + Học phí HK1 (một phần/đủ) hiện ở layout
  // lũy-kế và render đúng con số → cockpit đối chiếu trực tiếp với ma trận.
  it("ytd → shows Nháp + Học phí HK1 columns with values", () => {
    const totals = mkRow({
      quota: null,
      submitted: 411,
      draft: 87,
      feePartial: 374,
      feeFull: 7,
    });
    render(
      <WeeklyReportTable
        rows={[
          mkRow({
            quota: null,
            submitted: 411,
            draft: 87,
            feePartial: 374,
            feeFull: 7,
          }),
        ]}
        totals={totals}
        groupBy="major"
        period="ytd"
      />,
    );
    expect(screen.getByText("Nháp")).toBeTruthy();
    expect(screen.getByText("HK1 một phần")).toBeTruthy();
    expect(screen.getByText("HK1 đủ")).toBeTruthy();
    // giá trị hiển thị (hàng dữ liệu + hàng TỔNG → mỗi số xuất hiện ≥1 lần)
    expect(screen.getAllByText("87").length).toBeGreaterThan(0); // nháp
    expect(screen.getAllByText("374").length).toBeGreaterThan(0); // HK1 một phần
    expect(screen.getAllByText("7").length).toBeGreaterThan(0); // HK1 đủ
  });

  // Cột hoạt-động (period=week) KHÔNG có các cột chi tiết hoá lũy-kế.
  it("week period → no Nháp / HK1 columns", () => {
    const totals = mkRow({ submitted: 5, draft: 2 });
    render(
      <WeeklyReportTable
        rows={[mkRow({ submitted: 5, draft: 2 })]}
        totals={totals}
        groupBy="major"
        period="week"
      />,
    );
    expect(screen.queryByText("Nháp")).toBeNull();
    expect(screen.queryByText("HK1 một phần")).toBeNull();
  });

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

  // Regression: unit-scope + tất cả đợt → BE trả quota=null cho MỌI ngành. Caption
  // a11y KHÔNG được nhắc "chỉ tiêu" (cột chỉ tiêu đã ẩn) — nếu không screen reader
  // đọc sai cấu trúc bảng. Ngược lại khi có quota thì caption phải nhắc chỉ tiêu.
  it("caption drops 'chỉ tiêu' when quota is null (unit scope / no quota)", () => {
    const totals = mkRow({ quota: null, enrolled: 0 });
    render(
      <WeeklyReportTable
        rows={[mkRow({ quota: null, enrolled: 0 })]}
        totals={totals}
        groupBy="major"
        period="ytd"
      />,
    );
    const caption = screen.getByText(/Báo cáo tuyển sinh lũy kế năm theo/);
    expect(caption.textContent).not.toMatch(/chỉ tiêu/);
    expect(caption.textContent).toMatch(/nhập học/);
  });

  it("caption mentions 'chỉ tiêu' when a quota is attached (whole-school)", () => {
    const totals = mkRow({ quota: 100, enrolled: 40 });
    render(
      <WeeklyReportTable
        rows={[mkRow({ quota: 100, enrolled: 40 })]}
        totals={totals}
        groupBy="major"
        period="ytd"
      />,
    );
    const caption = screen.getByText(/Báo cáo tuyển sinh lũy kế năm theo/);
    expect(caption.textContent).toMatch(/chỉ tiêu/);
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
