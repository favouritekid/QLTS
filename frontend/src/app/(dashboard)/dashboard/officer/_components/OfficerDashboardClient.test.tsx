// src/app/(dashboard)/dashboard/officer/_components/OfficerDashboardClient.test.tsx
// @vitest-environment jsdom
/**
 * Contract tests for OfficerDashboardClient.
 *
 * Validates:
 * - Quick actions
 * - URL state init: scope/unit/officer/funnel read from URL on mount
 * - popstate: back/forward restores all filter state from URL
 * - KPI props pass-through (avg_response_time_target)
 */
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — must be before component import
// ---------------------------------------------------------------------------

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, prefetch: vi.fn() }),
}));

// Dynamic mock: identify by loader.toString(), capture PerformanceChart props
let perfChartProps: Record<string, any> = {};
vi.mock("next/dynamic", () => ({
  default: (loader: any) => {
    const src = loader.toString();
    let testId = "dynamic-mock";
    if (src.includes("FunnelChart")) testId = "funnel-chart";
    else if (src.includes("FunnelTable")) testId = "funnel-table";
    else if (src.includes("PerformanceChart")) testId = "performance-chart";
    return function DynamicMock(props: any) {
      if (testId === "performance-chart") perfChartProps = props;
      return <div data-testid={testId} />;
    };
  },
}));

vi.mock("sonner", () => ({
  toast: { info: vi.fn(), warning: vi.fn() },
}));

// Mock auth — mutable role for per-test override
const mockUser = { id: 1, role: "officer", username: "test", full_name: "Test Officer", unit_id: 10 };
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: mockUser }),
}));

vi.mock("@/lib/utils/vn-date", () => ({
  todayVN: () => "2026-03-13",
  subDaysVN: () => "2026-03-07",
  startOfMonthVN: () => "2026-03-01",
}));

// Mutable date context — tests can override mockDateContext to simulate historical ranges
let mockDateContext = {
  startDate: "2026-03-07",
  endDate: "2026-03-13",
  dateRange: { from: new Date(2026, 2, 7), to: new Date(2026, 2, 13) } as { from: Date; to: Date },
  preset: "7d" as string,
  setPreset: vi.fn(),
  setCustomRange: vi.fn(),
};
vi.mock("@/contexts/DashboardDateContext", () => ({
  DashboardDateProvider: ({ children }: any) => <>{children}</>,
  useDashboardDate: () => mockDateContext,
  DATE_PRESET_LABELS: { "7d": "7 ngày", "30d": "30 ngày", "this_month": "Tháng này", "custom": "Tùy chọn" },
  formatDateForAPI: (d: Date) => d.toISOString().slice(0, 10),
}));

vi.mock("@/lib/socket/client", () => ({
  socket: { connected: true, connect: vi.fn(), on: vi.fn(), off: vi.fn() },
}));

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn() },
}));

// Mock officerApi (needed for module resolution, actual data controlled via useOfficerKpiPlan below)
vi.mock("@/lib/api/officer", () => ({
  officerApi: { getMyKpiPlan: () => Promise.resolve(null) },
}));

// Partially mock useDashboardStats module: keep useDashboardStats real, override useOfficerKpiPlan
// to return data synchronously (avoids React Query async timing issues in jsdom)
(globalThis as any).__kpiPlanMockValue = null;
vi.mock("@/hooks/useDashboardStats", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useDashboardStats")>();
  return {
    ...actual,
    useOfficerKpiPlan: () => ({
      data: (globalThis as any).__kpiPlanMockValue,
      isLoading: false,
      error: null,
      refetch: () => {},
    }),
  };
});

vi.mock("@/components/ui/skeleton", () => ({
  Skeleton: ({ className }: any) => <div className={className} />,
}));

vi.mock("@/components/ui/alert", () => ({
  Alert: ({ children }: any) => <div>{children}</div>,
  AlertDescription: ({ children }: any) => <div>{children}</div>,
  AlertTitle: ({ children }: any) => <div>{children}</div>,
}));

vi.mock("lucide-react", () => ({
  AlertCircle: () => <span />,
  Info: () => <span />,
  BarChart3: () => <span />,
  Table2: () => <span />,
}));

// Capture props passed to key sub-components
let headerProps: Record<string, any> = {};
let kpiGridProps: Record<string, any> = {};
let monthlyProps: Record<string, any> = {};
let distributionProps: Record<string, any> = {};

