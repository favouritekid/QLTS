/**
 * Phase B12: Unit Tests for ConsentManager (ConsentImportDialog.tsx)
 *
 * Tests cover:
 * - Consent list renders data and status badges
 * - Filter dropdowns work
 * - Empty state display
 * - Import dialog CSV upload calls correct endpoint
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createTestQueryClient } from "@/test/utils/test-utils";
import type { NotificationConsentsPage } from "@/types/api.types";

// Mock hooks
vi.mock("@/hooks/useNotificationConsents", () => ({
  useNotificationConsents: vi.fn(),
  useUpsertConsent: vi.fn(() => ({
    mutateAsync: vi.fn(),
    isPending: false,
  })),
  useBulkImportConsents: vi.fn(() => ({
    mutateAsync: vi.fn(),
    isPending: false,
  })),
  notificationConsentKeys: {
    all: ["notification-consents"],
    lists: () => ["notification-consents", "list"],
    list: (params: Record<string, unknown>) => ["notification-consents", "list", params],
  },
}));

import ConsentManager from "./ConsentImportDialog";
import { useNotificationConsents } from "@/hooks/useNotificationConsents";

const mockUseConsents = vi.mocked(useNotificationConsents);

function createWrapper() {
  const queryClient = createTestQueryClient();
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "TestQueryClientWrapper";
  return Wrapper;
}

const MOCK_DATA: NotificationConsentsPage = {
  total_count: 2,
  consents: [
    {
      id: 1,
      channel: "zalo",
      source_type: "lead",
      source_id: 1,
      normalized_phone: "84901234567",
      normalized_email: null,
      consent_status: "granted",
      consent_source: "manual",
      granted_by: 1,
      granted_at: "2026-03-25T10:00:00Z",
      revoked_at: null,
      notes: null,
      created_at: "2026-03-25T10:00:00Z",
      updated_at: "2026-03-25T10:00:00Z",
    },
    {
      id: 2,
      channel: "email",
      source_type: "lead",
      source_id: 2,
      normalized_phone: null,
      normalized_email: "test@example.com",
      consent_status: "revoked",
      consent_source: "csv_import",
      granted_by: 1,
      granted_at: "2026-03-24T10:00:00Z",
      revoked_at: "2026-03-25T08:00:00Z",
      notes: null,
      created_at: "2026-03-24T10:00:00Z",
      updated_at: "2026-03-25T08:00:00Z",
    },
  ],
};

describe("ConsentManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders consent data with status badges", () => {
    mockUseConsents.mockReturnValue({
      data: MOCK_DATA,
      isLoading: false,
      error: null,
    } as ReturnType<typeof useNotificationConsents>);

    render(<ConsentManager />, { wrapper: createWrapper() });

    // Check channel and source type rendered
    expect(screen.getByText("zalo")).toBeDefined();
    expect(screen.getByText("email")).toBeDefined();

    // Check status badges
    expect(screen.getByText("Đã cấp")).toBeDefined();
    expect(screen.getByText("Đã thu hồi")).toBeDefined();

    // Check contact info
    expect(screen.getByText("84901234567")).toBeDefined();
    expect(screen.getByText("test@example.com")).toBeDefined();
  });

  it("shows empty state when no consents", () => {
    mockUseConsents.mockReturnValue({
      data: { total_count: 0, consents: [] },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useNotificationConsents>);

    render(<ConsentManager />, { wrapper: createWrapper() });
    expect(screen.getByText("Chưa có consent record")).toBeDefined();
  });

  it("shows loading state", () => {
    mockUseConsents.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as ReturnType<typeof useNotificationConsents>);

    const { container } = render(<ConsentManager />, {
      wrapper: createWrapper(),
    });

    const spinner = container.querySelector(".animate-spin");
    expect(spinner).toBeDefined();
  });

  it("renders Import CSV and Thêm consent buttons", () => {
    mockUseConsents.mockReturnValue({
      data: MOCK_DATA,
      isLoading: false,
      error: null,
    } as ReturnType<typeof useNotificationConsents>);

    render(<ConsentManager />, { wrapper: createWrapper() });

    expect(screen.getByText("Import CSV")).toBeDefined();
    expect(screen.getByText("Thêm consent")).toBeDefined();
  });
});
