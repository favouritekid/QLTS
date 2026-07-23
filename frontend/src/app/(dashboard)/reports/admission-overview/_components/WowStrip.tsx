"use client";

import * as React from "react";
import { Minus, TrendingDown, TrendingUp } from "lucide-react";

import { cn } from "@/lib/utils";
import type { AdmissionWow, WowMovement } from "@/lib/zod/reports";

const nf = new Intl.NumberFormat("vi-VN");
const dm = (s: string) => `${s.slice(8, 10)}/${s.slice(5, 7)}`;

/** 3 milestone tổng — nhãn TRUNG THỰC: đây là sự kiện MỚI trong tuần, KHÔNG lũy kế. */
const MILESTONES: { key: "submitted" | "admitted" | "enrolled"; label: string }[] = [
  { key: "submitted", label: "Nộp hồ sơ" },
  { key: "admitted", label: "Đủ điều kiện" },
  { key: "enrolled", label: "Nhập học" },
];

/** Biến động 1 milestone: mũi tên + dấu tải nghĩa (màu KHÔNG là tín hiệu duy nhất). */
function DeltaChip({ mv }: { mv: WowMovement }) {
  const up = mv.delta > 0;
  const down = mv.delta < 0;
  const Icon = up ? TrendingUp : down ? TrendingDown : Minus;
  const sign = up ? "+" : down ? "−" : "";
  const pct =
    mv.delta_pct !== null
      ? `${mv.delta_pct > 0 ? "+" : mv.delta_pct < 0 ? "−" : ""}${nf.format(
          Math.abs(mv.delta_pct),
        )}%`
      : mv.count_current > 0
        ? "mới"
        : null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium tabular-nums",
        up && "text-emerald-600 dark:text-emerald-400",
        down && "text-rose-600 dark:text-rose-400",
        !up && !down && "text-muted-foreground",
      )}
    >
      <Icon aria-hidden className="size-3.5" />
      <span>
        {sign}
        {nf.format(Math.abs(mv.delta))}
      </span>
      {pct && <span className="text-muted-foreground">({pct})</span>}
      <span className="sr-only">
        {up ? "tăng" : down ? "giảm" : "không đổi"} so tuần trước
      </span>
    </span>
  );
}

/**
 * Nhịp so tuần trước — biến động 3 milestone giữa 2 tuần ISO ĐÃ HOÀN TẤT (BE loại
 * tuần đang chạy). Chỉ render tổng (BE cũng tính theo ngành/cán bộ). Thin-client:
 * KHÔNG suy diễn "nguy cơ", chỉ hiển thị tăng/giảm.
 */
export function WowStrip({ wow }: { wow: AdmissionWow }) {
  if (wow.insufficient_data || !wow.comparison) {
    return (
      <p className="text-sm text-muted-foreground">
        Chưa đủ 2 tuần đã hoàn tất để so nhịp tuần (năm chưa bắt đầu hoặc mới mở).
      </p>
    );
  }

  const cur = wow.comparison.latest_complete_week;
  const prev = wow.comparison.previous_complete_week;

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Sự kiện <strong>mới phát sinh</strong> trong tuần (không phải lũy kế). Tuần{" "}
        {cur.iso_week} ({dm(cur.week_start)}–{dm(cur.week_end)}) so tuần {prev.iso_week}{" "}
        ({dm(prev.week_start)}–{dm(prev.week_end)}).
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        {MILESTONES.map(({ key, label }) => {
          const mv = wow.totals[key];
          return (
            <div key={key} className="rounded-lg border bg-muted/30 p-3">
              <div className="text-xs text-muted-foreground">{label}</div>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-2xl font-bold tabular-nums">
                  {nf.format(mv.count_current)}
                </span>
                <DeltaChip mv={mv} />
              </div>
              <div className="mt-0.5 text-xs text-muted-foreground tabular-nums">
                Tuần trước: {nf.format(mv.count_previous)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
