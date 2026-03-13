// src/components/officer/dashboard/KpiSummaryBanner.test.tsx
// @vitest-environment jsdom
/**
 * Tests for KpiSummaryBanner — actionable KPI summary near dashboard top.
 *
 * Validates:
 * - Annual progress status mapping (completed, at_risk, overdue shown; in_progress skipped)
 * - Monthly enrollment from plan (current month only)
 * - Today's consultation — only shown when met (not-met is already on KPI card)
 * - Comparable KPIs below target (win_rate, sla_compliance_rate)
 * - Non-comparable metrics never mentioned
 * - Attention items prioritized over good items
 * - Max 4 items cap
 * - Empty state: returns null when no items
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/lib/utils", () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(" "),
}));

vi.mock("lucide-react", () => ({
  CheckCircle2: () => <span data-testid="icon-good" />,
  AlertTriangle: () => <span data-testid="icon-attention" />,
  Info: () => <span data-testid="icon-neutral" />,
}));

// Mock DashboardDateContext
const mockUseDashboardDate = vi.fn();
vi.mock("@/contexts/DashboardDateContext", () => ({
  useDashboardDate: () => mockUseDashboardDate(),
}));

// Mock useKpiCatalog
const mockCanShowTarget = vi.fn();
vi.mock("@/lib/hooks/use-kpi-catalog", () => ({
  useKpiCatalog: () => ({ canShowTarget: mockCanShowTarget }),
}));

import { KpiSummaryBanner } from "./KpiSummaryBanner";
import type { KPIStats, AnnualProgressInfo } from "@/hooks/useDashboardStats";
import type { OfficerKpiPlanResponse } from "@/lib/api/officer";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeKpis(overrides: Record<string, any> = {}): KPIStats {
  return {
    consultations_today: 5,
    consultations_target: 10,
    consultations_trend: { value: 0, direction: "neutral", comparison: "" },
    active_leads: 12,
    active_leads_trend: { value: 0, direction: "neutral", comparison: "" },
    win_rate: 40,
    new_lead_conversion_rate: 20,
    avg_response_time: 2,
    avg_response_time_trend: { value: 0, direction: "neutral", comparison: "" },
    sla_compliance_rate: 85,
    consultation_effectiveness: 55,
    win_rate_target: 33,
    sla_compliance_rate_target: 80,
    new_lead_conversion_rate_target: null,
    consultation_effectiveness_target: null,
    ...overrides,
  };
}

function makeAnnual(overrides: Record<string, any> = {}): AnnualProgressInfo {
  return {
    kpi_code: "enrollments_annual",
    fiscal_year: 2026,
    annual_target: 80,
    achieved_ytd: 45,
    remaining: 35,
    progress_pct: 56.3,
    months_left: 10,
    monthly_target: 3.5,
    status: "in_progress",
    on_track: true,
    ...overrides,
  };
}

function makePlan(currentMonthActual: number | null = 5): OfficerKpiPlanResponse {
  const currentMonth = new Date().getMonth() + 1;
  return {
    fiscal_year: 2026,
    annual_target: 80,
    achieved_ytd: 45,
    progress_pct: 56.3,
    source: "officer",
    months: Array.from({ length: 12 }, (_, i) => ({
      month: i + 1,
      enrollment_target: 7,
      enrollment_actual: i + 1 === currentMonth ? currentMonthActual : null,
      working_days: 22,
      consultations_daily: 10,
      consultations_actual_avg: null,
      consultations_monthly_total: null,
      conversion_rate: null,
      win_rate: null,
    })),
  } as OfficerKpiPlanResponse;
}

/** Set up date mocks so today IS within the dashboard range */
function setTodayInRange() {
  const today = new Date();
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 6);
  mockUseDashboardDate.mockReturnValue({
    dateRange: { from: weekAgo, to: today },
    preset: "7d",
  });
}

