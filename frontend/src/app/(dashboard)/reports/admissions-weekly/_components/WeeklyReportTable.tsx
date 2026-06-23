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
// Show real zeros (a funnel that drops to 0 IS information), just dimmed — never a
// placeholder dash/dot that reads as "missing data".
const count = (n: number) => (
  <span className={n === 0 ? dimZero : undefined}>{nf.format(n)}</span>
);
const money = (s: string) => (
  <span className={parseFloat(s) === 0 ? dimZero : undefined}>{formatVND(s)}</span>
);

function admissionCells(row: ReportRow, period: Period) {
  const a = row.admission;
  return period === "week"
    ? [a.submitted_in_week, a.admitted_in_week, a.enrolled_in_week]
    : [a.submitted_cumulative, a.admitted_cumulative, a.enrolled_cumulative];
}

function rowKey(row: ReportRow): string {
  return row.is_bucket
    ? `bucket-${row.bucket_kind}`
    : `major-${row.group_key ?? row.code ?? row.label}`;
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
  const firstColLabel = groupBy === "major" ? "Ngành" : "Cán bộ";
  const isWeek = period === "week";
  const leadCols = isWeek ? 3 : 2; // "Mới" is a weekly event → only in the week view
  const finCols = isWeek ? 3 : 2;
  const colCount = 1 + leadCols + 3 + finCols;

  const renderRow = (row: ReportRow, isTotal = false) => {
    const [sub, adm, enr] = admissionCells(row, period);
    const hot =
      !isTotal && !row.is_bucket && parseFloat(row.finance.net_cumulative) > 0;
    return (
      <TableRow
        key={isTotal ? "__total__" : rowKey(row)}
        className={cn(
          isTotal && "border-t-2 bg-muted/40 font-semibold",
          row.is_bucket && "text-muted-foreground",
        )}
      >
        <TableCell className="sticky left-0 bg-background">
          <div className="flex items-center gap-2">
            {hot && (
              <span
                className="size-1.5 shrink-0 rounded-full bg-amber-500"
                aria-hidden
              />
            )}
            <span className={cn("font-medium", isTotal && "font-bold")}>
              {row.label}
            </span>
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
        {/* Lead — "Mới" (weekly event) hidden in the cumulative view */}
        {isWeek && (
          <TableCell className="border-l text-right tabular-nums">
            {count(row.lead.new_in_week)}
          </TableCell>
        )}
        <TableCell className={cn("text-right tabular-nums", !isWeek && "border-l")}>
          {count(row.lead.active_current)}
        </TableCell>
        <TableCell className="text-right tabular-nums">
          {count(row.lead.consulting_positive_current)}
        </TableCell>
        {/* Hồ sơ */}
        <TableCell className="border-l bg-muted/20 text-right tabular-nums">
          {count(sub)}
        </TableCell>
        <TableCell className="bg-muted/20 text-right tabular-nums">{count(adm)}</TableCell>
        <TableCell className="bg-muted/20 text-right tabular-nums">{count(enr)}</TableCell>
        {/* Tài chính */}
        {isWeek ? (
          <>
            <TableCell className="border-l text-right tabular-nums">
              {money(row.finance.application_net_in_week)}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {money(row.finance.tuition_net_in_week)}
            </TableCell>
            <TableCell className="text-right font-medium tabular-nums">
              {money(row.finance.net_in_week)}
            </TableCell>
          </>
        ) : (
          <>
            <TableCell className="border-l text-right font-medium tabular-nums">
              {money(row.finance.net_cumulative)}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {count(row.finance.profiles_paid)}
            </TableCell>
          </>
        )}
      </TableRow>
    );
  };

  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/50">
            <TableHead rowSpan={2} className="sticky left-0 bg-muted/50 align-bottom">
              {firstColLabel}
            </TableHead>
            <TableHead colSpan={leadCols} className="border-l text-center">
              Lead (tư vấn)
            </TableHead>
            <TableHead colSpan={3} className="border-l text-center">
              Hồ sơ {isWeek ? "(tuần)" : "(lũy kế)"}
            </TableHead>
            <TableHead colSpan={finCols} className="border-l text-center">
              Tài chính {isWeek ? "(thu tuần)" : "(lũy kế)"}
            </TableHead>
          </TableRow>
          <TableRow className="bg-muted/50 text-xs">
            {isWeek && <TableHead className="border-l text-right">Mới</TableHead>}
            <TableHead className={cn("text-right", !isWeek && "border-l")}>
              Đang theo
            </TableHead>
            <TableHead className="text-right">Tư vấn+</TableHead>
            <TableHead className="border-l text-right">Nộp</TableHead>
            <TableHead className="text-right">Trúng</TableHead>
            <TableHead className="text-right">Nhập học</TableHead>
            {isWeek ? (
              <>
                <TableHead className="border-l text-right">Lệ phí</TableHead>
                <TableHead className="text-right">Học phí</TableHead>
                <TableHead className="text-right">Đã thu</TableHead>
              </>
            ) : (
              <>
                <TableHead className="border-l text-right">Đã thu</TableHead>
                <TableHead className="text-right">HS đã thu</TableHead>
              </>
            )}
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
