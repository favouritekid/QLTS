// src/components/officer/PerformanceChart.test.tsx
// @vitest-environment jsdom
/**
 * Tests for PerformanceChart benchmark strip.
 *
 * Validates:
 * - Rolling leads baseline shown in summary strip
 * - Enrollment pace shown when prop provided
 * - Enrollment pace hidden when prop is null
 * - On-track vs off-track color coding
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

vi.mock("@/contexts/DashboardDateContext", () => ({
  useDashboardDate: () => ({
    dateRange: { from: new Date(2026, 2, 7), to: new Date(2026, 2, 13) },
  }),
}));

vi.mock("@/components/ui/card", () => ({
  Card: ({ children }: any) => <div>{children}</div>,
  CardContent: ({ children }: any) => <div>{children}</div>,
  CardHeader: ({ children }: any) => <div>{children}</div>,
  CardTitle: ({ children }: any) => <div>{children}</div>,
  CardDescription: ({ children }: any) => <div>{children}</div>,
}));

vi.mock("recharts", () => ({
  LineChart: ({ children }: any) => <div>{children}</div>,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  Legend: () => null,
  ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
  ReferenceLine: () => null,
}));

vi.mock("date-fns", () => ({
  format: (d: Date, fmt: string) => "07/03",
}));

vi.mock("date-fns/locale", () => ({
  vi: {},
}));

import { PerformanceChart } from "./PerformanceChart";

const TRENDS = [
  { date: "2026-03-07", leads_assigned: 8, consultations: 6, converted: 2, enrolled: 1, lost: 1 },
  { date: "2026-03-08", leads_assigned: 10, consultations: 7, converted: 3, enrolled: 2, lost: 0 },
  { date: "2026-03-09", leads_assigned: 6, consultations: 5, converted: 1, enrolled: 0, lost: 2 },
];

describe("PerformanceChart benchmark strip", () => {
  it("shows rolling leads baseline in summary strip", () => {
    render(<PerformanceChart trends={TRENDS} />);
    // avg leads = (8+10+6)/3 = 8
    expect(screen.getByText(/Baseline leads: 8\/ngày/)).toBeInTheDocument();
  });

  it("shows enrollment pace when prop is provided", () => {
    render(
      <PerformanceChart
        trends={TRENDS}
        enrollmentPace={{ pace: 0.5, onTrack: true, label: "5/12" }}
      />
    );
    expect(screen.getByTestId("enrollment-pace")).toBeInTheDocument();
    expect(screen.getByText(/Pace nhập học: 0.5\/ngày/)).toBeInTheDocument();
    expect(screen.getByText(/5\/12/)).toBeInTheDocument();
  });

  it("does not show enrollment pace when prop is null", () => {
    render(<PerformanceChart trends={TRENDS} enrollmentPace={null} />);
    expect(screen.queryByTestId("enrollment-pace")).not.toBeInTheDocument();
  });

  it("shows green indicator when on track", () => {
    render(
      <PerformanceChart
        trends={TRENDS}
        enrollmentPace={{ pace: 0.3, onTrack: true, label: "8/12" }}
      />
    );
    const el = screen.getByTestId("enrollment-pace");
    const dot = el.querySelector("div");
    expect(dot?.className).toContain("bg-success-500");
  });

  it("shows warning indicator when off track", () => {
    render(
      <PerformanceChart
        trends={TRENDS}
        enrollmentPace={{ pace: 1.2, onTrack: false, label: "3/12" }}
      />
    );
    const el = screen.getByTestId("enrollment-pace");
    const dot = el.querySelector("div");
    expect(dot?.className).toContain("bg-warning-500");
  });
});
