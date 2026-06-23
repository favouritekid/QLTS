"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { formatVND } from "@/lib/zod/finance";
import type { ReportGroupBy, ReportRow } from "@/lib/zod/reports";

export type Period = "week" | "ytd";

const nf = new Intl.NumberFormat("vi-VN");
const dimZero = "text-muted-foreground/40";

const count = (n: number) => (
  <span className={n === 0 ? dimZero : undefined}>{nf.format(n)}</span>
);
const money = (s: string) => (
  <span className={parseFloat(s) === 0 ? dimZero : undefined}>{formatVND(s)}</span>
);
const pct = (r: number | null) =>
  r === null ? <span className={dimZero}>—</span> : `${Math.round(r * 100)}%`;

// Quota-progress thresholds are PRESENTATION (coloring a returned ratio), not a
// business rule — kept here, not on the backend contract. Shared with SummaryBand.
export function quotaTone(ratio: number): string {
  if (ratio >= 0.9) return "bg-emerald-500";
  if (ratio >= 0.5) return "bg-amber-500";
  return "bg-rose-500";
}

function QuotaProgress({
  enrolled,
  quota,
}: {
  enrolled: number;
  quota: number | null;
}) {
  if (quota == null || quota === 0) {
    return <span className={cn("text-xs", dimZero)}>chưa đặt chỉ tiêu</span>;
  }
  const ratio = enrolled / quota;
  return (
    <div className="min-w-[130px] space-y-1">
      <div className="flex items-center justify-between text-xs tabular-nums">
        <span>
          {nf.format(enrolled)} / {nf.format(quota)}
        </span>
        <span className="font-semibold">{Math.round(ratio * 100)}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full", quotaTone(ratio))}
          style={{ width: `${Math.min(100, Math.round(ratio * 100))}%` }}
        />
      </div>
    </div>
  );
}

function rowKey(row: ReportRow): string {
  return row.is_bucket
    ? `bucket-${row.bucket_kind}`
    : `major-${row.group_key ?? row.code ?? row.label}`;
}

function FirstCell({
  row,
  isTotal,
  dot,
}: {
  row: ReportRow;
  isTotal: boolean;
  dot?: string | null;
}) {
  return (
    <TableCell className="sticky left-0 bg-background">
      <div className="flex items-center gap-2">
        {dot && (
          <span className={cn("size-2 shrink-0 rounded-full", dot)} aria-hidden />
        )}
        <span className={cn("font-medium", isTotal && "font-bold")}>{row.label}</span>
        {row.degree_level && (
          <span className="rounded border px-1 text-[10px] text-muted-foreground">
            {row.degree_level}
          </span>
        )}
      </div>
      {row.code && (
        <span className="block text-xs text-muted-foreground">{row.code}</span>
      )}
    </TableCell>
  );
}

