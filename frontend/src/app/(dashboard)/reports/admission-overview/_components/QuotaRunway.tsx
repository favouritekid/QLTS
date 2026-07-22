"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import type { ReportRow } from "@/lib/zod/reports";

const nf = new Intl.NumberFormat("vi-VN");

/** Same thresholds as the weekly cockpit's ``quotaTone``. */
function tone(ratio: number): string {
  if (ratio >= 0.9) return "bg-emerald-500";
  if (ratio >= 0.5) return "bg-amber-500";
  return "bg-rose-500";
}

/**
 * Đường băng chỉ tiêu — mỗi ngành một thanh tiến độ nhập-học / chỉ-tiêu, sắp theo
 * mức cần đẩy (tỉ lệ đạt tăng dần → ngành nguy cơ hiện đầu). Quota chỉ có ở lát
 * cắt toàn-trường · mọi-đợt (BE trả quota=null khi lọc đợt/đơn vị) → khi thiếu
 * quota, xếp theo số nhập học và ẩn cột tiến độ.
 */
export function QuotaRunway({ rows }: { rows: ReportRow[] }) {
  const majors = React.useMemo(
    () => rows.filter((r) => !r.is_bucket && r.group_key != null),
    [rows],
  );
  const hasQuota = React.useMemo(
    () => majors.some((r) => r.admission.quota != null && r.admission.quota > 0),
    [majors],
  );

  const ranked = React.useMemo(() => {
    const withRatio = majors.map((r) => {
      const q = r.admission.quota ?? 0;
      const ratio = q > 0 ? r.admission.enrolled_cumulative / q : null;
      return { row: r, ratio };
    });
    withRatio.sort((a, b) => {
      if (hasQuota) {
        // no-quota rows sink; otherwise most-behind (lowest ratio) first
        if (a.ratio == null) return 1;
        if (b.ratio == null) return -1;
        return a.ratio - b.ratio;
      }
      return b.row.admission.enrolled_cumulative - a.row.admission.enrolled_cumulative;
    });
    return withRatio;
  }, [majors, hasQuota]);

  const maxEnrolled = React.useMemo(
    () => Math.max(1, ...majors.map((r) => r.admission.enrolled_cumulative)),
    [majors],
  );

  if (majors.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Chưa có ngành nào phát sinh hồ sơ trong lát cắt này.
      </p>
    );
  }

  return (
    <div className="space-y-1.5">
      {!hasQuota && (
        <p className="pb-1 text-xs text-muted-foreground">
          Lát cắt này không có chỉ tiêu năm — xếp theo số nhập học.
        </p>
      )}
      {ranked.map(({ row, ratio }) => {
        const enrolled = row.admission.enrolled_cumulative;
        const quota = row.admission.quota;
        const width =
          ratio != null
            ? Math.min(100, ratio * 100)
            : (enrolled / maxEnrolled) * 100;
        return (
          <div
            key={row.group_key}
            className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 rounded-md px-1.5 py-1.5 hover:bg-muted/50 sm:grid-cols-[minmax(120px,200px)_1fr_auto]"
          >
            <div className="flex min-w-0 items-center gap-2">
              {row.code && (
                <span className="hidden shrink-0 font-mono text-[10px] text-muted-foreground sm:inline">
                  {row.code}
                </span>
              )}
              <span className="truncate text-sm font-medium" title={row.label}>
                {row.label.replace(/\s*\([^)]*\)\s*$/, "")}
              </span>
            </div>
            <div className="col-span-2 h-2.5 overflow-hidden rounded-full bg-muted sm:col-span-1">
              <div
                className={cn(
                  "h-full rounded-full transition-[width] duration-500",
                  ratio != null ? tone(ratio) : "bg-primary",
                )}
                style={{ width: `${Math.max(2, width)}%` }}
              />
            </div>
            <div className="flex items-baseline justify-end gap-1.5 tabular-nums">
              <span className="text-sm font-semibold">{nf.format(enrolled)}</span>
              {quota != null && quota > 0 && (
                <>
                  <span className="text-xs text-muted-foreground">
                    /{nf.format(quota)}
                  </span>
                  <span className="w-9 text-right text-xs text-muted-foreground">
                    {ratio != null ? Math.round(ratio * 100) : 0}%
                  </span>
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
