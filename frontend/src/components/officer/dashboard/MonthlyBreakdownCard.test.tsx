// src/components/officer/dashboard/MonthlyBreakdownCard.test.tsx
// @vitest-environment jsdom
/**
 * Gap 2: Contract tests for MonthlyBreakdownCard.
 *
 * Validates:
 * - Returns null when plan is undefined (404)
 * - Returns null when loading
 * - Collapsed by default (no table visible)
 * - Expands to show 12 rows
 * - Current month highlighted
 * - Footer totals correct
 * - Source label shows "Cá nhân" vs "Đơn vị"
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

vi.mock("@/components/ui/card", () => ({
  Card: ({ children, className }: any) => <div className={className}>{children}</div>,
  CardContent: ({ children, className }: any) => <div className={className}>{children}</div>,
  CardHeader: ({ children, className }: any) => <div className={className}>{children}</div>,
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(" "),
}));

vi.mock("lucide-react", () => ({
  ChevronDown: () => <span data-testid="chevron-down" />,
  ChevronUp: () => <span data-testid="chevron-up" />,
  CalendarDays: () => <span />,
}));

import { MonthlyBreakdownCard } from "./MonthlyBreakdownCard";
import type { OfficerKpiPlanResponse } from "@/lib/api/officer";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePlan(overrides: Partial<OfficerKpiPlanResponse> = {}): OfficerKpiPlanResponse {
  const months = Array.from({ length: 12 }, (_, i) => ({
    month: i + 1,
    enrollment_target: 7,
    enrollment_actual: i < 2 ? 8 : null, // Jan & Feb have actuals
    working_days: 22,
    consultations_daily: 10,
    consultations_monthly_total: 220,
    conversion_rate: 15.0,
    win_rate: 33.0,
  }));

  return {
    fiscal_year: 2026,
    annual_target: 84,
    achieved_ytd: 16,
    progress_pct: 19.0,
    months,
    source: "officer",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MonthlyBreakdownCard", () => {
  it("returns null when plan is undefined (no plan / 404)", () => {
    const { container } = render(<MonthlyBreakdownCard plan={undefined} />);
    expect(container.innerHTML).toBe("");
  });

  it("returns null when plan is null (404 from hook)", () => {
    const { container } = render(<MonthlyBreakdownCard plan={null} />);
    expect(container.innerHTML).toBe("");
  });

  it("returns null when loading", () => {
    const { container } = render(<MonthlyBreakdownCard plan={makePlan()} isLoading={true} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders collapsed by default (no table visible)", () => {
    render(<MonthlyBreakdownCard plan={makePlan()} />);
    expect(screen.getByText("Kế hoạch theo tháng")).toBeInTheDocument();
    expect(screen.queryByTestId("monthly-breakdown-table")).not.toBeInTheDocument();
  });

  it("expands on click to show 12 month rows", async () => {
    const user = userEvent.setup();
    render(<MonthlyBreakdownCard plan={makePlan()} />);

    await user.click(screen.getByRole("button", { name: /Kế hoạch theo tháng/i }));
    const table = screen.getByTestId("monthly-breakdown-table");
    // 12 data rows in tbody
    const rows = within(table).getAllByRole("row");
    // thead(1) + tbody(12) + tfoot(1) = 14
    expect(rows).toHaveLength(14);
  });

  it("shows source label 'Cá nhân' for officer plan", () => {
    render(<MonthlyBreakdownCard plan={makePlan({ source: "officer" })} />);
    expect(screen.getByText(/Cá nhân/)).toBeInTheDocument();
  });

  it("shows source label 'Đơn vị' for unit plan fallback", () => {
    render(<MonthlyBreakdownCard plan={makePlan({ source: "unit" })} />);
    expect(screen.getByText(/Đơn vị/)).toBeInTheDocument();
  });

  it("highlights current month row", async () => {
    const user = userEvent.setup();
    const now = new Date();
    const plan = makePlan({ fiscal_year: now.getFullYear() });
    render(<MonthlyBreakdownCard plan={plan} />);

    await user.click(screen.getByRole("button", { name: /Kế hoạch theo tháng/i }));
    expect(screen.getByText("Hiện tại")).toBeInTheDocument();
  });

  it("shows footer totals row", async () => {
    const user = userEvent.setup();
    render(<MonthlyBreakdownCard plan={makePlan()} />);

    await user.click(screen.getByRole("button", { name: /Kế hoạch theo tháng/i }));
    expect(screen.getByText("Tổng cộng")).toBeInTheDocument();
  });

  it("displays progress summary in header using canonical plan values", () => {
    render(<MonthlyBreakdownCard plan={makePlan({ achieved_ytd: 16, annual_target: 84, progress_pct: 19.0 })} />);
    // Header shows "16/84 (19,0%)" from plan.achieved_ytd/plan.annual_target
    expect(screen.getByText(/16\/84/)).toBeInTheDocument();
  });

  it("footer target equals sum of row targets, not annual_target", async () => {
    const user = userEvent.setup();
    // Months with mixed targets: 6 months × 5 + 6 months × 10 = 90
    // But annual_target is 100 (intentional mismatch)
    const months = Array.from({ length: 12 }, (_, i) => ({
      month: i + 1,
      enrollment_target: i < 6 ? 5 : 10,
      enrollment_actual: null,
      working_days: 22,
      consultations_daily: 10,
      consultations_monthly_total: 220,
      conversion_rate: 15.0,
      win_rate: 33.0,
    }));
    render(
      <MonthlyBreakdownCard
        plan={makePlan({ annual_target: 100, months })}
      />
    );

    await user.click(screen.getByRole("button", { name: /Kế hoạch theo tháng/i }));
    const table = screen.getByTestId("monthly-breakdown-table");
    const footer = within(table).getAllByRole("row").at(-1)!;
    const cells = within(footer).getAllByRole("cell");
    // Footer target cell (index 1) should show sum=90, NOT annual_target=100
    expect(cells[1].textContent).toBe("90");
  });

  it("footer actual equals sum of row actuals", async () => {
    const user = userEvent.setup();
    // Jan=3, Feb=5, rest=null → total=8
    const months = Array.from({ length: 12 }, (_, i) => ({
      month: i + 1,
      enrollment_target: 7,
      enrollment_actual: i === 0 ? 3 : i === 1 ? 5 : null,
      working_days: 22,
      consultations_daily: 10,
      consultations_monthly_total: 220,
      conversion_rate: 15.0,
      win_rate: 33.0,
    }));
    render(
      <MonthlyBreakdownCard
        plan={makePlan({ achieved_ytd: 99, months })}
      />
    );

    await user.click(screen.getByRole("button", { name: /Kế hoạch theo tháng/i }));
    const table = screen.getByTestId("monthly-breakdown-table");
    const footer = within(table).getAllByRole("row").at(-1)!;
    const cells = within(footer).getAllByRole("cell");
    // Footer actual cell (index 2) should show sum=8, NOT achieved_ytd=99
    expect(cells[2].textContent).toBe("8");
  });
});
