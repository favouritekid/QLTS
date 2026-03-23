"use client";

import { useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, CalendarRange, Filter, Layers3 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { DrillDownResponse, DrillDownParams } from "@/lib/api/drilldown";

type DrillDownPageTarget = "consultations" | "transitions" | "cohorts";

interface DrillDownPageShellProps {
  target: DrillDownPageTarget;
  title: string;
  fetchFn: (params: DrillDownParams) => Promise<DrillDownResponse>;
  queryKeyPrefix: string;
  renderRow: (row: Record<string, unknown>, index: number) => React.ReactNode;
  columns: { key: string; label: string }[];
}

const KNOWN_PARAMS = new Set([
  "metric_key",
  "scope",
  "scope_officer_id",
  "scope_unit_id",
  "include_descendants",
  "from",
  "to",
  "page",
  "page_size",
  "sort_by",
  "order",
  "nav_source",
  "date_field",
]);

const METRIC_TITLES: Record<DrillDownPageTarget, Record<string, string>> = {
  consultations: {
    consultations_today: "Tư vấn hôm nay",
    consultations_avg_per_day: "Trung bình tư vấn / ngày",
    loss_reason: "Lý do mất lead",
    avg_response_time: "Thời gian phản hồi",
  },
  transitions: {
    bottleneck: "Điểm nghẽn chuyển giai đoạn",
    slow_stage: "Giai đoạn xử lý chậm",
    high_loss: "Leads mất nhiều ở giai đoạn",
    win_rate: "Tỷ lệ chốt đơn",
    enrollments_monthly: "Nhập học trong kỳ",
    consultation_effectiveness: "Hiệu quả tư vấn",
  },
  cohorts: {
    new_lead_conversion: "Chuyển đổi lead mới",
  },
};

const FILTER_LABELS: Record<string, string> = {
  stage_id: "Giai đoạn",
  loss_reason_code: "Lý do mất",
  consultation_kind: "Loại tư vấn",
  response_breach_only: "Vi phạm phản hồi",
  outcome: "Kết quả",
  final_only: "Chỉ final",
  consulted_only: "Đã tư vấn",
  cohort_result: "Kết quả cohort",
};

function formatFilterValue(key: string, value: string) {
  if (key === "consultation_kind") {
    return value === "human" ? "Tư vấn thủ công" : "System";
  }
  if (key === "response_breach_only" || key === "final_only" || key === "consulted_only") {
    return value === "1" || value === "true" ? "Có" : "Không";
  }
  if (key === "outcome") {
    return value === "positive"
      ? "Tích cực"
      : value === "negative"
      ? "Tiêu cực"
      : value === "neutral"
      ? "Trung tính"
      : value;
  }
  if (key === "cohort_result") {
    return value === "converted"
      ? "Đã chuyển đổi"
      : value === "lost"
      ? "Đã mất"
      : value === "open"
      ? "Đang mở"
      : value;
  }
  return value;
}

export function DrillDownPageShell({
  target,
  title,
  fetchFn,
  queryKeyPrefix,
  renderRow,
  columns,
}: DrillDownPageShellProps) {
  const searchParams = useSearchParams();
  const router = useRouter();

  const params: DrillDownParams = {
    metric_key: searchParams.get("metric_key") || "unknown",
    scope: searchParams.get("scope") || undefined,
    scope_officer_id: searchParams.get("scope_officer_id") ? Number(searchParams.get("scope_officer_id")) : undefined,
    scope_unit_id: searchParams.get("scope_unit_id") ? Number(searchParams.get("scope_unit_id")) : undefined,
    include_descendants: searchParams.get("include_descendants") === "1",
    from: searchParams.get("from") || undefined,
    to: searchParams.get("to") || undefined,
    page: Number(searchParams.get("page") || "1"),
    page_size: Number(searchParams.get("page_size") || "20"),
    sort_by: searchParams.get("sort_by") || undefined,
    order: (searchParams.get("order") as "asc" | "desc") || "desc",
  };

  searchParams.forEach((value, key) => {
    if (!(key in params)) {
      params[key] = value;
    }
  });

  const { data, isLoading, error } = useQuery({
    queryKey: [queryKeyPrefix, params],
    queryFn: () => fetchFn(params),
  });

  const metadata = data?.metadata;
  const rows = data?.rows || [];
  const metricTitle = METRIC_TITLES[target][params.metric_key] ?? title;
  const appliedFilters = useMemo(
    () =>
      Array.from(searchParams.entries())
        .filter(([key, value]) => !KNOWN_PARAMS.has(key) && value)
        .map(([key, value]) => ({
          key,
          label: FILTER_LABELS[key] ?? key,
          value: formatFilterValue(key, value),
        })),
    [searchParams],
  );

  return (
    <div className="flex h-full flex-col space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-start gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.back()}>
          <ArrowLeft className="mr-1 h-4 w-4" />
          Quay lại
        </Button>
        <div className="min-w-0 space-y-2">
          <div>
            <h1 className="text-lg font-semibold">{metricTitle}</h1>
            <p className="text-sm text-muted-foreground">{title}</p>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {metadata?.effective_scope && (
              <Badge variant="secondary" className="gap-1">
                <Layers3 className="h-3 w-3" />
                {metadata.effective_scope.label}
              </Badge>
            )}
            {metadata?.effective_date_context?.start_date && (
              <Badge variant="outline" className="gap-1">
                <CalendarRange className="h-3 w-3" />
                {metadata.effective_date_context.start_date} → {metadata.effective_date_context.end_date}
              </Badge>
            )}
            {metadata && (
              <Badge variant="outline">{metadata.total_count} bản ghi</Badge>
            )}
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Filter className="h-3.5 w-3.5" />
          <span>Metric key: <strong>{params.metric_key}</strong></span>
        </div>
        {appliedFilters.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {appliedFilters.map((filter) => (
              <Badge key={filter.key} variant="outline">
                {filter.label}: {filter.value}
              </Badge>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Không có filter bổ sung.</p>
        )}
      </div>

      {isLoading ? (
        <div className="flex flex-1 items-center justify-center text-muted-foreground">
          Đang tải...
        </div>
      ) : error ? (
        <div className="flex flex-1 items-center justify-center text-destructive">
          Lỗi tải dữ liệu
        </div>
      ) : rows.length === 0 ? (
        <div className="flex flex-1 items-center justify-center text-muted-foreground">
          Không có dữ liệu
        </div>
      ) : (
        <div className="flex-1 overflow-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="sticky top-0 border-b bg-background">
              <tr>
                {columns.map((col) => (
                  <th key={col.key} className="px-3 py-2 text-left font-medium text-muted-foreground">
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => renderRow(row, i))}
            </tbody>
          </table>

          {metadata && metadata.total_count > metadata.page_size && (
            <div className="mt-2 flex items-center justify-between border-t px-3 py-3">
              <span className="text-sm text-muted-foreground">
                Trang {metadata.page} / {Math.ceil(metadata.total_count / metadata.page_size)}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={metadata.page <= 1}
                  onClick={() => {
                    const p = new URLSearchParams(searchParams.toString());
                    p.set("page", String(metadata.page - 1));
                    router.push(`?${p.toString()}`);
                  }}
                >
                  Trước
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={metadata.page >= Math.ceil(metadata.total_count / metadata.page_size)}
                  onClick={() => {
                    const p = new URLSearchParams(searchParams.toString());
                    p.set("page", String(metadata.page + 1));
                    router.push(`?${p.toString()}`);
                  }}
                >
                  Sau
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
