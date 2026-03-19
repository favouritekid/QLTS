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

// Mock officer API module for useOfficerKpiPlan tests
const mockGetMyKpiPlan = vi.fn();
vi.mock("@/lib/api/officer", () => ({
  officerApi: {
    getMyKpiPlan: (...args: any[]) => mockGetMyKpiPlan(...args),
  },
}));

// Import AFTER mocks
import { useDashboardStats, useOfficerKpiPlan } from "./useDashboardStats";

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


// =============================================================================
// useOfficerKpiPlan — Gap 2 contract tests
// =============================================================================

const KPI_PLAN_RESPONSE = {
  fiscal_year: 2026,
  annual_target: 80,
  achieved_ytd: 25,
  progress_pct: 31.3,
  source: "officer" as const,
  months: Array.from({ length: 12 }, (_, i) => ({
    month: i + 1,
    enrollment_target: 7,
    enrollment_actual: i < 3 ? 8 : null,
    working_days: 22,
    consultations_daily: 10,
    consultations_monthly_total: 220,
    conversion_rate: 15,
    win_rate: 33,
  })),
};

describe("useOfficerKpiPlan", () => {
  beforeEach(() => {
    mockGetMyKpiPlan.mockReset();
  });

  it("returns plan data on successful 200 response", async () => {
    mockGetMyKpiPlan.mockResolvedValue(KPI_PLAN_RESPONSE);

    const { result } = renderHook(
      () => useOfficerKpiPlan({ fiscalYear: 2026, enabled: true }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(KPI_PLAN_RESPONSE);
    expect(result.current.error).toBeNull();
  });

  it("returns null data on 200+null response (no plan exists)", async () => {
    mockGetMyKpiPlan.mockResolvedValue(null);

    const { result } = renderHook(
      () => useOfficerKpiPlan({ fiscalYear: 2026, enabled: true }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("propagates 404 IDOR error to error state (not swallowed)", async () => {
    const idorError = { response: { status: 404 }, message: "Not found" };
    mockGetMyKpiPlan.mockRejectedValue(idorError);

    const { result } = renderHook(
      () => useOfficerKpiPlan({ fiscalYear: 2026, officerId: 999, enabled: true }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
    expect(result.current.error).toBe(idorError);
  });

  it("propagates 400 BusinessRuleViolation to error state", async () => {
    const brError = { response: { status: 400 }, message: "officer_id required" };
    mockGetMyKpiPlan.mockRejectedValue(brError);

    const { result } = renderHook(
      () => useOfficerKpiPlan({ fiscalYear: 2026, enabled: true }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBe(brError);
  });

  it("does not fetch when enabled=false", async () => {
    renderHook(
      () => useOfficerKpiPlan({ fiscalYear: 2026, enabled: false }),
      { wrapper: createWrapper() },
    );

    await new Promise((r) => setTimeout(r, 50));
    expect(mockGetMyKpiPlan).not.toHaveBeenCalled();
  });

  it("passes officerId to API call when provided", async () => {
    mockGetMyKpiPlan.mockResolvedValue(KPI_PLAN_RESPONSE);

    const { result } = renderHook(
      () => useOfficerKpiPlan({ fiscalYear: 2026, officerId: 42, enabled: true }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockGetMyKpiPlan).toHaveBeenCalledWith(2026, 42);
  });
});
