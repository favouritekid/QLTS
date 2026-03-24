// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/contexts/DashboardDateContext", () => ({
  useDashboardDate: () => ({
    startDate: "2026-03-17",
    endDate: "2026-03-23",
  }),
}));

vi.mock("@/hooks/usePipeline", () => ({
  useLossReasons: () => ({ data: undefined }),
}));

vi.mock("@/components/ui/card", () => ({
  Card: ({ children, className }: any) => <div className={className}>{children}</div>,
  CardContent: ({ children, className }: any) => <div className={className}>{children}</div>,
  CardHeader: ({ children, className }: any) => <div className={className}>{children}</div>,
  CardTitle: ({ children, className }: any) => <div className={className}>{children}</div>,
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children }: any) => <span>{children}</span>,
}));

vi.mock("@/components/ui/table", () => ({
  Table: ({ children }: any) => <table>{children}</table>,
  TableBody: ({ children }: any) => <tbody>{children}</tbody>,
  TableCell: ({ children, className, colSpan }: any) => (
    <td className={className} colSpan={colSpan}>
      {children}
    </td>
  ),
  TableHead: ({ children, className }: any) => <th className={className}>{children}</th>,
  TableHeader: ({ children }: any) => <thead>{children}</thead>,
  TableRow: ({ children, className, onClick }: any) => (
    <tr className={className} onClick={onClick}>
      {children}
    </tr>
  ),
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(" "),
}));

import { FunnelTable } from "./FunnelTable";

describe("FunnelTable totals", () => {
  it("uses all stages for header total, summary total, and row percentages", () => {
    render(
      <FunnelTable
        funnel={[
          {
            stage_id: "stg01",
            stage_name: "Stage A",
            stage_order: 1,
            lead_count: 4,
            is_final_stage: false,
            conversion_rate: 80,
            velocity: null,
            estimated_lost_revenue: null,
            early_exit_count: 1,
            move_forward: 3,
            loss_breakdown: null,
          },
          {
            stage_id: "stg06",
            stage_name: "Stage Won",
            stage_order: 10,
            lead_count: 5,
            is_final_stage: true,
            velocity: null,
            estimated_lost_revenue: null,
            early_exit_count: 0,
            move_forward: 0,
            loss_breakdown: null,
            outcome_breakdown: { positive: 5, negative: 0, neutral: 0 },
          },
        ]}
      />,
    );

    expect(
      screen.getAllByText((_, node) => node?.textContent === "Tổng: 9 leads").length,
    ).toBeGreaterThan(0);

    const stageRow = screen.getByRole("button", { name: "Stage A" }).closest("tr");
    expect(stageRow).toHaveTextContent("4");
    expect(stageRow).toHaveTextContent("44%");

    const summaryRow = screen.getByText(/Tổng cộng/i).closest("tr");
    expect(summaryRow).toHaveTextContent("9");
  });
});
