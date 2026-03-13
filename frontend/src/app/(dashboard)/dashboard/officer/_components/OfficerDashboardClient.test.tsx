// src/app/(dashboard)/dashboard/officer/_components/OfficerDashboardClient.test.tsx
// @vitest-environment jsdom
/**
 * Contract tests for OfficerDashboardClient.
 *
 * Validates:
 * - Quick action "new_lead" triggers router.push("/leads?action=create")
 * - Quick action "log_call" triggers toast (not navigation)
 * - Quick action "schedule" triggers toast (not navigation)
 * - handleQuickAction callback is stable (useCallback)
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — must be before component import
// ---------------------------------------------------------------------------

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, prefetch: vi.fn() }),
}));

// Mock next/dynamic to render children synchronously
vi.mock("next/dynamic", () => ({
  default: (loader: any) => {
    // Return a simple placeholder component
    return function DynamicMock() {
      return <div data-testid="dynamic-mock" />;
    };
  },
}));

const mockToastInfo = vi.fn();
vi.mock("sonner", () => ({
  toast: { info: (...args: any[]) => mockToastInfo(...args) },
}));

// Mock auth — officer role by default
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    user: { id: 1, role: "officer", username: "test" },
  }),
}));

// Mock vn-date
vi.mock("@/lib/utils/vn-date", () => ({
  todayVN: () => "2026-03-13",
  subDaysVN: () => "2026-03-07",
  startOfMonthVN: () => "2026-03-01",
}));

// Mock DashboardDateContext
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

// Mock socket
vi.mock("@/lib/socket/client", () => ({
  socket: {
    connected: true,
    connect: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
  },
}));

// Mock API — vi.fn() only; implementation set in beforeEach (mockReset: true clears it)
vi.mock("@/lib/api/client", () => ({
  api: {
    get: vi.fn(),
  },
}));

// Mock UI components to simplify rendering
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

// Mock all dashboard sub-components — only SmartHeader needs to call onQuickAction
let capturedOnQuickAction: ((action: string) => void) | undefined;

vi.mock("@/components/officer/dashboard", () => ({
  KPICardsGrid: () => <div data-testid="kpi-cards" />,
  ActionInsightsPanel: () => <div data-testid="action-insights" />,
  WeeklyLeaderboard: () => <div data-testid="leaderboard" />,
  AnnualProgressCard: () => <div data-testid="annual-progress" />,
  SmartHeader: (props: any) => {
    capturedOnQuickAction = props.onQuickAction;
    return (
      <div data-testid="smart-header">
        <button data-testid="qa-new-lead" onClick={() => props.onQuickAction?.("new_lead")}>
          New Lead
        </button>
        <button data-testid="qa-log-call" onClick={() => props.onQuickAction?.("log_call")}>
          Log Call
        </button>
        <button data-testid="qa-schedule" onClick={() => props.onQuickAction?.("schedule")}>
          Schedule
        </button>
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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OfficerDashboardClient quick actions", () => {
  beforeEach(() => {
    mockPush.mockReset();
    mockToastInfo.mockReset();
    capturedOnQuickAction = undefined;
    // Re-setup api.get mock (mockReset: true in vitest config clears it between tests)
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: DASHBOARD_RESPONSE });
  });

  it("navigates to /leads?action=create on 'new_lead' quick action", async () => {
    renderWithProviders();

    // Wait for data to load and component to render
    await waitFor(() => {
      expect(screen.getByTestId("smart-header")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("qa-new-lead"));
    expect(mockPush).toHaveBeenCalledWith("/leads?action=create");
  });

  it("shows toast (not navigation) on 'log_call' quick action", async () => {
    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("smart-header")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("qa-log-call"));
    expect(mockToastInfo).toHaveBeenCalledWith("Tính năng đang phát triển");
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("shows toast (not navigation) on 'schedule' quick action", async () => {
    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("smart-header")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("qa-schedule"));
    expect(mockToastInfo).toHaveBeenCalledWith("Tính năng đang phát triển");
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("onQuickAction callback reference is stable across re-renders", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const ui = (
      <QueryClientProvider client={queryClient}>
        <OfficerDashboardClient />
      </QueryClientProvider>
    );

    const { rerender } = render(ui);

    await waitFor(() => {
      expect(screen.getByTestId("smart-header")).toBeInTheDocument();
    });

    const firstRef = capturedOnQuickAction;
    expect(firstRef).toBeDefined();

    // Force a full re-render of the component tree
    rerender(ui);

    await waitFor(() => {
      expect(screen.getByTestId("smart-header")).toBeInTheDocument();
    });

    // The callback reference should be the same (useCallback)
    expect(capturedOnQuickAction).toBe(firstRef);
  });
});