export function WeeklyReportTable({
  rows,
  totals,
  groupBy,
  period,
}: {
  rows: ReportRow[];
  totals: ReportRow;
  groupBy: ReportGroupBy;
  period: Period;
}) {
  const isMajor = groupBy === "major";
  const firstColLabel = isMajor ? "Ngành" : "Cán bộ";

  // =========================================================== COCKPIT (lũy kế)
  if (period === "ytd") {
    // Quota progress only renders when the backend attached a quota (major view,
    // không lọc đợt). Otherwise fall back to the count layout (Nộp/Trúng/NH).
    const showQuota = isMajor && totals.admission.quota != null;
    const colCount = 8;

    const renderRow = (row: ReportRow, isTotal = false) => {
      const a = row.admission;
      const ratio = a.quota && a.quota > 0 ? a.enrolled_cumulative / a.quota : null;
      const dot =
        showQuota && !isTotal && !row.is_bucket && ratio !== null
          ? quotaTone(ratio)
          : null;
      return (
        <TableRow
          key={isTotal ? "__total__" : rowKey(row)}
          className={cn(
            isTotal && "border-t-2 bg-muted/40 font-semibold",
            row.is_bucket && "text-muted-foreground",
          )}
        >
          <FirstCell row={row} isTotal={isTotal} dot={dot} />
          {showQuota && (
            <TableCell className="border-l">
              {row.is_bucket ? (
                <span className={dimZero}>—</span>
              ) : (
                <QuotaProgress enrolled={a.enrolled_cumulative} quota={a.quota} />
              )}
            </TableCell>
          )}
          <TableCell
            className={cn("text-right tabular-nums", !showQuota && "border-l")}
          >
            {count(a.submitted_cumulative)}
          </TableCell>
          <TableCell className="text-right tabular-nums">
            {count(a.admitted_cumulative)}
          </TableCell>
          {!showQuota && (
            <TableCell className="text-right tabular-nums">
              {count(a.enrolled_cumulative)}
            </TableCell>
          )}
          <TableCell className="border-l text-right tabular-nums">
            {pct(row.conversion.submit_to_admit)}
          </TableCell>
          <TableCell className="text-right tabular-nums">
            {pct(row.conversion.admit_to_enroll)}
          </TableCell>
          <TableCell className="border-l text-right tabular-nums">
            {count(row.lead.active_current)}
          </TableCell>
          <TableCell className="text-right font-medium tabular-nums">
            {money(row.finance.net_cumulative)}
          </TableCell>
        </TableRow>
      );
    };

    return (
      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50 text-xs">
              <TableHead className="sticky left-0 bg-muted/50">{firstColLabel}</TableHead>
              {showQuota && (
                <TableHead className="border-l">Tiến độ chỉ tiêu (Nhập học)</TableHead>
              )}
              <TableHead className={cn("text-right", !showQuota && "border-l")}>
                Nộp
              </TableHead>
              <TableHead className="text-right">Trúng</TableHead>
              {!showQuota && <TableHead className="text-right">Nhập học</TableHead>}
              <TableHead className="border-l text-right">Nộp→Trúng</TableHead>
              <TableHead className="text-right">Trúng→NH</TableHead>
              <TableHead className="border-l text-right">Đang theo</TableHead>
              <TableHead className="text-right">Đã thu</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={colCount}
                  className="py-8 text-center text-muted-foreground"
                >
                  Không có dữ liệu cho kỳ đã chọn.
                </TableCell>
              </TableRow>
            ) : (
              <>
                {rows.map((r) => renderRow(r))}
                {renderRow(totals, true)}
              </>
            )}
          </TableBody>
        </Table>
      </div>
    );
  }

  // =========================================================== ACTIVITY (tuần)
  const colCount = 1 + 3 + 3 + 3;
  const renderRow = (row: ReportRow, isTotal = false) => (
    <TableRow
      key={isTotal ? "__total__" : rowKey(row)}
      className={cn(
        isTotal && "border-t-2 bg-muted/40 font-semibold",
        row.is_bucket && "text-muted-foreground",
      )}
    >
      <FirstCell row={row} isTotal={isTotal} />
      <TableCell className="border-l text-right tabular-nums">
        {count(row.lead.new_in_week)}
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {count(row.lead.active_current)}
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {count(row.lead.consulting_positive_current)}
      </TableCell>
      <TableCell className="border-l bg-muted/20 text-right tabular-nums">
        {count(row.admission.submitted_in_week)}
      </TableCell>
      <TableCell className="bg-muted/20 text-right tabular-nums">
        {count(row.admission.admitted_in_week)}
      </TableCell>
      <TableCell className="bg-muted/20 text-right tabular-nums">
        {count(row.admission.enrolled_in_week)}
      </TableCell>
      <TableCell className="border-l text-right tabular-nums">
        {money(row.finance.application_net_in_week)}
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {money(row.finance.tuition_net_in_week)}
      </TableCell>
      <TableCell className="text-right font-medium tabular-nums">
        {money(row.finance.net_in_week)}
      </TableCell>
    </TableRow>
  );

  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/50">
            <TableHead rowSpan={2} className="sticky left-0 bg-muted/50 align-bottom">
              {firstColLabel}
            </TableHead>
            <TableHead colSpan={3} className="border-l text-center">
              Lead (tư vấn)
            </TableHead>
            <TableHead colSpan={3} className="border-l text-center">
              Hồ sơ (tuần)
            </TableHead>
            <TableHead colSpan={3} className="border-l text-center">
              Tài chính (thu tuần)
            </TableHead>
          </TableRow>
          <TableRow className="bg-muted/50 text-xs">
            <TableHead className="border-l text-right">Mới</TableHead>
            <TableHead className="text-right">Đang theo</TableHead>
            <TableHead className="text-right">Tư vấn+</TableHead>
            <TableHead className="border-l text-right">Nộp</TableHead>
            <TableHead className="text-right">Trúng</TableHead>
            <TableHead className="text-right">Nhập học</TableHead>
            <TableHead className="border-l text-right">Lệ phí</TableHead>
            <TableHead className="text-right">Học phí</TableHead>
            <TableHead className="text-right">Đã thu</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={colCount}
                className="py-8 text-center text-muted-foreground"
              >
                Không có dữ liệu cho kỳ đã chọn.
              </TableCell>
            </TableRow>
          ) : (
            <>
              {rows.map((r) => renderRow(r))}
              {renderRow(totals, true)}
            </>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
