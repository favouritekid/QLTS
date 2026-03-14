// src/components/officer/dashboard/AnnualProgressCard.test.tsx
// @vitest-environment jsdom
/**
 * Contract tests for AnnualProgressCard.
 *
 * Validates:
 * - Labels sourced from catalog (not hardcoded)
 * - inherited_estimate renders "(ước tính)" indicator
 * - assigned does NOT render "(ước tính)"
 * - resolution_kind field in AnnualProgressInfo contract
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import {
  AnnualProgressCard,
  type AnnualProgressInfo,
} from "./AnnualProgressCard";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Mock UI components to avoid transitive dependency resolution issues
vi.mock("@/components/ui/card", () => ({
  Card: ({ children, className }: any) => <div data-testid="card" className={className}>{children}</div>,
  CardContent: ({ children }: any) => <div>{children}</div>,
  CardHeader: ({ children }: any) => <div>{children}</div>,
  CardTitle: ({ children, className }: any) => <div className={className}>{children}</div>,
}));

vi.mock("@/components/ui/progress", () => ({
  Progress: ({ value }: any) => <div data-testid="progress" data-value={value} />,
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children, className }: any) => <span className={className}>{children}</span>,
}));

vi.mock("@/components/ui/tooltip", () => ({
  Tooltip: ({ children }: any) => <>{children}</>,
  TooltipContent: ({ children }: any) => <div>{children}</div>,
  TooltipProvider: ({ children }: any) => <>{children}</>,
  TooltipTrigger: ({ children }: any) => <>{children}</>,
}));

vi.mock("lucide-react", () => ({
  Target: () => <span data-testid="icon-target" />,
  TrendingUp: () => <span data-testid="icon-trending-up" />,
  TrendingDown: () => <span data-testid="icon-trending-down" />,
  AlertTriangle: () => <span data-testid="icon-alert" />,
  CheckCircle2: () => <span data-testid="icon-check" />,
  Calendar: () => <span data-testid="icon-calendar" />,
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(" "),
}));

// Mock the catalog hook to avoid real API calls
vi.mock("@/lib/hooks/use-kpi-catalog", () => ({
  useKpiCatalog: () => ({
    getDisplayName: (code: string, context: string) => {
      const map: Record<string, Record<string, string>> = {
        enrollments_annual: {
          annual_progress: "Nhập học năm",
          dashboard: "Nhập học năm",
        },
      };
      return map[code]?.[context] ?? code;
    },
    getUnit: () => "count",
    getComparison: () => ({
      comparable: true,
      requires_period_match: false,
      target_period: "annual",
      caveat: null,
    }),
    getKpiOptions: () => [],
    canShowTarget: () => true,
    catalog: [],
    catalogMap: new Map(),
    data: [],
    isLoading: false,
  }),
}));

function createQueryWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function makeProgress(
  overrides: Partial<AnnualProgressInfo> = {},
): AnnualProgressInfo {
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
    resolution_kind: "assigned",
    ...overrides,
  };
}

describe("AnnualProgressCard", () => {
  it("renders empty state when progress is null", () => {
    render(<AnnualProgressCard progress={null} />, {
      wrapper: createQueryWrapper(),
    });
    expect(screen.getByText("Chưa có chỉ tiêu năm")).toBeInTheDocument();
  });

  it("renders target and YTD for assigned progress", () => {
    render(
      <AnnualProgressCard progress={makeProgress()} />,
      { wrapper: createQueryWrapper() },
    );
    expect(screen.getByText("45")).toBeInTheDocument();
    expect(screen.getByText(/\/\s*80/)).toBeInTheDocument();
  });

  it("does NOT show ước tính for assigned resolution_kind", () => {
    render(
      <AnnualProgressCard
        progress={makeProgress({ resolution_kind: "assigned" })}
      />,
      { wrapper: createQueryWrapper() },
    );
    expect(screen.queryByText("(ước tính)")).not.toBeInTheDocument();
  });

  it("shows ước tính for inherited_estimate resolution_kind", () => {
    render(
      <AnnualProgressCard
        progress={makeProgress({ resolution_kind: "inherited_estimate" })}
      />,
      { wrapper: createQueryWrapper() },
    );
    expect(screen.getByText("(ước tính)")).toBeInTheDocument();
  });

  it("does NOT show ước tính when resolution_kind is null", () => {
    render(
      <AnnualProgressCard
        progress={makeProgress({ resolution_kind: null })}
      />,
      { wrapper: createQueryWrapper() },
    );
    expect(screen.queryByText("(ước tính)")).not.toBeInTheDocument();
  });

  it("renders fiscal year in header", () => {
    render(
      <AnnualProgressCard
        progress={makeProgress({ fiscal_year: 2026 })}
      />,
      { wrapper: createQueryWrapper() },
    );
    expect(screen.getByText(/Chỉ tiêu năm 2026/)).toBeInTheDocument();
  });

  it("AnnualProgressInfo type includes resolution_kind", () => {
    // Type-level contract test: if this compiles, the field exists
    const info: AnnualProgressInfo = makeProgress({
      resolution_kind: "inherited_estimate",
    });
    expect(info.resolution_kind).toBe("inherited_estimate");
  });

  it("AnnualProgressInfo type includes expected_progress_pct", () => {
    // Type-level contract test: if this compiles, the field exists
    const info: AnnualProgressInfo = makeProgress({
      expected_progress_pct: 25.0,
    });
    expect(info.expected_progress_pct).toBe(25.0);
  });

  it("renders expected progress marker with backend value when provided", () => {
    const { container } = render(
      <AnnualProgressCard
        progress={makeProgress({
          expected_progress_pct: 30.0,
          months_left: 10,
          status: "in_progress",
        })}
      />,
      { wrapper: createQueryWrapper() },
    );
    // The marker should use expected_progress_pct=30% (not linear (12-10)/12*100=16.7%)
    const marker = container.querySelector('[title*="Tiến độ kỳ vọng: 30%"]');
    expect(marker).toBeInTheDocument();
  });

  it("falls back to seasonal expected when expected_progress_pct is null", () => {
    const { container } = render(
      <AnnualProgressCard
        progress={makeProgress({
          expected_progress_pct: null,
          months_left: 6,
          status: "in_progress",
        })}
      />,
      { wrapper: createQueryWrapper() },
    );
    // Seasonal: sum of DEFAULT_SEASONAL_WEIGHTS[0..5] = 0.040+0.033+0.050+0.060+0.073+0.127 = 0.383 → 38%
    const marker = container.querySelector('[title*="Tiến độ kỳ vọng: 38%"]');
    expect(marker).toBeInTheDocument();
  });
});
