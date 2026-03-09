// src/app/(dashboard)/leads/pipeline/_components/PipelineClient.tsx
// src/app/(dashboard)/leads/pipeline/page.tsx
"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { RefreshCw, Filter, Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";

// ✅ PERFORMANCE: Dynamic import for heavy @dnd-kit components (~50KB)
// This defers loading until the component is actually rendered
const PipelineBoard = dynamic(
  () => import("@/components/leads/PipelineBoard").then((m) => m.PipelineBoard),
  {
    ssr: false, // @dnd-kit doesn't support SSR
    loading: () => <Skeleton className="h-[400px] md:h-[600px] w-full rounded-lg" />,
  }
);
import { useFullPipeline } from "@/hooks/usePipeline";
import { useExportLeads } from "@/hooks/useLeads";
import type { PipelineQueryParams, FullPipeline } from "@/types/pipeline.types";

// Helper: handles both ratio (0-1) and percentage (0-100)
function formatConversionRate(value: number): number {
  if (value <= 1) return value * 100;
  return value;
}

interface PipelineClientProps {
  initialData?: FullPipeline;
}

export function PipelineClient({ initialData }: PipelineClientProps) {
  const [filters, setFilters] = useState<PipelineQueryParams>({
    include_leads: true,
    include_stats: true,
  });
  const [showFilters, setShowFilters] = useState(false);

  const { data: pipeline, isLoading, isError, error, refetch } = useFullPipeline(filters, { initialData: filters.include_leads === true && filters.include_stats === true ? initialData : undefined });
  const exportLeads = useExportLeads();

  const handleExport = () => {
    exportLeads.mutate({ filters });
  };

  if (isLoading) {
    return (
      <PageContainer>
        <Skeleton className="h-10 w-48 sm:w-64" />
        <div className="grid grid-cols-2 gap-3 md:gap-4 md:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-[400px] md:h-[600px]" />
      </PageContainer>
    );
  }

  if (isError || !pipeline) {
    return (
      <PageContainer>
        <Card className="border-error-200 bg-error-50">
          <CardHeader>
            <CardTitle className="text-error-900">Lỗi tải Pipeline</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-error-700 mb-4">
              {error?.message || "Không thể tải dữ liệu pipeline"}
            </p>
            <Button onClick={() => refetch()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Thử lại
            </Button>
          </CardContent>
        </Card>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      {/* Header */}
      <PageHeader
        title="Bảng Pipeline"
        description="Kéo thả lead để di chuyển qua các giai đoạn pipeline"
        backButton={{ href: "/leads", label: "Quay lại Leads" }}
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowFilters(!showFilters)}
            >
              <Filter className="mr-2 h-4 w-4" />
              Bộ lọc
            </Button>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Làm mới
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleExport}
              disabled={exportLeads.isPending}
            >
              <Download className="mr-2 h-4 w-4" />
              {exportLeads.isPending ? "Đang xuất..." : "Xuất"}
            </Button>
          </>
        }
      />

      {/* Filters */}
      {showFilters && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Bộ lọc</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-3">
              <div>
                <label className="text-sm font-medium mb-2 block">
                  Đơn vị
                </label>
                <Select
                  value={filters.unit_id?.toString() || "all"}
                  onValueChange={(value) =>
                    setFilters({
                      ...filters,
                      unit_id: value === "all" ? undefined : parseInt(value),
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Tất cả đơn vị" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Tất cả đơn vị</SelectItem>
                    {/* Add unit options here */}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">Cán bộ</label>
                <Select
                  value={filters.officer_id?.toString() || "all"}
                  onValueChange={(value) =>
                    setFilters({
                      ...filters,
                      officer_id: value === "all" ? undefined : parseInt(value),
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Tất cả cán bộ" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Tất cả cán bộ</SelectItem>
                    {/* Add officer options here */}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">
                  Khoảng thời gian
                </label>
                <Select
                  defaultValue="all"
                  onValueChange={(value) => {
                    // ✅ TECHNICAL DEBT FIX: Implement date range logic
                    const getDateRange = (option: string): { date_from?: string; date_to?: string } => {
                      const now = new Date();
                      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
                      
                      switch (option) {
                        case "today":
                          return {
                            date_from: today.toISOString(),
                            date_to: new Date(today.getTime() + 24 * 60 * 60 * 1000 - 1).toISOString(),
                          };
                        case "week": {
                          const weekStart = new Date(today);
                          weekStart.setDate(today.getDate() - today.getDay()); // Start of week (Sunday)
                          const weekEnd = new Date(weekStart);
                          weekEnd.setDate(weekStart.getDate() + 6);
                          return {
                            date_from: weekStart.toISOString(),
                            date_to: weekEnd.toISOString(),
                          };
                        }
                        case "month": {
                          const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);
                          const monthEnd = new Date(today.getFullYear(), today.getMonth() + 1, 0);
                          return {
                            date_from: monthStart.toISOString(),
                            date_to: monthEnd.toISOString(),
                          };
                        }
                        case "year": {
                          const yearStart = new Date(today.getFullYear(), 0, 1);
                          const yearEnd = new Date(today.getFullYear(), 11, 31);
                          return {
                            date_from: yearStart.toISOString(),
                            date_to: yearEnd.toISOString(),
                          };
                        }
                        default:
                          return { date_from: undefined, date_to: undefined };
                      }
                    };
                    
                    const dateRange = getDateRange(value);
                    setFilters((prev) => ({
                      ...prev,
                      ...dateRange,
                    }));
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Tất cả" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Tất cả</SelectItem>
                    <SelectItem value="today">Hôm nay</SelectItem>
                    <SelectItem value="week">Tuần này</SelectItem>
                    <SelectItem value="month">Tháng này</SelectItem>
                    <SelectItem value="year">Năm nay</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Stats Cards */}
      <div className="grid grid-cols-2 gap-3 md:gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Tổng Lead</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{pipeline.total_leads}</div>
            <p className="text-xs text-muted-foreground">Tất cả giai đoạn</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Tỷ lệ chuyển đổi</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {pipeline.conversion_rate !== undefined
                ? `${formatConversionRate(pipeline.conversion_rate).toFixed(1)}%`
                : "N/A"}
            </div>
            <p className="text-xs text-muted-foreground">Tổng chuyển đổi</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Thời gian TB trong Pipeline</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {pipeline.avg_time_in_pipeline_days !== undefined
                ? `${Math.round(pipeline.avg_time_in_pipeline_days)} ngày`
                : "N/A"}
            </div>
            <p className="text-xs text-muted-foreground">Từ lead mới đến ghi danh</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Giai đoạn hoạt động</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{pipeline.stages.length}</div>
            <p className="text-xs text-muted-foreground">Giai đoạn pipeline</p>
          </CardContent>
        </Card>
      </div>

      {/* Kanban Board */}
      <PipelineBoard pipeline={pipeline} />
    </PageContainer>
  );
}
