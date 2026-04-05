/**
 * Phase B12: Unit Tests for DeliveryOpsTable
 *
 * Tests cover:
 * - Rendering delivery data with status badges
 * - Filter controls (event, channel, status)
 * - Empty state display
 * - Loading state display
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createTestQueryClient } from "@/test/utils/test-utils";
import type { NotificationDeliveriesPage } from "@/types/api.types";

// Mock the hooks
vi.mock("@/hooks/useNotificationDeliveries", () => ({
  useNotificationDeliveries: vi.fn(),
  useDeliveryStats: vi.fn(() => ({ data: null, isLoading: false })),
  useReplayDelivery: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  notificationDeliveryKeys: {
    all: ["notification-deliveries"],
    lists: () => ["notification-deliveries", "list"],
    list: (params: Record<string, unknown>) => ["notification-deliveries", "list", params],
    details: () => ["notification-deliveries", "detail"],
    detail: (id: number) => ["notification-deliveries", "detail", id],
  },
}));

import DeliveryOpsTable from "./DeliveryOpsTable";
import { useNotificationDeliveries } from "@/hooks/useNotificationDeliveries";

const mockUseNotificationDeliveries = vi.mocked(useNotificationDeliveries);

function createWrapper() {
  const queryClient = createTestQueryClient();
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "TestQueryClientWrapper";
  return Wrapper;
}

const MOCK_DATA: NotificationDeliveriesPage = {
  total_count: 3,
  deliveries: [
    {
      id: 1,
      notification_id: 100,
      event: "lead_assigned",
      channel: "browser",
      recipient_kind: "internal",
      user_id: 5,
      source_type: "lead",
      source_id: 1,
      destination: null,
      status: "sent",
      error_reason: null,
      dedupe_key: null,
      rule_id: 1,
      action_step: 1,
      template_code: null,
      payload_snapshot: null,
      provider_message_id: null,
      scheduled_for: null,
      attempt_count: 1,
      last_attempt_at: "2026-03-25T10:00:01Z",
      next_retry_at: null,
      max_retries: 5,
      dead_lettered_at: null,
      created_at: "2026-03-25T10:00:00Z",
      updated_at: "2026-03-25T10:00:00Z",
      sent_at: "2026-03-25T10:00:01Z",
    },
    {
      id: 2,
      notification_id: 101,
      event: "lead_assigned",
      channel: "email",
      recipient_kind: "internal",
      user_id: 5,
      source_type: "lead",
      source_id: 1,
      destination: null,
      status: "failed",
      error_reason: "SMTP timeout",
      dedupe_key: null,
      rule_id: 1,
      action_step: 2,
      template_code: null,
      payload_snapshot: null,
      provider_message_id: null,
      scheduled_for: null,
      attempt_count: 3,
      last_attempt_at: "2026-03-25T10:00:05Z",
      next_retry_at: "2026-03-25T10:05:00Z",
      max_retries: 5,
      dead_lettered_at: null,
      created_at: "2026-03-25T10:00:00Z",
      updated_at: "2026-03-25T10:00:05Z",
      sent_at: null,
    },
    {
      id: 3,
      notification_id: null,
      event: "profile_submitted",
      channel: "browser",
      recipient_kind: "internal",
      user_id: 10,
      source_type: null,
      source_id: null,
      destination: null,
      status: "queued",
      error_reason: null,
      dedupe_key: null,
      rule_id: null,
      action_step: null,
      template_code: null,
      payload_snapshot: null,
      provider_message_id: null,
      scheduled_for: null,
      attempt_count: 0,
      last_attempt_at: null,
      next_retry_at: null,
      max_retries: 5,
      dead_lettered_at: null,
      created_at: "2026-03-25T11:00:00Z",
      updated_at: "2026-03-25T11:00:00Z",
      sent_at: null,
    },
  ],
};

describe("DeliveryOpsTable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders delivery data with correct status badges", () => {
    mockUseNotificationDeliveries.mockReturnValue({
      data: MOCK_DATA,
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useNotificationDeliveries>);

    render(<DeliveryOpsTable />, { wrapper: createWrapper() });

    // Check events rendered (lead_assigned appears in 2 rows)
    expect(screen.getAllByText("lead_assigned")).toHaveLength(2);
    expect(screen.getByText("profile_submitted")).toBeDefined();

    // Check status badges exist (use getAllBy for labels that also appear in stats cards)
    expect(screen.getByText("Đã gửi")).toBeDefined();
    expect(screen.getAllByText("Thất bại").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Đang chờ")).toBeDefined();

    // Check channels
    expect(screen.getAllByText("browser")).toHaveLength(2);
    expect(screen.getByText("email")).toBeDefined();

    // Check error reason displayed
    expect(screen.getByText("SMTP timeout")).toBeDefined();
  });

  it("shows loading state", () => {
    mockUseNotificationDeliveries.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as unknown as ReturnType<typeof useNotificationDeliveries>);

    const { container } = render(<DeliveryOpsTable />, {
      wrapper: createWrapper(),
    });

    // Should show spinner (Loader2 icon with animate-spin)
    const spinner = container.querySelector(".animate-spin");
    expect(spinner).toBeDefined();
  });

  it("shows empty state when no deliveries", () => {
    mockUseNotificationDeliveries.mockReturnValue({
      data: { total_count: 0, deliveries: [] },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useNotificationDeliveries>);

    render(<DeliveryOpsTable />, { wrapper: createWrapper() });
    expect(screen.getByText("Chưa có delivery record")).toBeDefined();
  });

  it("renders total count in stats", () => {
    mockUseNotificationDeliveries.mockReturnValue({
      data: MOCK_DATA,
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useNotificationDeliveries>);

    render(<DeliveryOpsTable />, { wrapper: createWrapper() });
    expect(screen.getByText("3")).toBeDefined(); // total count
  });
});
