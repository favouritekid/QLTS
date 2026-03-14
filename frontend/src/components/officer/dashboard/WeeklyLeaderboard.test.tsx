// src/components/officer/dashboard/WeeklyLeaderboard.test.tsx
// @vitest-environment jsdom
/**
 * Contract tests for WeeklyLeaderboard.
 *
 * Validates:
 * - current_user_rank=null renders "N officers" instead of "#null/N"
 * - current_user_rank=number renders "#rank/total"
 * - is_current_user renders "Bạn" badge (logged-in user)
 * - is_focus_officer renders "Đang xem" badge (drill-down target)
 * - Manager drill-down: focus officer does NOT get "Bạn" badge
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

// Mock dependencies before importing component
vi.mock("@/components/ui/card", () => ({
  Card: ({ children, className }: any) => <div className={className}>{children}</div>,
  CardContent: ({ children }: any) => <div>{children}</div>,
  CardHeader: ({ children }: any) => <div>{children}</div>,
  CardTitle: ({ children, className }: any) => <div className={className}>{children}</div>,
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children, className, variant }: any) => (
    <span className={className} data-variant={variant}>{children}</span>
  ),
}));

vi.mock("@/components/ui/skeleton", () => ({
  Skeleton: ({ className }: any) => <div className={className} />,
}));

vi.mock("lucide-react", () => ({
  Crown: () => <span data-testid="icon-crown" />,
  Medal: () => <span data-testid="icon-medal" />,
  TrendingUp: () => <span data-testid="icon-up" />,
  TrendingDown: () => <span data-testid="icon-down" />,
  Minus: () => <span data-testid="icon-minus" />,
  Trophy: () => <span data-testid="icon-trophy" />,
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(" "),
}));

vi.mock("@/contexts/DashboardDateContext", () => ({
  useDashboardDate: () => ({
    startDate: "2026-03-09",
    endDate: "2026-03-12",
  }),
}));

// Mock the hook with controllable return values
const mockUseWeeklyLeaderboard = vi.fn();
vi.mock("@/hooks/officer/useWeeklyLeaderboard", () => ({
  useWeeklyLeaderboard: (...args: any[]) => mockUseWeeklyLeaderboard(...args),
}));

// Import component AFTER mocks
import { WeeklyLeaderboard } from "./WeeklyLeaderboard";

describe("WeeklyLeaderboard", () => {
  it("renders rank badge as '#rank/total' when current_user_rank is set", () => {
    mockUseWeeklyLeaderboard.mockReturnValue({
      data: {
        week_start: "2026-03-09",
        week_end: "2026-03-12",
        total_officers: 5,
        current_user_rank: 3,
        leaderboard: [
          { rank: 1, user_id: 10, username: "a", full_name: "A", consultations: 50, is_current_user: false },
        ],
      },
      isLoading: false,
      error: null,
    });

    render(<WeeklyLeaderboard />);
    expect(screen.getByText("#3/5")).toBeInTheDocument();
  });

  it("renders 'N officers' badge when current_user_rank is null (manager/admin not in population)", () => {
    mockUseWeeklyLeaderboard.mockReturnValue({
      data: {
        week_start: "2026-03-09",
        week_end: "2026-03-12",
        total_officers: 5,
        current_user_rank: null,
        leaderboard: [
          { rank: 1, user_id: 10, username: "a", full_name: "A", consultations: 50, is_current_user: false },
        ],
      },
      isLoading: false,
      error: null,
    });

    render(<WeeklyLeaderboard />);
    expect(screen.getByText("5 officers")).toBeInTheDocument();
    expect(screen.queryByText(/#null/)).not.toBeInTheDocument();
  });

  // =========================================================================
  // is_current_user vs is_focus_officer semantics
  // =========================================================================

  it("renders 'Bạn' badge for is_current_user=true (officer viewing own leaderboard)", () => {
    mockUseWeeklyLeaderboard.mockReturnValue({
      data: {
        week_start: "2026-03-09",
        total_officers: 5,
        current_user_rank: 3,
        leaderboard: [
          { rank: 1, user_id: 10, username: "a", full_name: "Top Officer", consultations: 50, is_current_user: false },
          { rank: 3, user_id: 42, username: "me", full_name: "My Name", consultations: 30, is_current_user: true, is_focus_officer: true },
        ],
      },
      isLoading: false,
      error: null,
    });

    render(<WeeklyLeaderboard />);
    expect(screen.getByText("Bạn")).toBeInTheDocument();
    // Should NOT show "Đang xem" when both flags are true (is_current_user takes precedence)
    expect(screen.queryByText("Đang xem")).not.toBeInTheDocument();
  });

  it("renders 'Đang xem' (NOT 'Bạn') for drill-down target when manager views another officer", () => {
    mockUseWeeklyLeaderboard.mockReturnValue({
      data: {
        week_start: "2026-03-09",
        total_officers: 5,
        current_user_rank: null, // Manager not in population
        leaderboard: [
          { rank: 1, user_id: 10, username: "a", full_name: "Top Officer", consultations: 50, is_current_user: false, is_focus_officer: false },
          { rank: 2, user_id: 99, username: "target", full_name: "Drilled Officer", consultations: 40, is_current_user: false, is_focus_officer: true },
        ],
      },
      isLoading: false,
      error: null,
    });

    render(<WeeklyLeaderboard />);
    // Must NOT show "Bạn" for the drilled officer
    expect(screen.queryByText("Bạn")).not.toBeInTheDocument();
    // Must show "Đang xem" for the focus officer
    expect(screen.getByText("Đang xem")).toBeInTheDocument();
  });

  it("does NOT show any badge for non-current non-focus officers", () => {
    mockUseWeeklyLeaderboard.mockReturnValue({
      data: {
        week_start: "2026-03-09",
        total_officers: 3,
        current_user_rank: null,
        leaderboard: [
          { rank: 1, user_id: 10, username: "a", full_name: "Officer A", consultations: 50, is_current_user: false, is_focus_officer: false },
          { rank: 2, user_id: 20, username: "b", full_name: "Officer B", consultations: 40, is_current_user: false, is_focus_officer: false },
        ],
      },
      isLoading: false,
      error: null,
    });

    render(<WeeklyLeaderboard />);
    expect(screen.queryByText("Bạn")).not.toBeInTheDocument();
    expect(screen.queryByText("Đang xem")).not.toBeInTheDocument();
  });
});