vi.mock("@/components/officer/dashboard", () => ({
  KPICardsGrid: (props: any) => {
    kpiGridProps = props;
    return <div data-testid="kpi-cards" />;
  },
  ActionInsightsPanel: () => <div data-testid="action-insights" />,
  WeeklyLeaderboard: () => <div data-testid="leaderboard" />,
  OfficerDistributionPanel: (props: any) => {
    distributionProps = props;
    return <div data-testid="distribution-panel" />;
  },
  AnnualProgressCard: () => <div data-testid="annual-progress" />,
  MonthlyBreakdownCard: (props: any) => {
    monthlyProps = props;
    return <div data-testid="monthly-breakdown" />;
  },
  CurrentMonthSnapshot: () => <div data-testid="current-month-snapshot" />,
  KpiSummaryBanner: () => <div data-testid="kpi-summary-banner" />,
  SmartHeader: (props: any) => {
    headerProps = props;
    return (
      <div data-testid="smart-header">
        <button data-testid="qa-new-lead" onClick={() => props.onQuickAction?.("new_lead")}>
          New Lead
        </button>
        <span data-testid="scope-value">{props.scope}</span>
        <span data-testid="unit-value">{String(props.selectedUnitId ?? "null")}</span>
        <span data-testid="officer-value">{String(props.selectedOfficerId ?? "null")}</span>
      </div>
    );
  },
}));

vi.mock("@/components/officer/WorkloadCard", () => ({
  WorkloadCard: () => <div data-testid="workload-card" />,
}));

vi.mock("@/components/officer/TodaySchedule", () => ({
  TodaySchedule: () => <div data-testid="today-schedule" />,
}));

// Import component and mocked modules AFTER all mocks
import { OfficerDashboardClient } from "./OfficerDashboardClient";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

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
    avg_response_time_target: 4,
    sla_compliance_rate: 80,
    consultation_effectiveness: 50,
    consultations_avg_per_day: 7,
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

function renderWithProviders() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <OfficerDashboardClient />
    </QueryClientProvider>,
  );
}

