// src/hooks/useDashboardStats.ts
/**
 * Custom hook for fetching officer dashboard stats with date range filtering.
 */
"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useDashboardDate } from "@/contexts/DashboardDateContext";
import { api } from "@/lib/api/client";
import { socket } from "@/lib/socket/client";

// =============================================================================
// TYPES
// =============================================================================

export interface TrendInfo {
  value: number;
  direction: "up" | "down" | "neutral";
  comparison: string;
}

export interface KPIStats {
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

export interface StatusOverview {
  current_workload: number;
  max_capacity: number;
  utilization: number;
  availability_status: "available" | "busy" | "offline";
}

export interface PriorityAction {
  id: string;
  type: "hot_lead" | "overdue" | "scheduled" | "follow_up" | "new_lead";
  priority: "urgent" | "high" | "medium";
  lead_id: number;
  lead_name: string;
  lead_score: number;
  reason: string;
  days_since_contact?: number;
}

export interface TrendPoint {
  date: string;
  assigned: number;
  consultations: number;
  converted: number;
}

export interface FunnelStage {
  stage_id: string;
  stage_name: string;
  stage_order: number;
  lead_count: number;
  is_final_stage?: boolean;
  fill?: string;
  conversion_rate?: number | null;
  outcome_breakdown?: {
    positive: number;
    negative: number;
    neutral: number;
  };
}

export interface LeadPreview {
  id: number;
  name: string;
  email?: string;
  phone?: string;
  lead_score: number;
  updated_at: string;
  stage_name?: string;
}

export interface UpcomingConsultation {
  id: number;
  lead_id: number;
  lead_name: string;
  scheduled_at: string;
  status: string;
}

export interface ActionableLists {
  high_score: LeadPreview[];
  stale: LeadPreview[];
  upcoming: UpcomingConsultation[];
}

export interface EnhancedOfficerStats {
  kpis: KPIStats;
  status_overview: StatusOverview;
  priority_actions: PriorityAction[];
  performance_trends: TrendPoint[];
  sales_funnel: FunnelStage[];
  actionable_lists: ActionableLists;
  // Phase 6: Annual progress (rolling targets)
  annual_progress?: AnnualProgressInfo | null;
}

// Phase 6: Annual Progress Info
export interface AnnualProgressInfo {
  kpi_code: string;
  fiscal_year: number;
  annual_target: number;
  achieved_ytd: number;
  remaining: number;
  progress_pct: number;
  months_left: number;
  monthly_target: number;
  status: "in_progress" | "completed" | "at_risk" | "overdue";
  on_track: boolean;
  surplus?: number | null;
  last_sync_at?: string | null;
}

export interface TeamStats {
  team_avg_consultations: number;
  team_avg_conversions: number;
  officer_rank_percentile: number;
  total_officers: number;
  period_days: number;
}

// =============================================================================
// API FUNCTIONS
// =============================================================================

export type DashboardScope = "personal" | "team" | "organization";

export interface DashboardFilters {
  scope?: DashboardScope;
  officerId?: number;
  unitId?: number;
  startDate?: string;
  endDate?: string;
}

async function fetchDashboard(filters: DashboardFilters): Promise<EnhancedOfficerStats> {
  const params = new URLSearchParams();
  
  if (filters.startDate) params.append("start_date", filters.startDate);
  if (filters.endDate) params.append("end_date", filters.endDate);
  if (filters.scope) params.append("scope", filters.scope);
  if (filters.officerId) params.append("officer_id", filters.officerId.toString());
  if (filters.unitId) params.append("unit_id", filters.unitId.toString());
  
  const url = `/api/officer/dashboard${params.toString() ? `?${params.toString()}` : ""}`;
  const response = await api.get(url);
  return response.data;
}

async function fetchTeamStats(): Promise<TeamStats> {
  const response = await api.get("/api/officer/team-stats");
  return response.data;
}

// =============================================================================
// HOOKS
// =============================================================================

export interface UseDashboardStatsOptions {
  scope?: DashboardScope;
  officerId?: number;
  unitId?: number;
}

export function useDashboardStats(options?: UseDashboardStatsOptions) {
  const queryClient = useQueryClient();
  const { startDate, endDate } = useDashboardDate();
  
  const scope = options?.scope ?? "personal";
  const officerId = options?.officerId;
  const unitId = options?.unitId;

  // Build cache key that includes all filters
  const cacheKey = ["officer", "dashboard", startDate, endDate, scope, officerId, unitId];

  // Fetch dashboard stats with date range and filters
  const dashboardQuery = useQuery({
    queryKey: cacheKey,
    queryFn: () => fetchDashboard({
      startDate,
      endDate,
      scope,
      officerId,
      unitId,
    }),
    refetchInterval: 60000,
    staleTime: 30000,
  });

  // Fetch team stats (no date filter needed)
  const teamStatsQuery = useQuery({
    queryKey: ["officer", "team-stats"],
    queryFn: fetchTeamStats,
    staleTime: 300000,
  });

  // Socket.IO integration for real-time updates
  useEffect(() => {
    if (!socket.connected) {
      socket.connect();
    }

    const handleDataUpdate = (...args: unknown[]) => {
      const data = args[0] as { resource: string };
      if (data.resource === "lead" || data.resource === "consultation") {
        queryClient.invalidateQueries({ queryKey: ["officer", "dashboard"] });
      }
    };

    const handleLeadChange = () => {
      queryClient.invalidateQueries({ queryKey: ["officer", "dashboard"] });
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

  return {
    stats: dashboardQuery.data,
    teamStats: teamStatsQuery.data,
    isLoading: dashboardQuery.isLoading,
    error: dashboardQuery.error,
    refetch: dashboardQuery.refetch,
  };
}
