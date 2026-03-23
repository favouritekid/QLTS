// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockPush, mockPrefetch } = vi.hoisted(() => ({
  mockPush: vi.fn(),
  mockPrefetch: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, prefetch: mockPrefetch }),
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(" "),
}));

vi.mock("@/components/ui/card", () => ({
  Card: ({ children, className }: any) => <div className={className}>{children}</div>,
  CardContent: ({ children, className }: any) => <div className={className}>{children}</div>,
}));

vi.mock("@/components/ui/tooltip", () => ({
  Tooltip: ({ children }: any) => <>{children}</>,
  TooltipContent: ({ children }: any) => <div>{children}</div>,
  TooltipTrigger: ({ children }: any) => <>{children}</>,
  TooltipProvider: ({ children }: any) => <>{children}</>,
}));

const mockUseDashboardDate = vi.fn();
vi.mock("@/contexts/DashboardDateContext", () => ({
  useDashboardDate: () => mockUseDashboardDate(),
  DATE_PRESET_LABELS: { "7d": "7 ngày", "30d": "30 ngày", this_month: "Tháng này", custom: "Tùy chọn" },
}));

const mockCanShowTarget = vi.fn();
vi.mock("@/lib/hooks/use-kpi-catalog", () => ({
  useKpiCatalog: () => ({ canShowTarget: mockCanShowTarget }),
}));

vi.mock("lucide-react", () => ({
  Phone: () => <span />,
  Users: () => <span />,
  TrendingUp: () => <span />,
  TrendingDown: () => <span />,
  Minus: () => <span />,
  Clock: () => <span />,
  GraduationCap: () => <span />,
  ShieldCheck: () => <span />,
  Target: () => <span />,
  Info: () => <span />,
}));

import { KPICardsGrid } from "./KPICardsGrid";

function makeKpis(overrides: Record<string, any> = {}) {
  return {
    consultations_today: 5,
    consultations_target: 10,
    consultations_trend: { value: 0, direction: "neutral" as const, comparison: "" },
    active_leads: 12,
    active_leads_trend: { value: 0, direction: "neutral" as const, comparison: "" },
    win_rate: 40,
    win_rate_trend: { value: 0, direction: "neutral" as const, comparison: "" },
    new_lead_conversion_rate: 20,
    new_lead_conversion_rate_trend: { value: 0, direction: "neutral" as const, comparison: "" },
    avg_response_time: 2,
    avg_response_time_trend: { value: 0, direction: "neutral" as const, comparison: "" },
    sla_compliance_rate: 85,
    sla_compliance_rate_trend: { value: 0, direction: "neutral" as const, comparison: "" },
    consultation_effectiveness: 55,
    consultation_effectiveness_trend: { value: 0, direction: "neutral" as const, comparison: "" },
    consultations_avg_per_day: 7,
    win_rate_target: 33,
    sla_compliance_rate_target: 80,
    new_lead_conversion_rate_target: null,
    consultation_effectiveness_target: null,
    enrollments_monthly: 3,
    enrollments_monthly_target: null,
    ...overrides,
  };
}

function setDashboardDate({
  preset = "this_month",
  startDate = "2026-03-01",
  endDate = "2026-03-31",
  from = new Date(2026, 2, 1),
  to = new Date(2026, 2, 31),
} = {}) {
  mockUseDashboardDate.mockReturnValue({
    preset,
    startDate,
    endDate,
    dateRange: { from, to },
  });
}

