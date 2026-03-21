import { describe, it, expect, beforeEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const mockMutateAsync = vi.fn();
const mockUseLead = vi.fn();
const mockUseAddConsultation = vi.fn();
const mockUseAllowedNextStatuses = vi.fn();

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock("@/hooks/useLeads", () => ({
  useLead: (...args: unknown[]) => mockUseLead(...args),
  useAddConsultation: () => mockUseAddConsultation(),
}));

vi.mock("@/hooks/usePipeline", () => ({
  useAllowedNextStatuses: (...args: unknown[]) => mockUseAllowedNextStatuses(...args),
}));

vi.mock("@/components/common/form", () => ({
  DateTimePicker: () => <div data-testid="date-time-picker" />,
}));

vi.mock("@/components/leads/LossReasonQuickSelect", () => ({
  LossReasonQuickSelect: () => null,
  showsLossReason: () => false,
  requiresLossReason: () => false,
}));

vi.mock("@/components/ui/dynamic-color-badge", () => ({
  ColorDot: () => <span data-testid="color-dot" />,
}));

import { QuickConsultationSectionV2 } from "./QuickConsultationSectionV2";

const CURRENT_STATUS = {
  id: "sts03",
  name: "Có nhu cầu tìm hiểu",
  color_code: "#FACC15",
  stage_id: "stg02",
  outcome_type: "neutral" as const,
  is_universal: false,
  is_final: false,
  status_type: "transition" as const,
  selectable_mode: "user" as const,
  updates_pipeline: true,
  counts_for_funnel: true,
  phase: "consultation",
  display_order: 20,
  stage: { id: "stg02", name: "Đang tư vấn", order: 2 },
};

describe("QuickConsultationSectionV2", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMutateAsync.mockResolvedValue({});
    mockUseAddConsultation.mockReturnValue({
      mutateAsync: mockMutateAsync,
      isPending: false,
    });
    mockUseLead.mockReturnValue({
      data: {
        id: 1,
        consultation_status_id: "sts03",
        pipeline_stage_id: "stg02",
        pipeline_stage: { id: "stg02", name: "Đang tư vấn", order: 2 },
        consultation_status: CURRENT_STATUS,
      },
    });
    mockUseAllowedNextStatuses.mockReturnValue({
      data: [
        {
          id: "sts06",
          name: "Đồng ý tư vấn",
          color_code: "#22C55E",
          stage_id: "stg02",
          display_order: 50,
          is_universal: false,
          outcome_type: "positive",
          is_final: false,
          status_type: "transition",
          selectable_mode: "user",
          updates_pipeline: true,
          counts_for_funnel: true,
          phase: "consultation",
          stage: { id: "stg02", name: "Đang tư vấn", order: 2 },
        },
      ],
      isLoading: false,
      isError: false,
      error: null,
    });
  });

  it("renders step 1 (content) before step 2 (results)", () => {
    render(<QuickConsultationSectionV2 leadId={1} />);

    expect(screen.getByText(/Bước 1: Nội dung tư vấn/i)).toBeDefined();
    expect(screen.getByText(/Bước 2: Kết quả tư vấn/i)).toBeDefined();
    // Notes textarea always visible
    expect(screen.getByPlaceholderText(/Nội dung tư vấn/i)).toBeDefined();
  });

  it("injects current status into grid when FSM omits it", () => {
    render(<QuickConsultationSectionV2 leadId={1} />);

    // Current status visible as highlighted button in grid
    const buttons = screen.getAllByText("Có nhu cầu tìm hiểu");
    expect(buttons.length).toBeGreaterThanOrEqual(1);
  });

  it("saves with current status via delayed commit", async () => {
    render(<QuickConsultationSectionV2 leadId={1} />);

    // Click current status in grid
    const statusButton = screen.getByRole("button", {
      name: /Chuyển sang trạng thái: Có nhu cầu tìm hiểu/i,
    });
    fireEvent.click(statusButton);

    const saveButton = await screen.findByRole("button", { name: /Lưu ngay/i });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({
        leadId: 1,
        data: expect.objectContaining({
          status_id: "sts03",
          method: "phone",
        }),
      });
    });
  });

  it("shows universal statuses as contact status", () => {
    mockUseAllowedNextStatuses.mockReturnValue({
      data: [
        {
          id: "sts01",
          name: "Không nghe máy",
          color_code: "#94A3B8",
          stage_id: null,
          display_order: 900,
          is_universal: true,
          outcome_type: "neutral",
          is_final: false,
          status_type: "activity",
          selectable_mode: "user",
          updates_pipeline: false,
          counts_for_funnel: false,
          phase: "universal",
          stage: null,
        },
      ],
      isLoading: false,
      isError: false,
      error: null,
    });

    render(<QuickConsultationSectionV2 leadId={1} />);

    expect(screen.getByText("Không liên hệ được")).toBeDefined();
  });

  it("schedule is collapsed by default", () => {
    render(<QuickConsultationSectionV2 leadId={1} />);

    expect(screen.getByText("Đặt lịch hẹn")).toBeDefined();
    // Schedule options not visible until clicked
    expect(screen.queryByText("Ngày mai")).toBeNull();

    // Click to expand
    fireEvent.click(screen.getByText("Đặt lịch hẹn"));
    expect(screen.getByText("Ngày mai")).toBeDefined();
  });

  it("shows method labels on all screen sizes", () => {
    render(<QuickConsultationSectionV2 leadId={1} />);

    expect(screen.getByText("Gọi điện")).toBeDefined();
    expect(screen.getByText("SMS")).toBeDefined();
    expect(screen.getByText("Video")).toBeDefined();
    expect(screen.getByText("Email")).toBeDefined();
    expect(screen.getByText("Gặp mặt")).toBeDefined();
  });
});
