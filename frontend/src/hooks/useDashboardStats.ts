// src/hooks/useDashboardStats.ts
/**
 * Custom hook for fetching officer dashboard stats with date range filtering.
 */
"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import { subDays, startOfDay, endOfDay } from "date-fns";
import { useDashboardDate, formatDateForAPI } from "@/contexts/DashboardDateContext";
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
  active_leads_in_period?: number;
  active_leads_trend: TrendInfo;
  win_rate: number;
  win_rate_trend?: TrendInfo | null;
  new_lead_conversion_rate: number;
  new_lead_conversion_rate_trend?: TrendInfo | null;
  avg_response_time: number;
  avg_response_time_trend: TrendInfo;
  sla_compliance_rate: number;
  sla_compliance_rate_trend?: TrendInfo | null;
  consultation_effectiveness: number;
  consultation_effectiveness_trend?: TrendInfo | null;
  consultations_avg_per_day?: number;
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
  enrolled?: number;
  lost?: number;
}

/** Phase 2: Loss reason breakdown item */
export interface LossBreakdownItem {
  reason_code: string;
  count: number;
  percentage: number;
}

/** Phase 2: Stage velocity statistics */
export interface VelocityStats {
  avg_days: number;
  min_days: number;
  max_days: number;
  sample_size: number;
}

/** Phase 2: Estimated lost revenue */
export interface EstimatedLostRevenue {
  lost_leads_count: number;
  avg_tuition: number;
  total_lost_revenue: number;
  leads_with_tuition: number;
}

/** Phase 2: AI-powered funnel suggestion */
export interface FunnelSuggestion {
  id: string;
  type: "bottleneck" | "slow_stage" | "high_loss" | "loss_reason";
  priority: "critical" | "high" | "medium" | "low";
  stage_id?: string | null;
  stage_name?: string | null;
  title: string;
  description: string;
  metric_value?: number | null;
  metric_label?: string | null;
  action_label?: string | null;
  action_url?: string | null;
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
  // SPEC 2026-02-04: Early Exit metrics
  early_exit_count?: number;  // FINAL leads (negative) at this stage
  move_forward?: number;      // lead_count - early_exit_count
  // Phase 2: Advanced funnel analytics
  loss_breakdown?: LossBreakdownItem[] | null;
  velocity?: VelocityStats | null;
  estimated_lost_revenue?: EstimatedLostRevenue | null;
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
  // Phase 2: AI-powered funnel suggestions
  funnel_suggestions?: FunnelSuggestion[];
  funnel_net_conversion_trend?: TrendInfo | null;
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

  try {
    const response = await api.get<EnhancedOfficerStats>(url);

    // Ensure we never return undefined (React Query requirement)
    if (!response.data) {
      console.error("[fetchDashboard] API returned empty response for:", url, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
        data: response.data,
        dataType: typeof response.data,
      });
      throw new Error(`Dashboard API returned empty response (status: ${response.status})`);
    }

    // Validate response has required fields
    if (!response.data.kpis || !response.data.status_overview) {
      console.error("[fetchDashboard] API returned incomplete response for:", url, {
        hasKpis: !!response.data.kpis,
        hasStatusOverview: !!response.data.status_overview,
        keys: Object.keys(response.data),
      });
      throw new Error("Dashboard API returned incomplete response");
    }

    return response.data;
  } catch (error) {
    console.error("[fetchDashboard] API error for:", url, error);
    throw error;
  }
}

async function fetchTeamStats(startDate?: string, endDate?: string, officerId?: number): Promise<TeamStats> {
  const params = new URLSearchParams();
  if (startDate) params.append("start_date", startDate);
  if (endDate) params.append("end_date", endDate);
  if (officerId) params.append("officer_id", officerId.toString());

  const url = `/api/officer/team-stats${params.toString() ? `?${params.toString()}` : ""}`;
  const response = await api.get(url);
  return response.data;
}

// =============================================================================
// HOOKS
// =============================================================================

export interface UseDashboardStatsOptions {
  scope?: DashboardScope;
  officerId?: number;
  unitId?: number;
  initialData?: EnhancedOfficerStats;
  enabled?: boolean;
}

export function useDashboardStats(options?: UseDashboardStatsOptions) {
  const queryClient = useQueryClient();
  const { startDate, endDate } = useDashboardDate();
  
  const scope = options?.scope ?? "personal";
  const officerId = options?.officerId;
  const unitId = options?.unitId;
  const enabled = options?.enabled ?? true;

  // Compute what SSR would have used (same logic as page.tsx getDefaultDateRange)
  const ssrDefault = useMemo(() => {
    const today = new Date();
    const from = subDays(today, 6);
    return {
      start: formatDateForAPI(startOfDay(from)),
      end: formatDateForAPI(endOfDay(today)),
    };
  }, []); // Empty deps: only compute once on mount (matches SSR snapshot)

  const isDefaultQuery =
    scope === "personal" &&
    !officerId &&
    !unitId &&
    startDate === ssrDefault.start &&
    endDate === ssrDefault.end;

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
    initialData: isDefaultQuery ? options?.initialData : undefined,
    enabled,
  });

  // Fetch team stats (with date filter + drill-down officer)
  const teamStatsQuery = useQuery({
    queryKey: ["officer", "team-stats", startDate, endDate, officerId],
    queryFn: () => fetchTeamStats(startDate, endDate, officerId),
    staleTime: 300000,
    enabled,
  });

  // Socket.IO integration for real-time updates
  useEffect(() => {
    if (!socket.connected) {
      socket.connect();
    }

    const handleDataUpdate = (...args: unknown[]) => {
      const data = args[0] as { resource: string };
      if (data.resource === "lead" || data.resource === "consultation") {
        queryClient.invalidateQueries({ queryKey: ["officer"] });
      }
    };

    const handleLeadChange = () => {
      queryClient.invalidateQueries({ queryKey: ["officer"] });
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
