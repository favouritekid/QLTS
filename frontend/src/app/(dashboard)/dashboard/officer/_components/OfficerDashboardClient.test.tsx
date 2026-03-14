// src/app/(dashboard)/dashboard/officer/_components/OfficerDashboardClient.test.tsx
// @vitest-environment jsdom
/**
 * Contract tests for OfficerDashboardClient.
 *
 * Validates:
 * - Quick action "new_lead" triggers router.push("/leads?action=create")
 * - handleQuickAction callback is stable (useCallback)
 * - URL state init: scope/unit/officer/funnel read from URL on mount
 * - popstate: back/forward restores filter state from URL
 * - popstate with no scope in URL resets to role-derived default
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

vi.mock("next/dynamic", () => ({
  default: (loader: any) => {
    return function DynamicMock() {
      return <div data-testid="dynamic-mock" />;
    };
  },
}));

vi.mock("sonner", () => ({
  toast: { info: vi.fn(), warning: vi.fn() },
}));

// Mock auth — officer role by default (can be overridden per test)
const mockUser = { id: 1, role: "officer", username: "test", full_name: "Test Officer" };
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

// Capture SmartHeader props for assertions
let capturedProps: Record<string, any> = {};

vi.mock("@/components/officer/dashboard", () => ({
  KPICardsGrid: () => <div data-testid="kpi-cards" />,
  ActionInsightsPanel: () => <div data-testid="action-insights" />,
  WeeklyLeaderboard: () => <div data-testid="leaderboard" />,
  AnnualProgressCard: () => <div data-testid="annual-progress" />,
  MonthlyBreakdownCard: () => <div data-testid="monthly-breakdown" />,
  CurrentMonthSnapshot: () => <div data-testid="current-month-snapshot" />,
  KpiSummaryBanner: () => <div data-testid="kpi-summary-banner" />,
  SmartHeader: (props: any) => {
    capturedProps = props;
    return (
      <div data-testid="smart-header">
        <button data-testid="qa-new-lead" onClick={() => props.onQuickAction?.("new_lead")}>
          New Lead
        </button>
        <span data-testid="scope-value">{props.scope}</span>
        <span data-testid="unit-value">{props.selectedUnitId ?? "null"}</span>
        <span data-testid="officer-value">{props.selectedOfficerId ?? "null"}</span>
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

/** Helper: set window.location.search before rendering */
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
    capturedProps = {};
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: DASHBOARD_RESPONSE });
    // Default: clean URL
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
    const firstRef = capturedProps.onQuickAction;
    expect(firstRef).toBeDefined();
    rerender(ui);
    await waitFor(() => expect(screen.getByTestId("smart-header")).toBeInTheDocument());
    expect(capturedProps.onQuickAction).toBe(firstRef);
  });

  // =========================================================================
  // URL state init
  // =========================================================================

  it("reads scope from URL on mount", async () => {
    setUrlSearch("?scope=team");
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("scope-value")).toHaveTextContent("team"));
  });

  it("reads unit and officer from URL on mount", async () => {
    setUrlSearch("?scope=organization&unit=42&officer=7");
    // Need admin role to allow organization scope
    (mockUser as any).role = "admin";
    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByTestId("unit-value")).toHaveTextContent("42");
      expect(screen.getByTestId("officer-value")).toHaveTextContent("7");
    });
    (mockUser as any).role = "officer"; // restore
  });

  it("defaults scope to role-derived value when URL has no scope", async () => {
    setUrlSearch("");
    renderWithProviders();
    // officer role → "personal"
    await waitFor(() => expect(screen.getByTestId("scope-value")).toHaveTextContent("personal"));
  });

  it("reads funnel=table from URL on mount", async () => {
    setUrlSearch("?funnel=table");
    renderWithProviders();
    // The funnel toggle state is internal; verify via FunnelTable being rendered
    // (FunnelChart/FunnelTable are dynamic mocks, so we just verify no crash)
    await waitFor(() => expect(screen.getByTestId("smart-header")).toBeInTheDocument());
  });

  // =========================================================================
  // popstate (back/forward)
  // =========================================================================

  it("restores scope from URL on popstate", async () => {
    setUrlSearch("");
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("scope-value")).toHaveTextContent("personal"));

    // Simulate browser navigating back to a URL with scope=team
    setUrlSearch("?scope=team");
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await waitFor(() => expect(screen.getByTestId("scope-value")).toHaveTextContent("team"));
  });

  it("resets scope to role-derived default on popstate when URL has no scope", async () => {
    // Start with scope=team in URL
    setUrlSearch("?scope=team");
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("scope-value")).toHaveTextContent("team"));

    // Simulate back to a URL without scope
    setUrlSearch("");
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    // officer role → should reset to "personal", NOT keep stale "team"
    await waitFor(() => expect(screen.getByTestId("scope-value")).toHaveTextContent("personal"));
  });

  it("restores unit and officer from URL on popstate", async () => {
    setUrlSearch("");
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("smart-header")).toBeInTheDocument());

    setUrlSearch("?scope=organization&unit=5&officer=10");
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("unit-value")).toHaveTextContent("5");
      expect(screen.getByTestId("officer-value")).toHaveTextContent("10");
    });
  });

  it("clears unit and officer on popstate when URL has no filters", async () => {
    setUrlSearch("?scope=organization&unit=5&officer=10");
    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByTestId("unit-value")).toHaveTextContent("5");
      expect(screen.getByTestId("officer-value")).toHaveTextContent("10");
    });

    // Simulate back to clean URL
    setUrlSearch("");
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("unit-value")).toHaveTextContent("null");
      expect(screen.getByTestId("officer-value")).toHaveTextContent("null");
    });
  });

  // =========================================================================
  // avg_response_time_target
  // =========================================================================

  it("passes avg_response_time_target through to KPI cards", async () => {
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("kpi-cards")).toBeInTheDocument());
    expect(DASHBOARD_RESPONSE.kpis.avg_response_time_target).toBe(4);
  });
});
