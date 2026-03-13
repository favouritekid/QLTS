// src/hooks/useDashboardStats.test.tsx
// @vitest-environment jsdom
/**
 * Contract tests for useDashboardStats hook.
 *
 * Validates:
 * - teamStatsQuery only enabled when scope === "personal"
 * - teamStatsQuery disabled for "team" and "organization" scopes
 * - dashboardQuery passes all filter params correctly
 * - dashboardQuery disabled when enabled=false
 */
import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock vn-date utilities
vi.mock("@/lib/utils/vn-date", () => ({
  todayVN: () => "2026-03-13",
  subDaysVN: (d: string, n: number) => `2026-03-0${13 - n}`, // simplified
}));

// Mock DashboardDateContext
vi.mock("@/contexts/DashboardDateContext", () => ({
  useDashboardDate: () => ({
    startDate: "2026-03-07",
    endDate: "2026-03-13",
    dateRange: {
      from: new Date(2026, 2, 7),
      to: new Date(2026, 2, 13),
    },
    preset: "7d",
  }),
  formatDateForAPI: (d: Date) => d.toISOString().slice(0, 10),
}));

// Mock API client — capture calls
const mockGet = vi.fn();
vi.mock("@/lib/api/client", () => ({
  api: {
    get: (...args: any[]) => mockGet(...args),
  },
}));

// Mock socket
vi.mock("@/lib/socket/client", () => ({
  socket: {
    connected: true,
    connect: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
  },
}));

// Import AFTER mocks
import { useDashboardStats } from "./useDashboardStats";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DASHBOARD_RESPONSE = {
  kpis: {
    consultations_today: 5,
    consultations_target: 10,
    consultations_trend: { value: 0, direction: "neutral", comparison: "" },
    active_leads: 12,
    active_leads_trend: { value: 0, direction: "neutral", comparison: "" },
    win_rate: 33,
    new_lead_conversion_rate: 15,
    avg_response_time: 2,
    avg_response_time_trend: { value: 0, direction: "neutral", comparison: "" },
    sla_compliance_rate: 80,
    consultation_effectiveness: 50,
  },
  status_overview: {
    current_workload: 12,
    max_capacity: 20,
    utilization: 60,
    availability_status: "available",
  },
  priority_actions: [],
  performance_trends: [],
  sales_funnel: [],
  actionable_lists: { high_score: [], stale: [], upcoming: [] },
};

const TEAM_STATS_RESPONSE = {
  team_avg_consultations: 8,
  team_avg_conversions: 3,
  officer_rank_percentile: 70,
  total_officers: 5,
  period_days: 7,
};

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    );
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useDashboardStats", () => {
  beforeEach(() => {
    mockGet.mockReset();
    // Default: all API calls succeed
    mockGet.mockImplementation((url: string) => {
      if (url.includes("/team-stats")) {
        return Promise.resolve({ data: TEAM_STATS_RESPONSE });
      }
      return Promise.resolve({ data: DASHBOARD_RESPONSE });
    });
  });

  it("fetches teamStats when scope is 'personal' (default)", async () => {
    const { result } = renderHook(
      () => useDashboardStats({ scope: "personal" }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.stats).toBeDefined());

    // team-stats should have been fetched
    const teamStatsCalls = mockGet.mock.calls.filter(
      (c: any[]) => typeof c[0] === "string" && c[0].includes("/team-stats"),
    );
    expect(teamStatsCalls.length).toBe(1);
  });

  it("does NOT fetch teamStats when scope is 'team'", async () => {
    const { result } = renderHook(
      () => useDashboardStats({ scope: "team" }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.stats).toBeDefined());

    const teamStatsCalls = mockGet.mock.calls.filter(
      (c: any[]) => typeof c[0] === "string" && c[0].includes("/team-stats"),
    );
    expect(teamStatsCalls.length).toBe(0);
  });

  it("does NOT fetch teamStats when scope is 'organization'", async () => {
    const { result } = renderHook(
      () => useDashboardStats({ scope: "organization" }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.stats).toBeDefined());

    const teamStatsCalls = mockGet.mock.calls.filter(
      (c: any[]) => typeof c[0] === "string" && c[0].includes("/team-stats"),
    );
    expect(teamStatsCalls.length).toBe(0);
  });

  it("passes officerId and unitId to dashboard API call", async () => {
    const { result } = renderHook(
      () => useDashboardStats({ scope: "personal", officerId: 42, unitId: 7 }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.stats).toBeDefined());

    const dashboardCalls = mockGet.mock.calls.filter(
      (c: any[]) => typeof c[0] === "string" && c[0].includes("/dashboard"),
    );
    expect(dashboardCalls.length).toBe(1);

    const url = dashboardCalls[0][0] as string;
    expect(url).toContain("officer_id=42");
    expect(url).toContain("unit_id=7");
    expect(url).toContain("scope=personal");
  });

  it("does not fetch anything when enabled=false", async () => {
    renderHook(
      () => useDashboardStats({ scope: "personal", enabled: false }),
      { wrapper: createWrapper() },
    );

    // Wait a tick to ensure no calls fire
    await new Promise((r) => setTimeout(r, 50));
    expect(mockGet).not.toHaveBeenCalled();
  });

  it("returns teamStats=undefined when scope is 'team'", async () => {
    const { result } = renderHook(
      () => useDashboardStats({ scope: "team" }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.stats).toBeDefined());

    // teamStats should be undefined because query was disabled
    expect(result.current.teamStats).toBeUndefined();
  });
});
