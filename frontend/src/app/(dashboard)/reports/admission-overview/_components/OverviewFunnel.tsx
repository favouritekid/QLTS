"use client";

import * as React from "react";

import type { PipelineFunnel } from "@/lib/zod/reports";

const nf = new Intl.NumberFormat("vi-VN");

// "Tạm âm" (từ chối, còn chăm) — vạch sọc chéo amber để LUÔN phân biệt được với
// màu nền đặc của bậc (vd stg02 "Đang tư vấn" cũng amber #F59E0B) và với hồng "đã rời".
const AT_RISK_STRIPE =
  "repeating-linear-gradient(45deg,#f59e0b 0,#f59e0b 3px,#fef08a 3px,#fef08a 6px)";

/**
 * Pipeline distribution — pure renderer (thin-client). The backend owns the model:
 * each stage carries `current` (số lead ĐANG Ở bậc đó — mỗi lead đếm đúng 1 lần theo
 * pipeline_stage_id, khớp Pipeline Board / Lead List), `leaked_here` (đã rời phễu —
 * negative-terminal) và `at_risk_here` (tạm âm chưa đóng — "Từ chối tư vấn"). Đây là
 * PHÂN BỐ hiện trạng, KHÔNG phải funnel lũy kế. Thanh mỗi bậc tách 3 phần: tích cực
 * (màu bậc) · tạm âm (hổ phách) · đã rời (hồng). tích cực = current − đã rời − tạm âm.
 */
export function OverviewFunnel({ funnel }: { funnel: PipelineFunnel }) {
  const stages = React.useMemo(
    () => [...funnel.stages].sort((a, b) => a.order - b.order),
    [funnel],
  );
  const maxCurrent = stages.length
    ? Math.max(...stages.map((s) => s.current))
    : 0;
  const hasAtRisk = stages.some((s) => s.at_risk_here > 0);

  if (funnel.total_leads === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Chưa có lead trong lát cắt này.
      </p>
    );
  }

  return (
    <div className="space-y-2.5">
      {(hasAtRisk || funnel.leaked > 0) && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
          {hasAtRisk && (
            <span className="inline-flex items-center gap-1">
              <span
                className="inline-block size-2.5 rounded-sm"
                style={{ backgroundImage: AT_RISK_STRIPE }}
              />
              tạm âm · từ chối (còn chăm)
            </span>
          )}
          {funnel.leaked > 0 && (
            <span className="inline-flex items-center gap-1">
              <span className="inline-block size-2.5 rounded-sm bg-rose-400" />
              đã rời phễu (đã đóng)
            </span>
          )}
        </div>
      )}
      {stages.map((s) => {
        const active = Math.max(0, s.current - s.leaked_here - s.at_risk_here);
        const barPct = maxCurrent ? (s.current / maxCurrent) * 100 : 0;
        // Trong thanh: tích cực (màu bậc) · tạm âm (hổ phách) · đã rời (hồng), tỉ lệ
        // theo current. Segment sau cùng có mặt lấy flex-1 để không hở do làm tròn.
        const activePct = s.current ? (active / s.current) * 100 : 0;
        const atRiskPct = s.current ? (s.at_risk_here / s.current) * 100 : 0;
        return (
          <div key={s.stage_id}>
            <div className="flex items-baseline justify-between gap-2 text-sm">
              <span className="truncate font-medium">{s.name}</span>
              <span className="shrink-0 font-semibold tabular-nums">
                {nf.format(s.current)}
              </span>
            </div>
            <div className="mt-1 h-2.5 w-full overflow-hidden rounded-full bg-muted">
              {/* Sàn 2% cho bậc có lead (current>0) để không mất hút; =0 vẽ 0%. */}
              <div
                className="flex h-full overflow-hidden rounded-full"
                style={{ width: `${s.current > 0 ? Math.max(2, barPct) : 0}%` }}
              >
                <div
                  className="h-full"
                  style={{ width: `${activePct}%`, backgroundColor: s.color_code }}
                />
                {s.at_risk_here > 0 && (
                  <div
                    className="h-full"
                    style={{
                      backgroundImage: AT_RISK_STRIPE,
                      ...(s.leaked_here > 0
                        ? { width: `${atRiskPct}%` }
                        : { flex: 1 }),
                    }}
                  />
                )}
                {s.leaked_here > 0 && (
                  <div className="h-full flex-1 bg-rose-400 dark:bg-rose-500" />
                )}
              </div>
            </div>
            {(s.leaked_here > 0 || s.at_risk_here > 0) && (
              <div className="mt-0.5 flex flex-wrap gap-x-3 text-xs tabular-nums text-muted-foreground">
                <span>tích cực: {nf.format(active)}</span>
                {s.at_risk_here > 0 && (
                  <span className="text-amber-600 dark:text-amber-500">
                    tạm âm (từ chối): {nf.format(s.at_risk_here)}
                  </span>
                )}
                {s.leaked_here > 0 && (
                  <span className="text-rose-500">
                    đã rời phễu: {nf.format(s.leaked_here)}
                  </span>
                )}
              </div>
            )}
          </div>
        );
      })}
      {funnel.leaked > 0 && (
        <div className="border-t pt-2 text-xs text-muted-foreground">
          Tổng {nf.format(funnel.total_leads)} lead ·{" "}
          <span className="font-semibold tabular-nums text-rose-500">
            {nf.format(funnel.leaked)} đã rời phễu
          </span>{" "}
          (bỏ tư vấn · rút · không đi học — đã đóng)
        </div>
      )}
    </div>
  );
}
