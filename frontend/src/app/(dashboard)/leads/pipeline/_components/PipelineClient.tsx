// src/app/(dashboard)/leads/pipeline/_components/PipelineClient.tsx
// src/app/(dashboard)/leads/pipeline/page.tsx
"use client";

import { useState } from "react";
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

import { PipelineBoard } from "@/components/leads/PipelineBoard";
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

  const handleExport = () => {
    exportLeads.mutate({ filters });
  };

  if (isLoading) {
    return (
      <PageContainer>
        <Skeleton className="h-10 w-64" />
        <div className="grid gap-4 md:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-[600px]" />
      </PageContainer>
    );
  }

  if (isError || !pipeline) {
    return (
      <PageContainer>
        <Card className="border-red-200 bg-red-50">
          <CardHeader>
            <CardTitle className="text-red-900">Error Loading Pipeline</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-red-700 mb-4">
              {error?.message || "Failed to load pipeline data"}
            </p>
            <Button onClick={() => refetch()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Retry
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
        title="Pipeline Board"
        description="Drag and drop leads to move them through the pipeline"
        backButton={{ href: "/leads", label: "Back to Leads" }}
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowFilters(!showFilters)}
            >
              <Filter className="mr-2 h-4 w-4" />
              Filters
            </Button>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Refresh
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleExport}
              disabled={exportLeads.isPending}
            >
              <Download className="mr-2 h-4 w-4" />
              {exportLeads.isPending ? "Exporting..." : "Export"}
            </Button>
          </>
        }
      />

      {/* Filters */}
      {showFilters && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Filters</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-3">
              <div>
                <label className="text-sm font-medium mb-2 block">
                  Organization Unit
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
                    <SelectValue placeholder="All Units" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Units</SelectItem>
                    {/* Add unit options here */}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">Officer</label>
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
                    <SelectValue placeholder="All Officers" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Officers</SelectItem>
                    {/* Add officer options here */}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">
                  Date Range
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
                    <SelectValue placeholder="All Time" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Time</SelectItem>
                    <SelectItem value="today">Today</SelectItem>
                    <SelectItem value="week">This Week</SelectItem>
                    <SelectItem value="month">This Month</SelectItem>
                    <SelectItem value="year">This Year</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Leads</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{pipeline.total_leads}</div>
            <p className="text-xs text-muted-foreground">Across all stages</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Conversion Rate</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {pipeline.conversion_rate !== undefined
                ? `${(pipeline.conversion_rate * 100).toFixed(1)}%`
                : "N/A"}
            </div>
            <p className="text-xs text-muted-foreground">Overall conversion</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Avg Time in Pipeline</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {pipeline.avg_time_in_pipeline_days !== undefined
                ? `${Math.round(pipeline.avg_time_in_pipeline_days)} days`
                : "N/A"}
            </div>
            <p className="text-xs text-muted-foreground">From new lead to enrolled</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Stages</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{pipeline.stages.length}</div>
            <p className="text-xs text-muted-foreground">Pipeline stages</p>
          </CardContent>
        </Card>
      </div>

      {/* Kanban Board */}
      <PipelineBoard pipeline={pipeline} />
    </PageContainer>
  );
}