/** Set up date mocks so today is NOT within the dashboard range */
function setTodayOutOfRange() {
  const pastEnd = new Date();
  pastEnd.setDate(pastEnd.getDate() - 10);
  const pastStart = new Date(pastEnd);
  pastStart.setDate(pastStart.getDate() - 6);
  mockUseDashboardDate.mockReturnValue({
    dateRange: { from: pastStart, to: pastEnd },
    preset: "custom",
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("KpiSummaryBanner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setTodayInRange();
    mockCanShowTarget.mockReturnValue(true);
  });

  it("renders null when no data produces summary items", () => {
    mockUseDashboardDate.mockReturnValue({ dateRange: null, preset: "7d" });
    const { container } = render(
      <KpiSummaryBanner kpis={makeKpis({ consultations_target: 0 })} />
    );
    expect(container.firstChild).toBeNull();
  });

  // === Annual progress ===

  it("skips annual progress in_progress (already visible on card)", () => {
    // in_progress is on-track → not notable, should not appear
    const { container } = render(
      <KpiSummaryBanner
        kpis={makeKpis({ consultations_target: 0 })}
        annualProgress={makeAnnual()}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows annual progress completed as good", () => {
    render(
      <KpiSummaryBanner
        kpis={makeKpis({ consultations_target: 0 })}
        annualProgress={makeAnnual({ status: "completed", achieved_ytd: 80, remaining: 0 })}
      />
    );
    expect(screen.getByText(/Nhập học năm: hoàn thành/)).toBeTruthy();
  });

  it("shows annual progress at_risk as attention", () => {
    render(
      <KpiSummaryBanner
        kpis={makeKpis()}
        annualProgress={makeAnnual({ status: "at_risk", on_track: false })}
      />
    );
    expect(screen.getByText(/cần tăng tốc/)).toBeTruthy();
  });

  it("shows annual progress overdue as attention", () => {
    render(
      <KpiSummaryBanner
        kpis={makeKpis()}
        annualProgress={makeAnnual({ status: "overdue", remaining: 10 })}
      />
    );
    expect(screen.getByText(/chưa đạt, còn thiếu 10/)).toBeTruthy();
  });

  // === Monthly enrollment from plan ===

  it("shows current month enrollment as attention when behind", () => {
    const currentMonth = new Date().getMonth() + 1;
    render(
      <KpiSummaryBanner kpis={makeKpis({ consultations_target: 0 })} plan={makePlan(5)} />
    );
    expect(screen.getByText(new RegExp(`Nhập học T${currentMonth}: 5/7`))).toBeTruthy();
  });

  it("shows met status when enrollment actual >= target", () => {
    render(
      <KpiSummaryBanner kpis={makeKpis({ consultations_target: 0 })} plan={makePlan(7)} />
    );
    expect(screen.getByText(/— đạt/)).toBeTruthy();
  });

  it("does not show monthly enrollment when actual is null", () => {
    render(
      <KpiSummaryBanner kpis={makeKpis()} plan={makePlan(null)} />
    );
    const currentMonth = new Date().getMonth() + 1;
    expect(screen.queryByText(new RegExp(`Nhập học T${currentMonth}`))).toBeNull();
  });

  // === Today's consultations ===

  it("does not show today consultations when not yet met (already on KPI card)", () => {
    // 5/10 not met → skipped
    const { container } = render(
      <KpiSummaryBanner kpis={makeKpis({ consultations_target: 10 })} />
    );
    expect(screen.queryByText(/Tư vấn hôm nay: 5\/10/)).toBeNull();
  });

  it("does not show today consultations when today is out of range", () => {
    setTodayOutOfRange();
    render(<KpiSummaryBanner kpis={makeKpis({ consultations_today: 10 })} />);
    expect(screen.queryByText(/Tư vấn hôm nay/)).toBeNull();
  });

  it("shows met text when consultations meet target", () => {
    render(<KpiSummaryBanner kpis={makeKpis({ consultations_today: 10 })} />);
    expect(screen.getByText(/đạt mục tiêu/)).toBeTruthy();
  });

  // === Comparable KPIs below target ===

  it("shows attention when win_rate is below target", () => {
    render(<KpiSummaryBanner kpis={makeKpis({ win_rate: 25, win_rate_target: 33 })} />);
    expect(screen.getByText(/Tỷ lệ chốt đơn.*dưới mục tiêu/)).toBeTruthy();
  });

  it("does not show win_rate when it meets target", () => {
    render(<KpiSummaryBanner kpis={makeKpis({ win_rate: 40, win_rate_target: 33 })} />);
    expect(screen.queryByText(/Tỷ lệ chốt đơn.*dưới mục tiêu/)).toBeNull();
  });

  it("does not show win_rate when canShowTarget returns false", () => {
    mockCanShowTarget.mockImplementation((code: string) => code !== "win_rate");
    render(<KpiSummaryBanner kpis={makeKpis({ win_rate: 10, win_rate_target: 33 })} />);
    expect(screen.queryByText(/Tỷ lệ chốt đơn/)).toBeNull();
  });

  it("shows attention when SLA is below target", () => {
    render(
      <KpiSummaryBanner kpis={makeKpis({ sla_compliance_rate: 70, sla_compliance_rate_target: 80 })} />
    );
    expect(screen.getByText(/SLA tuân thủ.*dưới mục tiêu/)).toBeTruthy();
  });

  // === Non-comparable metrics never mentioned ===

  it("never shows conversion_rate or consultation_effectiveness", () => {
    render(
      <KpiSummaryBanner
        kpis={makeKpis({
          new_lead_conversion_rate: 5,
          consultation_effectiveness: 10,
        })}
      />
    );
    expect(screen.queryByText(/chuyển đổi/i)).toBeNull();
    expect(screen.queryByText(/hiệu quả tư vấn/i)).toBeNull();
  });

  // === Prioritization & cap ===

  it("prioritizes attention items over good items", () => {
    // Setup: annual at_risk (attention), enrollment met (good), consultations met (good), win_rate below (attention)
    render(
      <KpiSummaryBanner
        kpis={makeKpis({ consultations_today: 10, win_rate: 20, win_rate_target: 33 })}
        annualProgress={makeAnnual({ status: "at_risk", on_track: false })}
        plan={makePlan(7)}
      />
    );
    const items = screen.getByTestId("kpi-summary-banner").querySelectorAll("li");
    // Attention items should come first
    expect(items[0].textContent).toMatch(/cần tăng tốc/);
    expect(items[1].textContent).toMatch(/Tỷ lệ chốt đơn.*dưới mục tiêu/);
  });

  it("caps at 4 items max even when more are available", () => {
    // Setup: annual overdue (attention), enrollment behind (attention),
    // win_rate below (attention), SLA below (attention),
    // consultations met (good) → 4 attention + 1 good = should cap at 4
    render(
      <KpiSummaryBanner
        kpis={makeKpis({
          consultations_today: 10,
          win_rate: 20,
          win_rate_target: 33,
          sla_compliance_rate: 70,
          sla_compliance_rate_target: 80,
        })}
        annualProgress={makeAnnual({ status: "overdue", remaining: 10 })}
        plan={makePlan(3)}
      />
    );
    const items = screen.getByTestId("kpi-summary-banner").querySelectorAll("li");
    expect(items.length).toBeLessThanOrEqual(4);
  });

  it("fills remaining slots with good items after attention", () => {
    // 1 attention (win_rate below), 2 good (enrollment met, consultations met)
    // Should show all 3 (under cap)
    render(
      <KpiSummaryBanner
        kpis={makeKpis({ consultations_today: 10, win_rate: 20, win_rate_target: 33 })}
        plan={makePlan(7)}
      />
    );
    const items = screen.getByTestId("kpi-summary-banner").querySelectorAll("li");
    expect(items.length).toBe(3);
    // Attention first
    expect(items[0].textContent).toMatch(/Tỷ lệ chốt đơn.*dưới mục tiêu/);
  });

  // === data-testid ===

  it("renders with data-testid for e2e targeting", () => {
    // Need at least one item to render — use win_rate below target
    render(<KpiSummaryBanner kpis={makeKpis({ win_rate: 20, win_rate_target: 33 })} />);
    expect(screen.getByTestId("kpi-summary-banner")).toBeTruthy();
  });
});
