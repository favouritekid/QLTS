// src/components/officer/dashboard/CurrentMonthSnapshot.test.tsx
// @vitest-environment jsdom
/**
 * Tests for CurrentMonthSnapshot.
 *
 * Validates:
 * - Renders null when no plan / loading
 * - Shows enrollment actual/target with progress
 * - consultations_monthly_total labeled as "CT" (chỉ tiêu), not actual
 * - conversion_rate: shows actual when available, falls back to plan target with "Chỉ tiêu" label
 * - conversion_rate_actual shown as "Conv% thực tế"
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

vi.mock("lucide-react", () => ({
  CalendarDays: () => <span />,
}));

vi.mock("@/components/ui/progress", () => ({
  Progress: () => <div data-testid="progress" />,
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(" "),
}));

import { CurrentMonthSnapshot } from "./CurrentMonthSnapshot";

const now = new Date();
const currentMonth = now.getMonth() + 1;

function makePlan(monthOverrides: Record<string, any> = {}) {
  return {
    fiscal_year: now.getFullYear(),
    annual_target: 80,
    achieved_ytd: 40,
    progress_pct: 50,
    source: "officer" as const,
    months: [{
      month: currentMonth,
      enrollment_target: 12,
      enrollment_actual: 5,
      working_days: 22,
      consultations_daily: 6,
      consultations_actual_avg: 5.5,
      consultations_monthly_total: 132, // plan-derived: 6 * 22
      conversion_rate: 15.0,
      conversion_rate_actual: null,
      win_rate: 33.0,
      win_rate_actual: null,
      ...monthOverrides,
    }],
  };
}

describe("CurrentMonthSnapshot", () => {
  it("renders null when plan is null", () => {
    const { container } = render(<CurrentMonthSnapshot plan={null} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders null when loading", () => {
    const { container } = render(<CurrentMonthSnapshot plan={makePlan()} isLoading={true} />);
    expect(container.innerHTML).toBe("");
  });

  it("shows enrollment actual/target", () => {
    render(<CurrentMonthSnapshot plan={makePlan()} />);
    expect(screen.getByText("5/12")).toBeInTheDocument();
  });

  it("labels consultations_monthly_total as chỉ tiêu (CT), not actual", () => {
    render(<CurrentMonthSnapshot plan={makePlan()} />);
    // Header says "CT TV tháng" — plan target, not actual
    expect(screen.getByText("CT TV tháng")).toBeInTheDocument();
    // "Chỉ tiêu" annotation present
    expect(screen.getAllByText("Chỉ tiêu").length).toBeGreaterThanOrEqual(1);
  });

  it("shows plan conversion_rate with 'Chỉ tiêu' label when no actual", () => {
    render(<CurrentMonthSnapshot plan={makePlan({ conversion_rate_actual: null, conversion_rate: 15.0 })} />);
    // Label says "CT Conv%" (not "Conv% thực tế")
    expect(screen.getByText("CT Conv%")).toBeInTheDocument();
  });

  it("shows actual conversion_rate with 'thực tế' label when available", () => {
    render(<CurrentMonthSnapshot plan={makePlan({ conversion_rate_actual: 22.5, conversion_rate: 15.0 })} />);
    // Label says "Conv% thực tế"
    expect(screen.getByText("Conv% thực tế")).toBeInTheDocument();
    // Value shows actual, not plan
    expect(screen.getByText("22,5%")).toBeInTheDocument();
  });
});
