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

// Dynamic mock: identify which component dynamic() loads via loader.toString()
vi.mock("next/dynamic", () => ({
  default: (loader: any) => {
    const src = loader.toString();
    let testId = "dynamic-mock";
    if (src.includes("FunnelChart")) testId = "funnel-chart";
    else if (src.includes("FunnelTable")) testId = "funnel-table";
    else if (src.includes("PerformanceChart")) testId = "performance-chart";
    return function DynamicMock() {
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

vi.mock("@/contexts/DashboardDateContext", () => ({
  DashboardDateProvider: ({ children }: any) => <>{children}</>,
  useDashboardDate: () => ({
    startDate: "2026-03-07",
    endDate: "2026-03-13",
    dateRange: { from: new Date(2026, 2, 7), to: new Date(2026, 2, 13) },
    preset: "7d",
    setPreset: vi.fn(),
    setCustomRange: vi.fn(),
  }),
  DATE_PRESET_LABELS: { "7d": "7 ngày", "30d": "30 ngày", "this_month": "Tháng này", "custom": "Tùy chọn" },
  formatDateForAPI: (d: Date) => d.toISOString().slice(0, 10),
}));

vi.mock("@/lib/socket/client", () => ({
  socket: { connected: true, connect: vi.fn(), on: vi.fn(), off: vi.fn() },
}));

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn() },
}));

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

vi.mock("@/components/officer/dashboard", () => ({
  KPICardsGrid: (props: any) => {
    kpiGridProps = props;
    return <div data-testid="kpi-cards" />;
  },
  ActionInsightsPanel: () => <div data-testid="action-insights" />,
  WeeklyLeaderboard: () => <div data-testid="leaderboard" />,
  AnnualProgressCard: () => <div data-testid="annual-progress" />,
  MonthlyBreakdownCard: () => <div data-testid="monthly-breakdown" />,
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

  beforeEach(() => {
    originalLocation = window.location;
    mockPush.mockReset();
    headerProps = {};
    kpiGridProps = {};
    (mockUser as any).role = "officer";
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: DASHBOARD_RESPONSE });
    setUrlSearch("");
  });

  afterEach(() => {
    Object.defineProperty(window, "location", { value: originalLocation, writable: true });
  });

  // =========================================================================
  // Quick actions
  // =========================================================================

  it("navigates to /leads?action=create on 'new_lead' quick action", async () => {
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("smart-header")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("qa-new-lead"));
    expect(mockPush).toHaveBeenCalledWith("/leads?action=create");
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
    setUrlSearch("?scope=team");
    renderWithProviders();
    // SmartHeader receives scope prop = "team" (from URL), not "personal" (from role)
    await waitFor(() => {
      expect(screen.getByTestId("scope-value")).toHaveTextContent("team");
      expect(headerProps.scope).toBe("team");
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

    setUrlSearch("?scope=team");
    act(() => { window.dispatchEvent(new PopStateEvent("popstate")); });
    await waitFor(() => expect(headerProps.scope).toBe("team"));
  });

  it("resets scope to role-derived default on popstate when URL has no scope", async () => {
    setUrlSearch("?scope=team");
    renderWithProviders();
    await waitFor(() => expect(headerProps.scope).toBe("team"));

    // Navigate back to URL without scope
    setUrlSearch("");
    act(() => { window.dispatchEvent(new PopStateEvent("popstate")); });
    // Must reset to "personal" (officer role default), not keep stale "team"
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
    // Assert the actual prop received by KPICardsGrid mock, not just the fixture
    expect(kpiGridProps.kpis).toBeDefined();
    expect(kpiGridProps.kpis.avg_response_time_target).toBe(4);
    expect(kpiGridProps.kpis.avg_response_time).toBe(2);
  });
});
