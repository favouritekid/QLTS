"use client";

import * as React from "react";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import type { MatrixMetric, OfficerMajorMatrix } from "@/lib/zod/reports";

const nf = new Intl.NumberFormat("vi-VN");

const keyOf = (o: number | null, m: number | null) =>
  `${o ?? "x"}:${m ?? "x"}`;

type Metric = { key: MatrixMetric; label: string };
type Tab = { key: string; label: string; metrics: Metric[] };

/**
 * 3 tab theo đúng vòng đời tuyển sinh — mỗi tab đọc thẳng chỉ số BE trả (thin
 * client, không suy diễn). Tab 2 chỉ số → mỗi cán bộ tách 2 cột con.
 */
const TABS: Tab[] = [
  {
    key: "profiles",
    label: "Hồ sơ",
    metrics: [
      { key: "submitted", label: "Đã nộp" },
      { key: "draft", label: "Nháp" },
    ],
  },
  {
    key: "fee",
    label: "Học phí HK1",
    metrics: [
      { key: "fee_partial", label: "Một phần" },
      { key: "fee_full", label: "Đóng đủ" },
    ],
  },
  {
    key: "enrolled",
    label: "Nhập học",
    metrics: [{ key: "enrolled", label: "Nhập học" }],
  },
];

/**
 * Heatmap ngành × cán bộ — HÀNG là ngành (mã + tên đầy đủ ở cột trái, đọc ngay),
 * CỘT là cán bộ. Ô đậm dần theo số hồ sơ; token ``--primary`` pha alpha nên tự
 * đúng cả sáng/tối. Cường độ theo từng chỉ số (mỗi cột con có thang riêng). Ma
 * trận trả CẢ 5 chỉ số → đổi tab client-side, không refetch. Hàng "Chưa phân
 * loại ngành" / cột "Chưa gán" giữ nguyên; hàng/cột "Tổng" để đối chiếu KPI.
 */
