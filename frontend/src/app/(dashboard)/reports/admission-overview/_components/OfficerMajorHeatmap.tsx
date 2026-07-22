"use client";

import * as React from "react";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import type { MatrixMetric, OfficerMajorMatrix } from "@/lib/zod/reports";

const nf = new Intl.NumberFormat("vi-VN");

const keyOf = (o: number | null, m: number | null) =>
  `${o ?? "x"}:${m ?? "x"}`;

/**
 * Heatmap cán bộ × ngành — ô đậm dần theo số hồ sơ (enrolled/submitted). Cường độ
 * dùng token ``--primary`` với alpha nên tự đúng cả sáng/tối. Nhiều ngành → cuộn
 * ngang trong khung riêng (body không cuộn ngang). Cột "Chưa phân loại" / hàng
 * "Chưa gán" giữ nguyên (không nuốt vào ai).
 */
export function OfficerMajorHeatmap({
  matrix,
  metric,
  onMetricChange,
}: {
  matrix: OfficerMajorMatrix;
  metric: MatrixMetric;
  onMetricChange: (m: MatrixMetric) => void;
}) {
  const { valueOf, rowTotal, max } = React.useMemo(() => {
    const lut = new Map<string, number>();
    const rTot = new Map<number | null, number>();
    let mx = 0;
    for (const c of matrix.cells) {
      const v = metric === "enrolled" ? c.enrolled : c.submitted;
      lut.set(keyOf(c.officer_id, c.major_id), v);
      rTot.set(c.officer_id, (rTot.get(c.officer_id) ?? 0) + v);
      if (v > mx) mx = v;
    }
    return {
      valueOf: (o: number | null, m: number | null) => lut.get(keyOf(o, m)) ?? 0,
      rowTotal: (o: number | null) => rTot.get(o) ?? 0,
      max: mx,
    };
  }, [matrix, metric]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          Số hồ sơ theo cán bộ (hàng) × ngành (cột) — đậm hơn = nhiều hơn.
        </p>
        <Tabs value={metric} onValueChange={(v) => onMetricChange(v as MatrixMetric)}>
          <TabsList className="h-8">
            <TabsTrigger value="enrolled" className="text-xs">
              Nhập học
            </TabsTrigger>
            <TabsTrigger value="submitted" className="text-xs">
              Nộp hồ sơ
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {matrix.officers.length === 0 || matrix.majors.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          Chưa có dữ liệu cán bộ × ngành trong lát cắt này.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                <th className="sticky left-0 z-10 border-b bg-card px-3 py-2 text-left text-xs font-semibold text-muted-foreground">
                  Cán bộ
                </th>
                {matrix.majors.map((mj) => (
                  <th
                    key={mj.id ?? "none"}
                    title={mj.name}
                    className="border-b border-l px-2 py-2 text-center align-bottom text-[10px] font-medium text-muted-foreground"
                  >
                    <span className="block max-w-[64px] truncate font-mono">
                      {mj.code ?? mj.name}
                    </span>
                  </th>
                ))}
                <th className="border-b border-l bg-card px-2 py-2 text-center text-xs font-semibold text-muted-foreground">
                  Tổng
                </th>
              </tr>
            </thead>
            <tbody>
              {matrix.officers.map((off) => (
                <tr key={off.id ?? "none"}>
                  <th className="sticky left-0 z-10 max-w-[160px] truncate border-b bg-card px-3 py-1.5 text-left text-xs font-medium">
                    {off.name}
                  </th>
                  {matrix.majors.map((mj) => {
                    const v = valueOf(off.id, mj.id);
                    const alpha = v > 0 && max > 0 ? 0.12 + 0.83 * (v / max) : 0;
                    return (
                      <td
                        key={mj.id ?? "none"}
                        className={cn(
                          "border-b border-l px-2 py-1.5 text-center tabular-nums",
                          alpha > 0.55 ? "text-primary-foreground" : "text-foreground",
                          v === 0 && "text-muted-foreground/40",
                        )}
                        style={
                          v > 0
                            ? { backgroundColor: `hsl(var(--primary) / ${alpha})` }
                            : undefined
                        }
                      >
                        {v === 0 ? "·" : nf.format(v)}
                      </td>
                    );
                  })}
                  <td className="border-b border-l bg-muted/40 px-2 py-1.5 text-center text-xs font-semibold tabular-nums">
                    {nf.format(rowTotal(off.id))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
