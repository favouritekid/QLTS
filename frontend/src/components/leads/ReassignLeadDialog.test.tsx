// src/components/leads/ReassignLeadDialog.test.tsx
/**
 * ReassignLeadDialog Component Tests
 *
 * Validates T5 fix: quota UI guard uses correct backend fields.
 * - Backend contract: { allowed, used, limit, remaining }
 * - Component displays remaining/limit as "remaining/limit"
 * - Submit is disabled when remaining <= 0
 * - Error message shown when quota exceeded
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createTestQueryClient } from "@/test/utils/test-utils";
import type { Lead } from "@/types/lead.types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockReassignQuota = vi.fn();
const mockPerformAction = vi.fn();

vi.mock("@/hooks/useLeads", () => ({
  useReassignQuota: (...args: unknown[]) => mockReassignQuota(...args),
  usePerformLeadAction: vi.fn(() => ({
    mutate: mockPerformAction,
    isPending: false,
  })),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    user: { id: 5, role: "officer", full_name: "Test Officer" },
  })),
}));

vi.mock("@/lib/utils/permissions", () => ({
  isManagerOrAbove: vi.fn(() => false), // officer by default
}));

// Mock useIsMobile to return false (desktop = Dialog, not Sheet)
vi.mock("@/hooks/useMediaQuery", () => ({
  useIsMobile: vi.fn(() => false),
}));

import { ReassignLeadDialog } from "./ReassignLeadDialog";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createWrapper() {
  const queryClient = createTestQueryClient();
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "TestQueryClientWrapper";
  return Wrapper;
}

const mockLead: Lead = {
  id: 1,
  full_name: "Test Lead",
  phone: "0901234567",
  email: "test@example.com",
  source: "website",
  status: "assigned",
  lead_score: 50,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
  version: 1,
  unit_id: 1,
  consultation_count: 0,
  cached_urgency_score: 0,
  is_hot_lead: false,
  is_overdue: false,
  days_in_stage: 0,
  location_proximity: 0,
  occupation_relevance: 0,
  academic_performance: 0,
  referrer_id: null,
  validity_status: null,
  created_via: null,
  referrer: null,
} as Lead;

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ReassignLeadDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("should display remaining/limit from backend quota contract", async () => {
    mockReassignQuota.mockReturnValue({
      data: { allowed: true, used: 3, limit: 5, remaining: 2 },
      isLoading: false,
    });

    render(
      <ReassignLeadDialog
        open={true}
        onOpenChange={vi.fn()}
        lead={mockLead}
      />,
      { wrapper: createWrapper() },
    );

    // The dialog should show the quota badge with "2/5"
    await waitFor(() => {
      expect(screen.getByText("2/5")).toBeInTheDocument();
    });
  });

  it("should disable submit when quota.remaining <= 0", async () => {
    mockReassignQuota.mockReturnValue({
      data: { allowed: false, used: 5, limit: 5, remaining: 0 },
      isLoading: false,
    });

    render(
      <ReassignLeadDialog
        open={true}
        onOpenChange={vi.fn()}
        lead={mockLead}
      />,
      { wrapper: createWrapper() },
    );

    // The submit button text for officers is "Gửi yêu cầu"
    await waitFor(() => {
      const submitButton = screen.getByRole("button", { name: /gửi yêu cầu/i });
      expect(submitButton).toBeDisabled();
    });
  });

  it("should show quota exceeded error when remaining is 0", async () => {
    mockReassignQuota.mockReturnValue({
      data: { allowed: false, used: 5, limit: 5, remaining: 0 },
      isLoading: false,
    });

    render(
      <ReassignLeadDialog
        open={true}
        onOpenChange={vi.fn()}
        lead={mockLead}
      />,
      { wrapper: createWrapper() },
    );

    // The error message should be visible
    await waitFor(() => {
      expect(
        screen.getByText("Đã hết lượt phân công lại"),
      ).toBeInTheDocument();
    });

    // Also verify the badge shows "0/5"
    expect(screen.getByText("0/5")).toBeInTheDocument();
  });
});
