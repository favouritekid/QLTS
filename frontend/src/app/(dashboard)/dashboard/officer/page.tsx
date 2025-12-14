// src/app/(dashboard)/dashboard/officer/page.tsx
"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";
import { WorkloadCard } from "@/components/officer/WorkloadCard";
import { PerformanceChart } from "@/components/officer/PerformanceChart";
import { FunnelChart } from "@/components/officer/FunnelChart";
import { ActionableLists } from "@/components/officer/ActionableLists";
import { KPICardsGrid } from "@/components/officer/dashboard";
import { api } from "@/lib/api/client";
import { socket } from "@/lib/socket/client";

/**
 * Officer Command Center - Enhanced Dashboard for officers
 *
 * Features:
 * - KPI Cards with trends (Phase 1)
 * - Priority Actions (Phase 2)
 * - Real-time stats with Socket.IO updates
 * - Performance trends (7 days)
 * - Sales funnel visualization
 * - Actionable lead lists
 * - Availability toggle
 */

// =============================================================================
// TYPES
// =============================================================================

interface TrendInfo {
  value: number;
  direction: "up" | "down" | "neutral";
  comparison: string;
}

interface KPIStats {
  consultations_today: number;
  consultations_target: number;
  consultations_trend: TrendInfo;
  active_leads: number;
  active_leads_trend: TrendInfo;
  conversion_rate: number;
  conversion_rate_trend: TrendInfo;
  avg_response_time: number;
  avg_response_time_trend: TrendInfo;
}

interface StatusOverview {
  current_workload: number;
  max_capacity: number;
  utilization: number;
  availability_status: "available" | "busy" | "offline";
}

interface PriorityAction {
  id: string;
  type: "hot_lead" | "overdue" | "scheduled" | "follow_up" | "new_lead";
  priority: "urgent" | "high" | "medium";
  lead_id: number;
  lead_name: string;
  lead_score: number;
  reason: string;
  days_since_contact?: number;
}

interface TrendPoint {
  date: string;
  assigned: number;
  consultations: number;
  converted: number;
}

interface FunnelStage {
  stage: string;
  count: number;
  fill: string;
}

interface LeadPreview {
  id: number;
  name: string;
  email?: string;
  phone?: string;
  lead_score: number;
  updated_at: string;
  stage_name?: string;
}

interface UpcomingConsultation {
  id: number;
  lead_id: number;
  lead_name: string;
  scheduled_at: string;
  status: string;
}

interface ActionableLists {
  high_score: LeadPreview[];
  stale: LeadPreview[];
  upcoming: UpcomingConsultation[];
}

interface EnhancedOfficerStats {
  kpis: KPIStats;
  status_overview: StatusOverview;
  priority_actions: PriorityAction[];
  performance_trends: TrendPoint[];
  sales_funnel: FunnelStage[];
  actionable_lists: ActionableLists;
}

// =============================================================================
// API
// =============================================================================

async function fetchEnhancedDashboard(): Promise<EnhancedOfficerStats> {
  const response = await api.get("/api/officer/dashboard");
  return response.data;
}

// =============================================================================
// COMPONENT
// =============================================================================

export default function OfficerDashboardPage() {
  const queryClient = useQueryClient();

  // Fetch enhanced officer stats
  const {
    data: stats,
    isLoading,
    error,
    refetch
  } = useQuery({
    queryKey: ["officer", "dashboard"],
    queryFn: fetchEnhancedDashboard,
    refetchInterval: 60000, // Refresh every 60 seconds
    staleTime: 30000, // Consider data stale after 30 seconds
  });

  // === REAL-TIME SOCKET.IO INTEGRATION ===
  useEffect(() => {
    if (!socket.connected) {
      socket.connect();
    }

    // Listen for data update events
    const handleDataUpdate = (...args: unknown[]) => {
      const data = args[0] as { resource: string };
      // Invalidate queries when leads or consultations are updated
      if (data.resource === "lead" || data.resource === "consultation") {
        queryClient.invalidateQueries({ queryKey: ["officer", "dashboard"] });
        console.log("Officer dashboard invalidated due to:", data.resource);
      }
    };

    // Listen for lead assignment/status events that affect officer workload
    const handleLeadChange = () => {
      queryClient.invalidateQueries({ queryKey: ["officer", "dashboard"] });
      console.log("Officer dashboard invalidated due to lead change");
    };

    socket.on("data_updated", handleDataUpdate);
    socket.on("lead_assigned", handleLeadChange);
    socket.on("lead_status_changed", handleLeadChange);

    return () => {
      socket.off("data_updated", handleDataUpdate);
      socket.off("lead_assigned", handleLeadChange);
      socket.off("lead_status_changed", handleLeadChange);
    };
  }, [queryClient]);

  // === LOADING STATE ===
  if (isLoading) {
    return (
      <div className="container mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <Skeleton className="h-10 w-64" />
        </div>

        {/* KPI Cards Skeleton */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>

        {/* Workload Skeleton */}
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          <Skeleton className="h-96" />
          <Skeleton className="h-96" />
        </div>
      </div>
    );
  }

  // === ERROR STATE ===
  if (error) {
    return (
      <div className="container mx-auto p-6">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Không thể tải thống kê dashboard. Vui lòng thử lại.
            <button
              onClick={() => refetch()}
              className="ml-4 underline"
            >
              Thử lại
            </button>
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  if (!stats) {
    return null;
  }

  // === DATA TRANSFORMERS ===
  // Transform API response to match existing component interfaces
  
  // Transform TrendPoint[] to PerformanceTrend[] for PerformanceChart
  const performanceTrends = stats.performance_trends.map((t) => ({
    date: t.date,
    leads_assigned: t.assigned,
    consultations: t.consultations,
    converted: t.converted,
  }));

  // Transform FunnelStage[] (API) to FunnelStage[] (component)
  const salesFunnel = stats.sales_funnel.map((s, index) => ({
    stage_name: s.stage,
    stage_order: index,
    lead_count: s.count,
  }));

  // Transform ActionableLists (API) to component format
  const actionableLists = {
    high_score: stats.actionable_lists.high_score.map((lead) => ({
      id: lead.id,
      full_name: lead.name, // API uses 'name', component expects 'full_name'
      email: lead.email || "",
      lead_score: lead.lead_score,
      status: lead.stage_name || "",
      created_at: lead.updated_at,
    })),
    stale: stats.actionable_lists.stale.map((lead) => ({
      id: lead.id,
      full_name: lead.name,
      email: lead.email || "",
      last_updated: lead.updated_at,
      days_stale: 3, // Calculate from updated_at if needed
    })),
    upcoming: stats.actionable_lists.upcoming.map((c) => ({
      id: c.id,
      lead_id: c.lead_id,
      lead_name: c.lead_name,
      consultation_date: c.scheduled_at,
      method: c.status,
      notes: null,
    })),
  };

  return (
    <div className="container mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Officer Dashboard</h1>
          <p className="text-muted-foreground">
            Theo dõi hiệu suất và quản lý leads của bạn
          </p>
        </div>
      </div>

      {/* ✅ PHASE 1: KPI Cards */}
      <KPICardsGrid kpis={stats.kpis} />

      {/* Workload Overview (4 mini cards) */}
      <WorkloadCard statusOverview={stats.status_overview} />

      {/* Performance and Funnel Charts */}
      <div className="grid gap-6 md:grid-cols-2">
        <PerformanceChart trends={performanceTrends} />
        <FunnelChart funnel={salesFunnel} />
      </div>

      {/* Actionable Lists */}
      <ActionableLists lists={actionableLists} />
    </div>
  );
}
