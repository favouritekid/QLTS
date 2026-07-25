import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AdmissionWeeklyReport } from "@/lib/zod/reports";
import type {
  DebtReportResponse,
  DebtReportRow,
} from "@/types/finance.types";

import { ActionNeeded } from "./ActionNeeded";

/** Report with NO other action items (no behind-quota rows, no prepay, no dq) so a
 *  test isolates the debt fail-closed behaviour. */
function cleanReport(): AdmissionWeeklyReport {
  return {
    academic_year: 2026,
    round_code: null,
    group_by: "major",
    week: {
      iso_year: 2026,
      iso_week: 30,
      week_start: "2026-07-20",
      week_end: "2026-07-26",
    },
    scope_unit_id: null,
    attribution: "recomputed-current",
    rows: [],
    totals: {
      group_key: null,
      label: "TỔNG",
      code: null,
      degree_level: null,
      is_bucket: false,
      bucket_kind: null,
      lead: {
        new_in_week: 0,
        active_current: 0,
        consulting_positive_current: 0,
      },
      admission: {
        profiles_total: 0,
        submitted_in_week: 0,
        admitted_in_week: 0,
        enrolled_in_week: 0,
        submitted_cumulative: 0,
        fee_paid_not_submitted: 0, // no prepay-draft alert
        admitted_cumulative: 0,
        enrolled_cumulative: 0,
        quota: null,
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
    },
    data_quality: {
      total_profiles: 0,
      ambiguous_profiles: 0,
      unresolved_profiles: 0,
      unassigned_profiles: 0,
    },
  } as unknown as AdmissionWeeklyReport;
}

function debtRow(bucket: DebtReportRow["aging_bucket"], out: string): DebtReportRow {
  return {
    admission_profile_id: 1,
    profile_code: "HS1",
    profile_name: "Nguyễn Văn A",
    unit_id: 14,
    unit_name: "Phòng Tuyển Sinh",
    academic_year: 2026,
    admission_round_id: null,
    fee_types: ["tuition"],
    invoice_count: 1,
    total_expected: out,
    total_paid: "0",
    total_outstanding: out,
    days_overdue: 70,
    aging_bucket: bucket,
  };
}

function debtResponse(items: DebtReportRow[]): DebtReportResponse {
  return {
    items,
    summary: {
      debtor_count: items.length,
      total_expected: "0",
      total_paid: "0",
      total_outstanding: "0",
      bucket_0_30: "0",
      bucket_31_60: "0",
      bucket_over_60: "0",
    },
  };
}

describe("ActionNeeded — debt fail-closed", () => {
  it("debt loaded + empty → genuine all-clear", () => {
    render(
      <ActionNeeded report={cleanReport()} debt={debtResponse([])} />,
    );
    expect(screen.getByText(/Không có mục cần xử lý gấp/)).toBeTruthy();
  });

  it("debt still LOADING → NOT all-clear, shows a checking notice", () => {
    render(
      <ActionNeeded report={cleanReport()} debt={undefined} debtLoading />,
    );
    expect(screen.queryByText(/Không có mục cần xử lý gấp/)).toBeNull();
    expect(screen.getByText(/Đang kiểm tra công nợ/)).toBeTruthy();
  });

  it("debt ERROR → NOT all-clear, warns it could not be checked", () => {
    render(
      <ActionNeeded report={cleanReport()} debt={undefined} debtError />,
    );
    expect(screen.queryByText(/Không có mục cần xử lý gấp/)).toBeNull();
    expect(screen.getByText(/Chưa kiểm tra được công nợ/)).toBeTruthy();
  });

  it("debt loaded with >60 overdue → surfaces the critical alert", () => {
    render(
      <ActionNeeded
        report={cleanReport()}
        debt={debtResponse([debtRow("over_60", "5000000")])}
      />,
    );
    expect(screen.getByText(/Công nợ quá hạn > 60 ngày/)).toBeTruthy();
    expect(screen.queryByText(/Không có mục cần xử lý gấp/)).toBeNull();
  });
});