/** Helper: set window.location.search before rendering or before popstate */
function setUrlSearch(search: string) {
  Object.defineProperty(window, "location", {
    value: { ...window.location, search, pathname: "/dashboard/officer" },
    writable: true,
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OfficerDashboardClient", () => {
  let originalLocation: Location;

  beforeEach(async () => {
    originalLocation = window.location;
    mockPush.mockReset();
    headerProps = {};
    kpiGridProps = {};
    monthlyProps = {};
    perfChartProps = {};
    (mockUser as any).role = "officer";
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: DASHBOARD_RESPONSE });
    (globalThis as any).__kpiPlanMockValue = null; // default: no plan
    // Reset date context to current-month-inclusive range
    mockDateContext = {
      startDate: "2026-03-07",
      endDate: "2026-03-13",
      dateRange: { from: new Date(2026, 2, 7), to: new Date(2026, 2, 13) },
      preset: "7d",
      setPreset: vi.fn(),
      setCustomRange: vi.fn(),
    };
    setUrlSearch("");
  });

  afterEach(() => {
    Object.defineProperty(window, "location", { value: originalLocation, writable: true });
  });

  // =========================================================================
  // Quick actions
  // =========================================================================

  it("navigates to dashboard create context on 'new_lead' quick action", async () => {
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("smart-header")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("qa-new-lead"));
    expect(mockPush).toHaveBeenCalledWith("/leads?nav_source=dashboard&action=create");
  });

  it("onQuickAction callback reference is stable across re-renders", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const ui = (
      <QueryClientProvider client={queryClient}>
        <OfficerDashboardClient />
      </QueryClientProvider>
    );
    const { rerender } = render(ui);
    await waitFor(() => expect(screen.getByTestId("smart-header")).toBeInTheDocument());
    const firstRef = headerProps.onQuickAction;
    expect(firstRef).toBeDefined();
    rerender(ui);
    await waitFor(() => expect(screen.getByTestId("smart-header")).toBeInTheDocument());
    expect(headerProps.onQuickAction).toBe(firstRef);
  });

  // =========================================================================
  // URL state init — scope
  // =========================================================================

  it("initializes scope from URL and passes it as prop to SmartHeader", async () => {
    setUrlSearch("?scope=unit");
    renderWithProviders();
    // SmartHeader receives scope prop = "unit" (from URL), not "personal" (from role)
    await waitFor(() => {
      expect(screen.getByTestId("scope-value")).toHaveTextContent("unit");
      expect(headerProps.scope).toBe("unit");
    });
  });

  it("defaults scope to role-derived value when URL has no scope param", async () => {
    setUrlSearch("");
    renderWithProviders();
    // officer role → "personal"
    await waitFor(() => {
      expect(headerProps.scope).toBe("personal");
    });
  });

  // =========================================================================
  // Hydration gate — unsupported role (PR #325 hasMounted)
  // =========================================================================

  it("renders 'Không có quyền' alert when persisted user.role is unsupported (e.g. accountant)", async () => {
    // PR #324 Commit 1 Known Limitation closure: accountant/user/other roles
    // landing on /dashboard/officer manually (no nav entry) used to mismatch
    // (SSR skeleton vs client Alert). hasMounted gate aligns first client
    // render with SSR; Alert fires NEXT render post-mount.
    (mockUser as any).role = "accountant";
    setUrlSearch("");
    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByText("Không có quyền truy cập")).toBeInTheDocument();
    });
    // SmartHeader (supported-role branch) must NOT render
    expect(screen.queryByTestId("smart-header")).not.toBeInTheDocument();
  });

  // =========================================================================
  // URL state init — unit / officer
  // =========================================================================

  it("initializes unit and officer from URL and passes them as props", async () => {
    setUrlSearch("?scope=organization&unit=42&officer=7");
    (mockUser as any).role = "admin";
    renderWithProviders();
    await waitFor(() => {
      expect(headerProps.selectedUnitId).toBe(42);
      expect(headerProps.selectedOfficerId).toBe(7);
    });
  });

  it("passes null for unit and officer when URL has no filter params", async () => {
    setUrlSearch("?scope=personal");
    renderWithProviders();
    await waitFor(() => {
      expect(headerProps.selectedUnitId).toBeNull();
      expect(headerProps.selectedOfficerId).toBeNull();
    });
  });

  // =========================================================================
  // URL state init — funnel view mode
  // =========================================================================

  it("renders FunnelChart (not FunnelTable) when URL has no funnel param", async () => {
    setUrlSearch("");
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("smart-header")).toBeInTheDocument());
    // default = chart view → FunnelChart rendered, FunnelTable not
    expect(screen.getByTestId("funnel-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("funnel-table")).not.toBeInTheDocument();
  });

  it("renders FunnelTable (not FunnelChart) when URL has funnel=table", async () => {
    setUrlSearch("?funnel=table");
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("smart-header")).toBeInTheDocument());
    // funnel=table → FunnelTable rendered, FunnelChart not
    expect(screen.getByTestId("funnel-table")).toBeInTheDocument();
    expect(screen.queryByTestId("funnel-chart")).not.toBeInTheDocument();
  });

  // =========================================================================
  // popstate (back/forward)
  // =========================================================================

  it("restores scope from URL on popstate (back to a different scope)", async () => {
    setUrlSearch("");
    renderWithProviders();
    await waitFor(() => expect(headerProps.scope).toBe("personal"));

    setUrlSearch("?scope=unit");
    act(() => { window.dispatchEvent(new PopStateEvent("popstate")); });
    await waitFor(() => expect(headerProps.scope).toBe("unit"));
  });

  it("resets scope to role-derived default on popstate when URL has no scope", async () => {
    setUrlSearch("?scope=unit");
    renderWithProviders();
    await waitFor(() => expect(headerProps.scope).toBe("unit"));

    // Navigate back to URL without scope
    setUrlSearch("");
    act(() => { window.dispatchEvent(new PopStateEvent("popstate")); });
    // Must reset to "personal" (officer role default), not keep stale "unit"
    await waitFor(() => expect(headerProps.scope).toBe("personal"));
  });

  it("restores unit and officer from URL on popstate", async () => {
    setUrlSearch("");
    renderWithProviders();
    await waitFor(() => expect(headerProps.scope).toBeDefined());

    setUrlSearch("?scope=organization&unit=5&officer=10");
    act(() => { window.dispatchEvent(new PopStateEvent("popstate")); });
    await waitFor(() => {
      expect(headerProps.selectedUnitId).toBe(5);
      expect(headerProps.selectedOfficerId).toBe(10);
    });
  });

  it("clears unit and officer on popstate to URL without filters", async () => {
    setUrlSearch("?scope=organization&unit=5&officer=10");
    renderWithProviders();
    await waitFor(() => {
      expect(headerProps.selectedUnitId).toBe(5);
      expect(headerProps.selectedOfficerId).toBe(10);
    });

    setUrlSearch("");
    act(() => { window.dispatchEvent(new PopStateEvent("popstate")); });
    await waitFor(() => {
      expect(headerProps.selectedUnitId).toBeNull();
      expect(headerProps.selectedOfficerId).toBeNull();
    });
  });

  it("restores funnel view mode from URL on popstate", async () => {
    // Start with chart (default)
    setUrlSearch("");
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("funnel-chart")).toBeInTheDocument());

    // Back to funnel=table
    setUrlSearch("?funnel=table");
    act(() => { window.dispatchEvent(new PopStateEvent("popstate")); });
    await waitFor(() => {
      expect(screen.getByTestId("funnel-table")).toBeInTheDocument();
      expect(screen.queryByTestId("funnel-chart")).not.toBeInTheDocument();
    });
  });

  // =========================================================================
  // KPI props pass-through
  // =========================================================================

  it("passes kpis including avg_response_time_target to KPICardsGrid", async () => {
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("kpi-cards")).toBeInTheDocument());
    expect(kpiGridProps.kpis).toBeDefined();
    expect(kpiGridProps.kpis.avg_response_time_target).toBe(4);
    expect(kpiGridProps.kpis.avg_response_time).toBe(2);
  });

  // =========================================================================
  // URL state — monthly expanded
  // =========================================================================

  it("passes expanded=false to MonthlyBreakdownCard when URL has no monthly param", async () => {
    setUrlSearch("");
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("monthly-breakdown")).toBeInTheDocument());
    expect(monthlyProps.expanded).toBe(false);
  });

  it("passes expanded=true to MonthlyBreakdownCard when URL has monthly=expanded", async () => {
    setUrlSearch("?monthly=expanded");
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("monthly-breakdown")).toBeInTheDocument());
    expect(monthlyProps.expanded).toBe(true);
  });

  it("restores monthly expanded state from URL on popstate", async () => {
    setUrlSearch("");
    renderWithProviders();
    await waitFor(() => expect(monthlyProps.expanded).toBe(false));

    setUrlSearch("?monthly=expanded");
    act(() => { window.dispatchEvent(new PopStateEvent("popstate")); });
    await waitFor(() => expect(monthlyProps.expanded).toBe(true));
  });

  it("clears monthly expanded on popstate when URL has no monthly param", async () => {
    setUrlSearch("?monthly=expanded");
    renderWithProviders();
    await waitFor(() => expect(monthlyProps.expanded).toBe(true));

    setUrlSearch("");
    act(() => { window.dispatchEvent(new PopStateEvent("popstate")); });
    await waitFor(() => expect(monthlyProps.expanded).toBe(false));
  });

  // =========================================================================
  // Enrollment pace benchmark integration
  // =========================================================================

  it("passes enrollmentPace=null to PerformanceChart when no KPI plan data", async () => {
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("performance-chart")).toBeInTheDocument());
    // officerApi.getMyKpiPlan returns null → no pace
    expect(perfChartProps.enrollmentPace).toBeNull();
  });

  it("passes non-null enrollmentPace to PerformanceChart when KPI plan exists and range includes today", async () => {
    // Set scope + date range that includes real today (useMemo uses new Date() internally)
    setUrlSearch("?scope=personal");
    const now = new Date();
    const weekAgo = new Date(now); weekAgo.setDate(now.getDate() - 6);
    const weekAhead = new Date(now); weekAhead.setDate(now.getDate() + 1);
    mockDateContext = {
      ...mockDateContext,
      dateRange: { from: weekAgo, to: weekAhead },
      startDate: weekAgo.toISOString().slice(0, 10),
      endDate: weekAhead.toISOString().slice(0, 10),
    };
    const currentMonth = now.getMonth() + 1;
    (globalThis as any).__kpiPlanMockValue = {
      fiscal_year: now.getFullYear(),
      annual_target: 80,
      achieved_ytd: 40,
      progress_pct: 50,
      source: "officer",
      months: [{
        month: currentMonth,
        enrollment_target: 12,
        enrollment_actual: 5,
        working_days: 22,
        consultations_daily: 6,
        consultations_actual_avg: 5.5,
        consultations_monthly_total: 88,
        conversion_rate: 22,
        win_rate: 30,
      }],
    };
    renderWithProviders();
    // Wait until PerformanceChart receives enrollmentPace with .pace property
    await waitFor(() => {
      expect(perfChartProps.enrollmentPace).toBeTruthy();
      expect(perfChartProps.enrollmentPace.pace).toBeDefined();
    }, { timeout: 3000 });
    expect(perfChartProps.enrollmentPace.pace).toBeGreaterThan(0);
    expect(perfChartProps.enrollmentPace.label).toBe("5/12");
    expect(typeof perfChartProps.enrollmentPace.onTrack).toBe("boolean");
  });

  it("passes enrollmentPace=null when date range is historical (today not in range)", async () => {
    // Set date context to a past range that doesn't include today
    mockDateContext = {
      ...mockDateContext,
      startDate: "2026-01-01",
      endDate: "2026-01-31",
      dateRange: { from: new Date(2026, 0, 1), to: new Date(2026, 0, 31) },
      preset: "custom",
    };
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("performance-chart")).toBeInTheDocument());
    expect(perfChartProps.enrollmentPace).toBeNull();
  });

  it("mounts OfficerDistributionPanel without officerId (bảng so cả đơn vị)", async () => {
    renderWithProviders();
    await waitFor(() =>
      expect(screen.getByTestId("distribution-panel")).toBeInTheDocument()
    );
    // Bảng điểm bận so sánh CẢ đơn vị; truyền officerId sẽ khiến backend
    // drill-down còn 1 dòng và mất ý nghĩa so sánh ⇒ ghim là không truyền.
    expect(distributionProps.officerId).toBeUndefined();
    expect("unitId" in distributionProps).toBe(true);
  });
});
