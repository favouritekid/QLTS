// src/components/officer/FunnelChart.test.tsx
// @vitest-environment jsdom
/**
 * Behavior test for FunnelChart expandable detail surface.
 *
 * Validates:
 * - "Xem chi tiết giai đoạn" button exists when funnel has extended data
 * - Clicking the button shows the detail table
 * - Detail table contains stage names and velocity data
 * - Clicking again hides the table
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

vi.mock("@/contexts/DashboardDateContext", () => ({
  useDashboardDate: () => ({
    startDate: "2026-03-07",
    endDate: "2026-03-13",
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

// Minimal mock for Tooltip components — render children only
vi.mock("@/components/ui/tooltip", () => ({
  TooltipProvider: ({ children }: any) => <>{children}</>,
  Tooltip: ({ children }: any) => <>{children}</>,
  TooltipTrigger: ({ children }: any) => <>{children}</>,
  TooltipContent: () => null,
}));

vi.mock("@/components/ui/card", () => ({
  Card: ({ children, className }: any) => <div className={className}>{children}</div>,
  CardContent: ({ children, className }: any) => <div className={className}>{children}</div>,
  CardHeader: ({ children, className }: any) => <div className={className}>{children}</div>,
  CardTitle: ({ children, className }: any) => <div className={className}>{children}</div>,
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(" "),
}));

vi.mock("@/hooks/usePipeline", () => ({
  useLossReasons: () => ({ data: undefined }),
}));

import { FunnelChart } from "./FunnelChart";

const FUNNEL_WITH_VELOCITY = [
  {
    stage_id: "stg01",
    stage_name: "Tiếp nhận",
    stage_order: 1,
    lead_count: 50,
    is_final_stage: false,
    velocity: { avg_days: 2.5, min_days: 0.5, max_days: 7.0, sample_size: 30 },
    estimated_lost_revenue: null,
    early_exit_count: 3,
    move_forward: 47,
    loss_breakdown: null,
  },
  {
    stage_id: "stg02",
    stage_name: "Tư vấn",
    stage_order: 2,
    lead_count: 35,
    is_final_stage: false,
    velocity: { avg_days: 5.1, min_days: 1.0, max_days: 14.0, sample_size: 20 },
    estimated_lost_revenue: { lost_leads_count: 5, avg_tuition: 15000000, total_lost_revenue: 75000000, leads_with_tuition: 4 },
    early_exit_count: 8,
    move_forward: 27,
    loss_breakdown: [{ reason_code: "PRICE_HIGH", count: 3, percentage: 37.5 }],
  },
  {
    stage_id: "stg06",
    stage_name: "Nhập học",
    stage_order: 10,
    lead_count: 15,
    is_final_stage: true,
    velocity: null,
    estimated_lost_revenue: null,
    early_exit_count: 0,
    move_forward: 0,
    loss_breakdown: null,
    outcome_breakdown: { positive: 15, negative: 0, neutral: 0 },
  },
];

describe("FunnelChart expandable detail", () => {
  it("shows 'Xem chi tiết giai đoạn' button when funnel has velocity data", () => {
    render(<FunnelChart funnel={FUNNEL_WITH_VELOCITY} />);
    expect(screen.getByText("Xem chi tiết giai đoạn")).toBeInTheDocument();
  });

  it("detail table is hidden by default", () => {
    render(<FunnelChart funnel={FUNNEL_WITH_VELOCITY} />);
    // Table headers should NOT be visible
    expect(screen.queryByText("TB ngày")).not.toBeInTheDocument();
  });

  it("clicking the button shows the detail table with stage data", async () => {
    render(<FunnelChart funnel={FUNNEL_WITH_VELOCITY} />);

    await userEvent.click(screen.getByText("Xem chi tiết giai đoạn"));

    // Table headers visible
    expect(screen.getByText("TB ngày")).toBeInTheDocument();
    expect(screen.getByText("DT mất (HK1)")).toBeInTheDocument();

    // Stage names in table
    expect(screen.getAllByText("Tiếp nhận").length).toBeGreaterThanOrEqual(2); // chart + table
    expect(screen.getAllByText("Tư vấn").length).toBeGreaterThanOrEqual(2);

    // Velocity data rendered (inline indicator + detail table = 2 instances each)
    expect(screen.getAllByText("2.5d").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("5.1d").length).toBeGreaterThanOrEqual(2);

    // Button text changes
    expect(screen.getByText("Thu gọn chi tiết")).toBeInTheDocument();
  });

  it("clicking again hides the detail table", async () => {
    render(<FunnelChart funnel={FUNNEL_WITH_VELOCITY} />);

    await userEvent.click(screen.getByText("Xem chi tiết giai đoạn"));
    expect(screen.getByText("TB ngày")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Thu gọn chi tiết"));
    expect(screen.queryByText("TB ngày")).not.toBeInTheDocument();
    expect(screen.getByText("Xem chi tiết giai đoạn")).toBeInTheDocument();
  });

  it("does not show expand button when funnel has no extended data", () => {
    const simpleStages = [
      { stage_id: "stg01", stage_name: "Step 1", stage_order: 1, lead_count: 10, is_final_stage: false },
      { stage_id: "stg02", stage_name: "Step 2", stage_order: 2, lead_count: 5, is_final_stage: true,
        outcome_breakdown: { positive: 5, negative: 0, neutral: 0 } },
    ];
    render(<FunnelChart funnel={simpleStages} />);
    expect(screen.queryByText("Xem chi tiết giai đoạn")).not.toBeInTheDocument();
  });
});
