"use client";

import * as React from "react";

import type { PipelineFunnel } from "@/lib/zod/reports";

const nf = new Intl.NumberFormat("vi-VN");

/**
 * Pipeline funnel — pure renderer (thin-client). The backend owns the funnel
 * model: each stage carries `reached` (cumulative on the success path),
 * `conversion_pct`, and an `is_leak` flag for the drop-off stage. This component
 * only lays them out and normalises bar width to the widest path stage. Bar
 * colour is the stage's own configured pipeline colour.
 */
export function OverviewFunnel({ funnel }: { funnel: PipelineFunnel }) {
  const path = React.useMemo(
    () =>
      funnel.stages.filter((s) => !s.is_leak).sort((a, b) => a.order - b.order),
    [funnel],
  );
  const maxReached = path.length ? Math.max(...path.map((s) => s.reached)) : 0;

  if (funnel.total_leads === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Chưa có lead trong lát cắt này.
      </p>
    );
  }

  return (
    <div className="space-y-2.5">
      {path.map((s) => {
        const width = maxReached ? (s.reached / maxReached) * 100 : 0;
        return (
          <div key={s.stage_id}>
            <div className="flex items-baseline justify-between gap-2 text-sm">
              <span className="truncate font-medium">{s.name}</span>
              <span className="shrink-0 font-semibold tabular-nums">
                {nf.format(s.reached)}
              </span>
            </div>
            <div className="mt-1 h-2.5 w-full overflow-hidden rounded-full bg-muted">
              {/* Sàn 2% CHỈ áp cho bậc có dữ liệu (reached>0) — bậc =0 vẽ 0% để
                  không biểu diễn sai (finding: reached=0 mà vẫn có thanh). */}
              <div
                className="h-full rounded-full transition-[width] duration-500"
                style={{
                  width: `${s.reached > 0 ? Math.max(2, width) : 0}%`,
                  backgroundColor: s.color_code,
                }}
              />
            </div>
            {s.conversion_pct != null && (
              <div className="mt-0.5 text-xs text-muted-foreground tabular-nums">
                ↓ {s.conversion_pct.toFixed(0)}% chuyển tiếp
              </div>
            )}
          </div>
        );
      })}
      {funnel.leaked > 0 && (
        <div className="border-t pt-2 text-xs text-muted-foreground">
          Rời phễu (từ chối · rút · không đi học):{" "}
          <span className="font-semibold tabular-nums text-rose-500">
            {nf.format(funnel.leaked)}
          </span>
        </div>
      )}
    </div>
  );
}
