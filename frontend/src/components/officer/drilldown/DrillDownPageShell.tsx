"use client";

import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Filter } from "lucide-react";
import { useRouter } from "next/navigation";
import type { DrillDownResponse, DrillDownParams } from "@/lib/api/drilldown";

interface DrillDownPageShellProps {
  title: string;
  fetchFn: (params: DrillDownParams) => Promise<DrillDownResponse>;
  queryKeyPrefix: string;
  renderRow: (row: Record<string, unknown>, index: number) => React.ReactNode;
  columns: { key: string; label: string }[];
}

export function DrillDownPageShell({
  title,
  fetchFn,
  queryKeyPrefix,
  renderRow,
  columns,
}: DrillDownPageShellProps) {
  const searchParams = useSearchParams();
  const router = useRouter();

  // Parse all params from URL
  const params: DrillDownParams = {
    metric_key: searchParams.get("metric_key") || "unknown",
    scope: searchParams.get("scope") || undefined,
    scope_officer_id: searchParams.get("scope_officer_id") ? Number(searchParams.get("scope_officer_id")) : undefined,
    scope_unit_id: searchParams.get("scope_unit_id") ? Number(searchParams.get("scope_unit_id")) : undefined,
    include_descendants: searchParams.get("include_descendants") === "1",
    from: searchParams.get("from") || undefined,
    to: searchParams.get("to") || undefined,
    page: Number(searchParams.get("page") || "1"),
    page_size: 20,
    sort_by: searchParams.get("sort_by") || undefined,
    order: (searchParams.get("order") as "asc" | "desc") || "desc",
  };

  // Pass through any extra filter params (stage_id, loss_reason_code, etc.)
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

  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.back()}>
          <ArrowLeft className="h-4 w-4 mr-1" />
          Quay lại
        </Button>
        <div>
          <h1 className="text-lg font-semibold">{title}</h1>
          {metadata?.effective_scope && (
            <div className="flex items-center gap-2 mt-1">
              <Badge variant="secondary" className="text-xs">
                {metadata.effective_scope.label}
              </Badge>
              {metadata.effective_date_context?.start_date && (
                <span className="text-xs text-muted-foreground">
                  {metadata.effective_date_context.start_date} → {metadata.effective_date_context.end_date}
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Filters applied */}
      {params.metric_key && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Filter className="h-3.5 w-3.5" />
          <span>Metric: <strong>{params.metric_key}</strong></span>
          {metadata && <span>• {metadata.total_count} kết quả</span>}
        </div>
      )}

      {/* Table */}
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center text-muted-foreground">
          Đang tải...
        </div>
      ) : error ? (
        <div className="flex-1 flex items-center justify-center text-destructive">
          Lỗi tải dữ liệu
        </div>
      ) : rows.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-muted-foreground">
          Không có dữ liệu
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-background border-b">
              <tr>
                {columns.map((col) => (
                  <th key={col.key} className="text-left py-2 px-3 font-medium text-muted-foreground">
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => renderRow(row, i))}
            </tbody>
          </table>

          {/* Pagination */}
          {metadata && metadata.total_count > metadata.page_size && (
            <div className="flex items-center justify-between py-3 border-t mt-2">
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
