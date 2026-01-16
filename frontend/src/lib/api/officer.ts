import { api } from "./client";

export interface LeaderboardEntry {
  rank: number;
  user_id: number;
  username: string;
  full_name: string;
  consultations: number;
  is_current_user: boolean;
  rank_change?: number | null;
}

export interface WeeklyLeaderboardData {
  week_start: string;
  total_officers: number;
  current_user_rank: number;
  leaderboard: LeaderboardEntry[];
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
  getLeaderboard: async () => {
    const response = await api.get<WeeklyLeaderboardData>("/api/officer/leaderboard");
    return response.data;
  },

  getUpcomingActivities: async (month: number, year: number) => {
    const response = await api.get<UpcomingActivitiesResponse>("/api/officer/upcoming-activities", {
      params: { month, year },
    });
    return response.data;
  },

  getRecommendations: async (limit: number = 5) => {
    const response = await api.get<RecommendationsResponse>(`/api/officer/recommendations?limit=${limit}`);
    return response.data;
  },

  updateAvailability: async (data: AvailabilityPayload) => {
    const response = await api.post("/api/officer/availability", data);
    return response.data;
  },
};
