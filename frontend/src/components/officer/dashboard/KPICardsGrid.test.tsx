// src/components/officer/dashboard/KPICardsGrid.test.tsx
// @vitest-environment jsdom
/**
 * Contract tests for KPICardsGrid target passing.
 *
 * Validates:
 * - win_rate_target passed to Tỉ lệ chốt đơn card only when period is calendar month
 * - sla_compliance_rate_target always passed to Tuân thủ SLA stat
 * - new_lead_conversion_rate_target (null) not rendered
 * - consultation_effectiveness_target (null) not rendered
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn() }),
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

// Mock DashboardDateContext — controls period behavior
const mockUseDashboardDate = vi.fn();
vi.mock("@/contexts/DashboardDateContext", () => ({
  useDashboardDate: () => mockUseDashboardDate(),
  DATE_PRESET_LABELS: { "7d": "7 ngày", "30d": "30 ngày", "this_month": "Tháng này", "custom": "Tùy chọn" },
}));

// Mock useKpiCatalog — catalog-driven canShowTarget
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
  ShieldCheck: () => <span />,
  Target: () => <span />,
  Info: () => <span />,
}));

import { KPICardsGrid } from "./KPICardsGrid";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeKpis(overrides: Record<string, any> = {}) {
  return {
    consultations_today: 5,
    consultations_target: 10,
    consultations_trend: { value: 0, direction: "neutral" as const, comparison: "" },
    active_leads: 12,
    active_leads_trend: { value: 0, direction: "neutral" as const, comparison: "" },
    win_rate: 40,
    new_lead_conversion_rate: 20,
    avg_response_time: 2,
    avg_response_time_trend: { value: 0, direction: "neutral" as const, comparison: "" },
    sla_compliance_rate: 85,
    consultation_effectiveness: 55,
    consultations_avg_per_day: 7,
    win_rate_target: 33,
    sla_compliance_rate_target: 80,
    new_lead_conversion_rate_target: null,
    consultation_effectiveness_target: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("KPICardsGrid target rendering", () => {
  /** Helper: configure canShowTarget per kpi_code */
  function setupCanShowTarget(allowed: Record<string, boolean>) {
    mockCanShowTarget.mockImplementation((code: string) => allowed[code] ?? false);
  }

  describe("win_rate_target (requires monthly period match via catalog)", () => {
    it("shows win_rate target when canShowTarget('win_rate') returns true", () => {
      mockUseDashboardDate.mockReturnValue({
        preset: "this_month",
        dateRange: { from: new Date(2026, 2, 1), to: new Date(2026, 2, 31) },
      });
      setupCanShowTarget({ win_rate: true, sla_compliance_rate: true });

      render(<KPICardsGrid kpis={makeKpis()} />);
      expect(screen.getByText(/Mục tiêu: 33,0%/)).toBeInTheDocument();
    });

    it("hides win_rate target when canShowTarget('win_rate') returns false", () => {
      mockUseDashboardDate.mockReturnValue({
        preset: "7d",
        dateRange: { from: new Date(2026, 2, 7), to: new Date(2026, 2, 13) },
      });
      setupCanShowTarget({ win_rate: false, sla_compliance_rate: true });

      render(<KPICardsGrid kpis={makeKpis()} />);
      // Only SLA target should show, not win_rate
      const targets = screen.getAllByText(/Mục tiêu:/);
      expect(targets).toHaveLength(1);
      expect(targets[0].textContent).toContain("80,0%");
    });
  });

  describe("sla_compliance_rate_target (no period match required)", () => {
    it("shows SLA target when canShowTarget('sla_compliance_rate') returns true", () => {
      mockUseDashboardDate.mockReturnValue({
        preset: "7d",
        dateRange: { from: new Date(2026, 2, 7), to: new Date(2026, 2, 13) },
      });
      setupCanShowTarget({ win_rate: false, sla_compliance_rate: true });

      render(<KPICardsGrid kpis={makeKpis()} />);
      expect(screen.getByText(/Mục tiêu: 80,0%/)).toBeInTheDocument();
    });

    it("does NOT show SLA target when value is null (even if catalog allows)", () => {
      mockUseDashboardDate.mockReturnValue({
        preset: "7d",
        dateRange: { from: new Date(2026, 2, 7), to: new Date(2026, 2, 13) },
      });
      setupCanShowTarget({ win_rate: false, sla_compliance_rate: true });

      render(<KPICardsGrid kpis={makeKpis({ sla_compliance_rate_target: null })} />);
      expect(screen.queryByText(/Mục tiêu:/)).not.toBeInTheDocument();
    });
  });

  describe("non-comparable metrics", () => {
    it("never shows target for new_lead_conversion_rate (comparable=false in catalog)", () => {
      mockUseDashboardDate.mockReturnValue({
        preset: "this_month",
        dateRange: { from: new Date(2026, 2, 1), to: new Date(2026, 2, 31) },
      });
      setupCanShowTarget({ win_rate: true, sla_compliance_rate: true });

      render(<KPICardsGrid kpis={makeKpis()} />);
      // Should show win_rate target (33%) and SLA target (80%), NOT conversion_rate
      const targets = screen.getAllByText(/Mục tiêu:/);
      expect(targets).toHaveLength(2);
    });
  });

  describe("canShowTarget receives dashboardRange", () => {
    it("passes { start, end } derived from dateRange to canShowTarget", () => {
      const from = new Date(2026, 2, 1);
      const to = new Date(2026, 2, 31);
      mockUseDashboardDate.mockReturnValue({ preset: "this_month", dateRange: { from, to } });
      setupCanShowTarget({ win_rate: true, sla_compliance_rate: true });

      render(<KPICardsGrid kpis={makeKpis()} />);

      // Verify canShowTarget was called with correct dashboardRange shape
      expect(mockCanShowTarget).toHaveBeenCalledWith("win_rate", { start: from, end: to });
      expect(mockCanShowTarget).toHaveBeenCalledWith("sla_compliance_rate", { start: from, end: to });
    });
  });
});
