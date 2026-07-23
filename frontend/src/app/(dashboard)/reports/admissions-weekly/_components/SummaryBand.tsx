"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import { formatVND } from "@/lib/zod/finance";
import type { ReportGroupBy, ReportRow } from "@/lib/zod/reports";

import { quotaTone } from "./WeeklyReportTable";

const nf = new Intl.NumberFormat("vi-VN");

/** "Đạt" = green tier (≥90% chỉ tiêu) — same threshold `quotaTone` paints green. */
const MET = 0.9;

function Card({
  label,
  value,
  hint,
  children,
}: {
  label: string;
  value?: React.ReactNode;
  hint?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      {value !== undefined && (
        <div className="mt-1 text-xl font-bold tabular-nums">{value}</div>
      )}
      {children}
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

export function SummaryBand({
  rows,
  totals,
  groupBy,
}: {
  rows: ReportRow[];
  totals: ReportRow;
  groupBy: ReportGroupBy;
}) {
  const t = totals.admission;
  const hasQuota = groupBy === "major" && t.quota != null && t.quota > 0;
  const ratio = hasQuota ? t.enrolled_cumulative / (t.quota as number) : 0;

  const withQuota = rows.filter(
    (r) => !r.is_bucket && r.admission.quota && r.admission.quota > 0,
  );
  const met = withQuota.filter(
    (r) => r.admission.enrolled_cumulative / (r.admission.quota as number) >= MET,
  ).length;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {hasQuota ? (
        <Card label="Nhập học / Chỉ tiêu" hint={`${Math.round(ratio * 100)}% chỉ tiêu năm`}>
          <div className="mt-1 text-xl font-bold tabular-nums">
            {nf.format(t.enrolled_cumulative)}
            <span className="text-sm font-normal text-muted-foreground">
              {" / "}
              {nf.format(t.quota as number)}
            </span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className={cn("h-full rounded-full", quotaTone(ratio))}
              style={{ width: `${Math.min(100, Math.round(ratio * 100))}%` }}
            />
          </div>
        </Card>
      ) : (
        <Card
          label="Nhập học"
          hint="lũy kế năm"
          value={nf.format(t.enrolled_cumulative)}
        />
      )}
      <Card label="Trúng tuyển" hint="lũy kế năm" value={nf.format(t.admitted_cumulative)} />
      <Card
        label="Đang theo"
        hint="còn trong phễu"
        value={nf.format(totals.lead.active_current)}
      />
      <Card
        label="Thu ròng tuyển sinh"
        hint="lệ phí XT + học phí · lũy kế năm"
        value={formatVND(totals.finance.net_cumulative)}
      />
      {hasQuota ? (
        <Card
          label="Ngành đạt ≥90%"
          hint={`/ ${withQuota.length} ngành có chỉ tiêu`}
          value={met}
        />
      ) : (
        <Card label="Hồ sơ đã nộp" hint="lũy kế năm · đếm theo hồ sơ" value={nf.format(t.submitted_cumulative)} />
      )}
      <Card
        label="Đã đóng lệ phí XT · còn nháp"
        hint="đã đóng lệ phí xét tuyển nhưng hồ sơ chưa nộp — cần nhắc hoàn tất"
        value={nf.format(t.fee_paid_not_submitted)}
      />
    </div>
  );
}