export function OfficerMajorHeatmap({
  matrix,
  tabKey: controlledTabKey,
  onTabKeyChange,
}: {
  matrix: OfficerMajorMatrix;
  /** Controlled: khoá tab đang chọn (khi cha đồng bộ lên URL). Bỏ trống → tự quản. */
  tabKey?: string;
  onTabKeyChange?: (key: string) => void;
}) {
  const [internalTabKey, setInternalTabKey] = React.useState(TABS[0].key);
  const tabKey = controlledTabKey ?? internalTabKey;
  const setTabKey = onTabKeyChange ?? setInternalTabKey;
  const tab = TABS.find((t) => t.key === tabKey) ?? TABS[0];
  const metrics = tab.metrics;
  const multi = metrics.length > 1;

  // Tính thẳng trong render — react-compiler tự memo theo (matrix, tab); KHÔNG
  // dùng useMemo tay (dep là object `tab` sẽ vỡ "memoization could not be preserved").
  const officers = matrix.officers;

  const lut = new Map<string, Record<MatrixMetric, number>>();
  for (const c of matrix.cells) {
    lut.set(keyOf(c.officer_id, c.major_id), {
      submitted: c.submitted,
      draft: c.draft,
      fee_partial: c.fee_partial,
      fee_full: c.fee_full,
      enrolled: c.enrolled,
    });
  }
  const valueOf = (o: number | null, m: number | null, k: MatrixMetric) =>
    lut.get(keyOf(o, m))?.[k] ?? 0;
  const rowTotal = (m: number | null, k: MatrixMetric) =>
    officers.reduce((s, o) => s + valueOf(o.id, m, k), 0);
  const colTotal = (o: number | null, k: MatrixMetric) =>
    matrix.majors.reduce((s, m) => s + valueOf(o, m.id, k), 0);

  const grand = {} as Record<MatrixMetric, number>;
  const maxByMetric = {} as Record<MatrixMetric, number>;
  for (const mt of metrics) {
    let g = 0;
    let mx = 0;
    for (const c of matrix.cells) {
      const v = c[mt.key];
      g += v;
      if (v > mx) mx = v;
    }
    grand[mt.key] = g;
    maxByMetric[mt.key] = mx;
  }
  // Ngành (hàng) sắp theo tổng các chỉ số của tab giảm dần; bucket null cuối.
  const majors = [...matrix.majors].sort((a, b) => {
    if (a.id == null) return 1;
    if (b.id == null) return -1;
    const sum = (mid: number) =>
      metrics.reduce((s, mt) => s + rowTotal(mid, mt.key), 0);
    return sum(b.id) - sum(a.id);
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          Số hồ sơ theo ngành (hàng) × cán bộ (cột) — đậm hơn = nhiều hơn.
        </p>
        <Tabs value={tabKey} onValueChange={setTabKey}>
          <TabsList className="h-8">
            {TABS.map((t) => (
              <TabsTrigger key={t.key} value={t.key} className="text-xs">
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      {officers.length === 0 || majors.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          Chưa có dữ liệu ngành × cán bộ trong lát cắt này.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">
              Ma trận số hồ sơ theo ngành (hàng) × cán bộ (cột) — đậm hơn nghĩa là
              nhiều hồ sơ hơn.
            </caption>
            <thead>
              <tr>
                <th
                  scope="col"
                  rowSpan={multi ? 2 : 1}
                  className="sticky left-0 z-10 border-b bg-card px-3 py-2 text-left align-bottom text-xs font-semibold text-muted-foreground"
                >
                  Ngành
                </th>
                {officers.map((off) => (
                  <th
                    key={off.id ?? "none"}
                    scope={metrics.length > 1 ? "colgroup" : "col"}
                    colSpan={metrics.length}
                    title={off.name}
                    className="border-b border-l px-2 py-2 text-center align-bottom text-[11px] font-medium text-muted-foreground"
                  >
                    <span className="mx-auto block max-w-[120px] leading-tight">
                      {off.name}
                    </span>
                  </th>
                ))}
                <th
                  scope={metrics.length > 1 ? "colgroup" : "col"}
                  colSpan={metrics.length}
                  className="border-b border-l bg-card px-2 py-2 text-center text-xs font-semibold text-muted-foreground"
                >
                  Tổng
                </th>
              </tr>
              {multi && (
                <tr>
                  {officers.map((off) =>
                    metrics.map((mt) => (
                      <th
                        key={`${off.id ?? "none"}:${mt.key}`}
                        scope="col"
                        className="border-b border-l px-2 py-1 text-center text-[10px] font-normal text-muted-foreground"
                      >
                        {mt.label}
                      </th>
                    )),
                  )}
                  {metrics.map((mt) => (
                    <th
                      key={`tot:${mt.key}`}
                      scope="col"
                      className="border-b border-l bg-card px-2 py-1 text-center text-[10px] font-normal text-muted-foreground"
                    >
                      {mt.label}
                    </th>
                  ))}
                </tr>
              )}
            </thead>
            <tbody>
              {majors.map((mj) => (
                <tr key={mj.id ?? "none"}>
                  <th
                    scope="row"
                    className="sticky left-0 z-10 border-b bg-card px-3 py-1.5 text-left font-medium"
                    title={mj.code ? `${mj.name} · ${mj.code}` : mj.name}
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      {mj.code && (
                        <span className="hidden shrink-0 font-mono text-[10px] text-muted-foreground sm:inline">
                          {mj.code}
                        </span>
                      )}
                      <span className="max-w-[240px] truncate text-xs">
                        {mj.name}
                      </span>
                    </span>
                  </th>
                  {officers.map((off) =>
                    metrics.map((mt) => {
                      const v = valueOf(off.id, mj.id, mt.key);
                      const mx = maxByMetric[mt.key] ?? 0;
                      const alpha = v > 0 && mx > 0 ? 0.12 + 0.83 * (v / mx) : 0;
                      return (
                        <td
                          key={`${off.id ?? "none"}:${mt.key}`}
                          className={cn(
                            "border-b border-l px-2 py-1.5 text-center tabular-nums",
                            alpha > 0.55
                              ? "text-primary-foreground"
                              : "text-foreground",
                            v === 0 && "text-muted-foreground/40",
                          )}
                          style={
                            v > 0
                              ? {
                                  // `--primary` is a hex token (not HSL channels), so
                                  // `hsl(var(--primary)/α)` is invalid; color-mix tints
                                  // it with transparency in both themes.
                                  backgroundColor: `color-mix(in srgb, var(--primary) ${Math.round(
                                    alpha * 100,
                                  )}%, transparent)`,
                                }
                              : undefined
                          }
                        >
                          {v === 0 ? (
                            <>
                              <span aria-hidden>·</span>
                              <span className="sr-only">0</span>
                            </>
                          ) : (
                            nf.format(v)
                          )}
                        </td>
                      );
                    }),
                  )}
                  {metrics.map((mt) => (
                    <td
                      key={`rowtot:${mt.key}`}
                      className="border-b border-l bg-muted/40 px-2 py-1.5 text-center text-xs font-semibold tabular-nums"
                    >
                      {nf.format(rowTotal(mj.id, mt.key))}
                    </td>
                  ))}
                </tr>
              ))}
              {/* Hàng tổng theo từng cán bộ (đối chiếu nhanh với KPI band). */}
              <tr>
                <th className="sticky left-0 z-10 border-t-2 bg-card px-3 py-1.5 text-left text-xs font-semibold text-muted-foreground">
                  Tổng
                </th>
                {officers.map((off) =>
                  metrics.map((mt) => (
                    <td
                      key={`coltot:${off.id ?? "none"}:${mt.key}`}
                      className="border-l border-t-2 bg-muted/40 px-2 py-1.5 text-center text-xs font-semibold tabular-nums"
                    >
                      {nf.format(colTotal(off.id, mt.key))}
                    </td>
                  )),
                )}
                {metrics.map((mt) => (
                  <td
                    key={`grand:${mt.key}`}
                    className="border-l border-t-2 bg-muted/60 px-2 py-1.5 text-center text-xs font-bold tabular-nums"
                  >
                    {nf.format(grand[mt.key] ?? 0)}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
