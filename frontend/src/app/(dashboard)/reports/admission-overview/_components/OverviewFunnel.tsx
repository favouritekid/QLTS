"use client";

import * as React from "react";

import type { PipelineFunnel } from "@/lib/zod/reports";

const nf = new Intl.NumberFormat("vi-VN");

/**
 * Pipeline funnel — leads by current stage, rendered as a narrowing "reached"
 * funnel. The highest-order final stage (e.g. "Không đi học") is the leak, shown
 * apart; the remaining ordered stages form the path where reached[k] = Σ current
 * for path stages at or below k (a lead at stage k has passed every earlier one).
 * Bar colour is the stage's own configured pipeline colour (consistent with how
 * stages appear elsewhere in the app).
 */
export function OverviewFunnel({ funnel }: { funnel: PipelineFunnel }) {
  const { path, leak, reached, maxReached } = React.useMemo(() => {
    const sorted = [...funnel.stages].sort((a, b) => a.order - b.order);
    const finals = sorted.filter((s) => s.is_final);
    const leakStage = finals.length ? finals[finals.length - 1] : null; // highest-order final = drop-off
    const pathStages = sorted.filter((s) => s !== leakStage);
    const acc: Record<string, number> = {};
    let running = 0;
    for (let i = pathStages.length - 1; i >= 0; i--) {
      running += pathStages[i].current;
      acc[pathStages[i].stage_id] = running;
    }
    return {
      path: pathStages,
      leak: leakStage,
      reached: acc,
      maxReached: pathStages.length ? acc[pathStages[0].stage_id] : 0,
    };
  }, [funnel]);

  if (funnel.total_leads === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Chưa có lead trong lát cắt này.
      </p>
    );
  }

  return (
    <div className="space-y-2.5">
      {path.map((s, i) => {
        const value = reached[s.stage_id] ?? 0;
        const width = maxReached ? (value / maxReached) * 100 : 0;
        const prev = i > 0 ? reached[path[i - 1].stage_id] ?? 0 : null;
        const conv = prev && prev > 0 ? (value / prev) * 100 : null;
        return (
          <div key={s.stage_id}>
            <div className="flex items-baseline justify-between gap-2 text-sm">
              <span className="truncate font-medium">{s.name}</span>
              <span className="shrink-0 font-semibold tabular-nums">
                {nf.format(value)}
              </span>
            </div>
            <div className="mt-1 h-2.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full transition-[width] duration-500"
                style={{
                  width: `${Math.max(2, width)}%`,
                  backgroundColor: s.color_code,
                }}
              />
            </div>
            {conv != null && (
              <div className="mt-0.5 text-xs text-muted-foreground tabular-nums">
                ↓ {conv.toFixed(0)}% chuyển tiếp
              </div>
            )}
          </div>
        );
      })}
      {leak && leak.current > 0 && (
        <div className="border-t pt-2 text-xs text-muted-foreground">
          Rời phễu — {leak.name}:{" "}
          <span className="font-semibold tabular-nums text-rose-500">
            {nf.format(leak.current)}
          </span>
        </div>
      )}
    </div>
  );
}
