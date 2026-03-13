import { api } from "./client";

export interface LeaderboardEntry {
  rank: number;
  user_id: number;
  username: string;
  full_name: string;
  consultations: number;
  is_current_user: boolean;
  is_focus_officer?: boolean;
  rank_change?: number | null;
}

export interface WeeklyLeaderboardData {
  week_start: string;
  week_end?: string;
  total_officers: number;
  current_user_rank: number | null;
  leaderboard: LeaderboardEntry[];
}

export interface LeaderboardFilters {
  startDate?: string;
  endDate?: string;
  scope?: "personal" | "team" | "organization";
  unitId?: number | null;
  officerId?: number | null;
}

export interface ScheduleActivity {
  id: number;
  lead_id: number;
  lead_name: string;
  time: string;
  date: string;
  day: number;
}

export interface UpcomingActivitiesResponse {
  activities: ScheduleActivity[];
  dates_with_activities: number[];
  month: number;
  year: number;
}

export interface Recommendation {
  type: string;
  priority: "critical" | "high" | "medium" | "low";
  title: string;
  message: string;
  action?: string | null;
  action_link?: string | null;
  expected_impact?: string;
}

export interface RecommendationsResponse {
  recommendations: Recommendation[];
  count: number;
}

export interface AvailabilityPayload {
  availability_status: string;
}

/**
 * Officer API Service
 * Handles all officer dashboard related endpoints
 */
export const officerApi = {
  getLeaderboard: async (filters?: LeaderboardFilters) => {
    const params = new URLSearchParams();
    if (filters?.startDate) params.append("start_date", filters.startDate);
    if (filters?.endDate) params.append("end_date", filters.endDate);
    if (filters?.scope) params.append("scope", filters.scope);
    if (filters?.unitId) params.append("unit_id", filters.unitId.toString());
    if (filters?.officerId) params.append("officer_id", filters.officerId.toString());

    const url = `/api/officer/leaderboard${params.toString() ? `?${params.toString()}` : ""}`;
    const response = await api.get<WeeklyLeaderboardData>(url);
    return response.data;
  },

  getUpcomingActivities: async (month: number, year: number, scope?: string, unitId?: number, officerId?: number) => {
    const params: Record<string, string | number> = { month, year };
    if (scope) params.scope = scope;
    if (unitId) params.unit_id = unitId;
    if (officerId) params.officer_id = officerId;
    const response = await api.get<UpcomingActivitiesResponse>("/api/officer/upcoming-activities", {
      params,
    });
    return response.data;
  },

  getRecommendations: async (limit: number = 5, startDate?: string, endDate?: string, officerId?: number) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (startDate) params.append("start_date", startDate);
    if (endDate) params.append("end_date", endDate);
    if (officerId) params.append("officer_id", String(officerId));
    const response = await api.get<RecommendationsResponse>(
      `/api/officer/recommendations?${params}`
    );
    return response.data;
  },

  updateAvailability: async (data: AvailabilityPayload) => {
    const response = await api.post("/api/officer/availability", data);
    return response.data;
  },

  getMyKpiPlan: async (fiscalYear: number, officerId?: number): Promise<OfficerKpiPlanResponse | null> => {
    const params = new URLSearchParams({ fiscal_year: String(fiscalYear) });
    if (officerId) params.append("officer_id", String(officerId));
    const response = await api.get<OfficerKpiPlanResponse | null>(
      `/api/officer/my-kpi-plan?${params}`
    );
    return response.data;
  },
};

// =============================================================================
// GAP 2: Monthly KPI Plan Types
// =============================================================================

export interface OfficerPlanMonthSummary {
  month: number;
  enrollment_target: number;
  enrollment_actual: number | null;
  working_days: number;
  consultations_daily: number | null;
  consultations_monthly_total: number | null;
  conversion_rate: number | null;
  win_rate: number | null;
}

export interface OfficerKpiPlanResponse {
  fiscal_year: number;
  annual_target: number;
  achieved_ytd: number;
  progress_pct: number;
  months: OfficerPlanMonthSummary[];
  source: "officer" | "unit";
}
