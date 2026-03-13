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
import { useOrganizationUnits } from "@/hooks/useOrganization";
import { useAdminUsersList } from "@/hooks/useAdminUsers";

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

  const { data: units } = useOrganizationUnits();
  const { data: officersData } = useAdminUsersList({
    role: "officer",
    status: "active",
    page_size: 100,
    ...(filters.unit_id ? { unit_id: filters.unit_id } : {}),
  });

  const handleExport = () => {
    // ✅ T4 FIX: Map pipeline filter fields to leads export API contract
    // Pipeline uses officer_id, but leads export API expects assigned_officer_id
    const exportFilters: Record<string, unknown> = {};
    if (filters.unit_id) exportFilters.unit_id = filters.unit_id;
    if (filters.officer_id) exportFilters.assigned_officer_id = filters.officer_id;
    if (filters.date_from) exportFilters.date_from = filters.date_from;
    if (filters.date_to) exportFilters.date_to = filters.date_to;
    exportLeads.mutate({ filters: exportFilters });
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
        description="Tổng quan lead theo từng giai đoạn. Mở lead để chuyển trạng thái qua bước tư vấn."
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
                    {units?.map((unit) => (
                      <SelectItem key={unit.id} value={unit.id.toString()}>
                        {unit.name}
                      </SelectItem>
                    ))}
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
                    {officersData?.users?.map((officer) => (
                      <SelectItem key={officer.id} value={officer.id.toString()}>
                        {officer.full_name}
                      </SelectItem>
                    ))}
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
                    // ✅ T8 FIX: Set date_to to end of day (23:59:59.999) to include all data on the last day
                    const getDateRange = (option: string): { date_from?: string; date_to?: string } => {
                      const now = new Date();
                      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

                      // Helper: set date to end of day (23:59:59.999)
                      const endOfDay = (date: Date): Date => {
                        date.setHours(23, 59, 59, 999);
                        return date;
                      };

                      switch (option) {
                        case "today":
                          return {
                            date_from: today.toISOString(),
                            date_to: endOfDay(new Date(today)).toISOString(),
                          };
                        case "week": {
                          const weekStart = new Date(today);
                          weekStart.setDate(today.getDate() - ((today.getDay() + 6) % 7)); // Start of week (Monday)
                          const weekEnd = new Date(weekStart);
                          weekEnd.setDate(weekStart.getDate() + 6);
                          return {
                            date_from: weekStart.toISOString(),
                            date_to: endOfDay(weekEnd).toISOString(),
                          };
                        }
                        case "month": {
                          const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);
                          const monthEnd = new Date(today.getFullYear(), today.getMonth() + 1, 0);
                          return {
                            date_from: monthStart.toISOString(),
                            date_to: endOfDay(monthEnd).toISOString(),
                          };
                        }
                        case "year": {
                          const yearStart = new Date(today.getFullYear(), 0, 1);
                          const yearEnd = new Date(today.getFullYear(), 11, 31);
                          return {
                            date_from: yearStart.toISOString(),
                            date_to: endOfDay(yearEnd).toISOString(),
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
              {pipeline.conversion_rate != null
                ? `${pipeline.conversion_rate.toFixed(1)}%`
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
