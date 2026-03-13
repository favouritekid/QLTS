// src/components/officer/dashboard/KPICard.test.tsx
// @vitest-environment jsdom
/**
 * Contract tests for KPICard target rendering.
 *
 * Validates:
 * - Target line renders when target prop is provided
 * - Target line hidden when target is null/undefined
 * - Success color when actual >= target (higherIsBetter=true)
 * - Warning color when actual < target (higherIsBetter=true)
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { KPICard, isTargetMet } from "./KPICard";
import { TrendingUp } from "lucide-react";

// Mock UI components
vi.mock("@/components/ui/card", () => ({
  Card: ({ children, className }: any) => <div className={className}>{children}</div>,
  CardContent: ({ children, className }: any) => <div className={className}>{children}</div>,
}));

vi.mock("@/components/ui/tooltip", () => ({
  Tooltip: ({ children }: any) => <>{children}</>,
  TooltipContent: ({ children }: any) => <div>{children}</div>,
  TooltipTrigger: ({ children }: any) => <>{children}</>,
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(" "),
}));

describe("KPICard target rendering", () => {
  const baseProps = {
    title: "Tỉ lệ chốt đơn",
    value: "40,0%",
    icon: TrendingUp,
  };

  it("renders target line when target is provided", () => {
    render(<KPICard {...baseProps} target={33} />);
    expect(screen.getByText(/Mục tiêu: 33,0%/)).toBeInTheDocument();
  });

  it("does NOT render target line when target is null", () => {
    render(<KPICard {...baseProps} target={null} />);
    expect(screen.queryByText(/Mục tiêu/)).not.toBeInTheDocument();
  });

  it("does NOT render target line when target is undefined", () => {
    render(<KPICard {...baseProps} />);
    expect(screen.queryByText(/Mục tiêu/)).not.toBeInTheDocument();
  });

  it("applies success color when actual >= target (higherIsBetter=true)", () => {
    render(<KPICard {...baseProps} target={33} higherIsBetter={true} />);
    const targetEl = screen.getByText(/Mục tiêu: 33,0%/);
    expect(targetEl.className).toContain("text-success");
  });

  it("applies warning color when actual < target (higherIsBetter=true)", () => {
    render(<KPICard {...baseProps} value="20,0%" target={33} higherIsBetter={true} />);
    const targetEl = screen.getByText(/Mục tiêu: 33,0%/);
    expect(targetEl.className).toContain("text-warning");
  });

  it("uses custom targetUnit", () => {
    render(<KPICard {...baseProps} target={2} targetUnit="h" />);
    expect(screen.getByText(/Mục tiêu: 2,0h/)).toBeInTheDocument();
  });

  it("uses actualValue prop instead of parsing value string", () => {
    // value="1,5h" would parseFloat to 1 (wrong), but actualValue=1.5 is exact
    render(<KPICard {...baseProps} value="1,5h" target={2} targetUnit="h" actualValue={1.5} higherIsBetter={false} />);
    const targetEl = screen.getByText(/Mục tiêu: 2,0h/);
    // 1.5 <= 2 with higherIsBetter=false → success
    expect(targetEl.className).toContain("text-success");
  });

  it("applies success color when actual == target (exact boundary)", () => {
    render(<KPICard {...baseProps} target={40} actualValue={40} higherIsBetter={true} />);
    const targetEl = screen.getByText(/Mục tiêu: 40,0%/);
    expect(targetEl.className).toContain("text-success");
  });

  it("applies success color when actual <= target with higherIsBetter=false", () => {
    render(<KPICard {...baseProps} value="1,8h" target={2} targetUnit="h" actualValue={1.8} higherIsBetter={false} />);
    const targetEl = screen.getByText(/Mục tiêu: 2,0h/);
    expect(targetEl.className).toContain("text-success");
  });

  it("applies warning color when actual > target with higherIsBetter=false", () => {
    render(<KPICard {...baseProps} value="3,0h" target={2} targetUnit="h" actualValue={3} higherIsBetter={false} />);
    const targetEl = screen.getByText(/Mục tiêu: 2,0h/);
    expect(targetEl.className).toContain("text-warning");
  });
});

describe("isTargetMet", () => {
  it("returns true when actual >= target and higherIsBetter=true", () => {
    expect(isTargetMet(40, 33, true)).toBe(true);
  });

  it("returns true when actual == target and higherIsBetter=true", () => {
    expect(isTargetMet(33, 33, true)).toBe(true);
  });

  it("returns false when actual < target and higherIsBetter=true", () => {
    expect(isTargetMet(20, 33, true)).toBe(false);
  });

  it("returns true when actual <= target and higherIsBetter=false", () => {
    expect(isTargetMet(1.5, 2, false)).toBe(true);
  });

  it("returns true when actual == target and higherIsBetter=false", () => {
    expect(isTargetMet(2, 2, false)).toBe(true);
  });

  it("returns false when actual > target and higherIsBetter=false", () => {
    expect(isTargetMet(3, 2, false)).toBe(false);
  });
});