describe("KPICardsGrid", () => {
  function setupCanShowTarget(allowed: Record<string, boolean>) {
    mockCanShowTarget.mockImplementation((code: string) => allowed[code] ?? false);
  }

  beforeEach(() => {
    mockPush.mockReset();
    mockPrefetch.mockReset();
    mockCanShowTarget.mockReset();
    setDashboardDate();
  });

  describe("target rendering", () => {
    it("shows win_rate target when canShowTarget('win_rate') returns true", () => {
      setupCanShowTarget({ win_rate: true, sla_compliance_rate: true });

      render(<KPICardsGrid kpis={makeKpis()} />);
      expect(screen.getByText(/Mục tiêu: 33,0%/)).toBeInTheDocument();
    });

    it("hides win_rate target when canShowTarget('win_rate') returns false", () => {
      setDashboardDate({
        preset: "7d",
        startDate: "2026-03-07",
        endDate: "2026-03-13",
        from: new Date(2026, 2, 7),
        to: new Date(2026, 2, 13),
      });
      setupCanShowTarget({ win_rate: false, sla_compliance_rate: true });

      render(<KPICardsGrid kpis={makeKpis()} />);
      const targets = screen.getAllByText(/Mục tiêu:/);
      expect(targets).toHaveLength(1);
      expect(targets[0].textContent).toContain("80,0%");
    });

    it("does not show SLA target when value is null", () => {
      setupCanShowTarget({ win_rate: false, sla_compliance_rate: true });

      render(<KPICardsGrid kpis={makeKpis({ sla_compliance_rate_target: null })} />);
      expect(screen.queryByText(/Mục tiêu:/)).not.toBeInTheDocument();
    });

    it("never shows target for non-comparable conversion metric", () => {
      setupCanShowTarget({ win_rate: true, sla_compliance_rate: true });

      render(<KPICardsGrid kpis={makeKpis()} />);
      expect(screen.getAllByText(/Mục tiêu:/)).toHaveLength(2);
    });

    it("passes dashboardRange into canShowTarget", () => {
      const from = new Date(2026, 2, 1);
      const to = new Date(2026, 2, 31);
      setDashboardDate({ from, to });
      setupCanShowTarget({ win_rate: true, sla_compliance_rate: true });

      render(<KPICardsGrid kpis={makeKpis()} />);

      expect(mockCanShowTarget).toHaveBeenCalledWith("win_rate", { start: from, end: to });
      expect(mockCanShowTarget).toHaveBeenCalledWith("sla_compliance_rate", { start: from, end: to });
    });
  });

  describe("exact drilldown navigation", () => {
    it("navigates active leads with canonical snapshot filters", async () => {
      setupCanShowTarget({});
      const user = userEvent.setup();

      render(
        <KPICardsGrid
          kpis={makeKpis()}
          scope="unit"
          unitId={7}
          includeDescendants={true}
        />,
      );

      await user.click(screen.getByRole("button", { name: /Leads đang xử lý: 12/i }));

      const url = new URL(mockPush.mock.calls.at(-1)?.[0] ?? "", "http://test");
      expect(url.pathname).toBe("/leads");
      expect(url.searchParams.get("status")).toBe("new,assigned,contacted,qualified");
      expect(url.searchParams.get("scope")).toBe("unit");
      expect(url.searchParams.get("scope_unit_id")).toBe("7");
      expect(url.searchParams.get("include_descendants")).toBe("1");
    });

    it("navigates win rate to exact transitions drilldown", async () => {
      setupCanShowTarget({ win_rate: true });
      const user = userEvent.setup();

      render(<KPICardsGrid kpis={makeKpis()} scope="personal" officerId={42} />);

      await user.click(screen.getByRole("button", { name: /Tỉ lệ chốt đơn: 40,0%/i }));

      const url = new URL(mockPush.mock.calls.at(-1)?.[0] ?? "", "http://test");
      expect(url.pathname).toBe("/dashboard/drilldown/transitions");
      expect(url.searchParams.get("metric_key")).toBe("win_rate");
      expect(url.searchParams.get("final_only")).toBe("1");
      expect(url.searchParams.get("scope")).toBe("personal");
      expect(url.searchParams.get("scope_officer_id")).toBe("42");
      expect(url.searchParams.get("from")).toBe("2026-03-01");
      expect(url.searchParams.get("to")).toBe("2026-03-31");
    });

    it("navigates cohort conversion to cohorts drilldown", async () => {
      setupCanShowTarget({});
      const user = userEvent.setup();

      render(<KPICardsGrid kpis={makeKpis()} />);

      await user.click(screen.getByRole("button", { name: /Chuyển đổi lead mới: 20,0%/i }));

      const url = new URL(mockPush.mock.calls.at(-1)?.[0] ?? "", "http://test");
      expect(url.pathname).toBe("/dashboard/drilldown/cohorts");
      expect(url.searchParams.get("metric_key")).toBe("new_lead_conversion");
    });

    it("navigates consultation effectiveness and enrollments to exact transitions evidence", async () => {
      setupCanShowTarget({ enrollments_monthly: true });
      const user = userEvent.setup();

      render(<KPICardsGrid kpis={makeKpis()} />);

      await user.click(screen.getByRole("button", { name: /Hiệu quả tư vấn: 55,0%/i }));
      let url = new URL(mockPush.mock.calls.at(-1)?.[0] ?? "", "http://test");
      expect(url.pathname).toBe("/dashboard/drilldown/transitions");
      expect(url.searchParams.get("metric_key")).toBe("consultation_effectiveness");
      expect(url.searchParams.get("consulted_only")).toBe("1");
      expect(url.searchParams.get("final_only")).toBe("1");

      await user.click(screen.getByRole("button", { name: /Nhập học: 3/i }));
      url = new URL(mockPush.mock.calls.at(-1)?.[0] ?? "", "http://test");
      expect(url.pathname).toBe("/dashboard/drilldown/transitions");
      expect(url.searchParams.get("metric_key")).toBe("enrollments_monthly");
      expect(url.searchParams.get("outcome")).toBe("positive");
      expect(url.searchParams.get("final_only")).toBe("1");
    });
  });
});
