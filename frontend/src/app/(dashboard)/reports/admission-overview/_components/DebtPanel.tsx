"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { formatVND } from "@/lib/zod/finance";
import type { DebtReportSummary } from "@/types/finance.types";

const nf = new Intl.NumberFormat("vi-VN");

const AGING = [
  { field: "bucket_0_30", label: "Trong hạn · 0–30 ngày", accent: "bg-amber-500" },
  { field: "bucket_31_60", label: "Quá hạn · 31–60 ngày", accent: "bg-orange-500" },
  { field: "bucket_over_60", label: "Quá hạn · > 60 ngày", accent: "bg-rose-500" },
] as const;

export function DebtPanel({
  summary,
  isLoading,
}: {
  summary?: DebtReportSummary;
  isLoading: boolean;
}) {
  if (isLoading && !summary) {
    return <Skeleton className="h-40 w-full" />;
  }
  if (!summary) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Chưa tải được công nợ.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <div>
          <div className="text-xs text-muted-foreground">Công nợ học phí còn lại</div>
          <div className="text-2xl font-bold tabular-nums text-rose-500">
            {formatVND(summary.total_outstanding)}
          </div>
        </div>
        <div className="text-sm text-muted-foreground">
          Đã thu{" "}
          <span className="font-semibold text-foreground">
            {formatVND(summary.total_paid)}
          </span>{" "}
          / phải thu {formatVND(summary.total_expected)}
          <span className="ml-2">· {nf.format(summary.debtor_count)} hồ sơ còn nợ</span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {AGING.map((a) => (
          <div key={a.field} className="rounded-lg border p-3">
            <div className={`mb-1.5 h-1 w-6 rounded-full ${a.accent}`} />
            <div className="text-xs text-muted-foreground">{a.label}</div>
            <div className="mt-0.5 text-lg font-bold tabular-nums">
              {formatVND(summary[a.field])}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
