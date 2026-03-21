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
  requiresLossReason: () => false,
}));

vi.mock("@/components/ui/dynamic-color-badge", () => ({
  ColorDot: () => <span data-testid="color-dot" />,
}));

import { QuickConsultationSectionV2 } from "./QuickConsultationSectionV2";

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
        consultation_status_id: "sts06",
        pipeline_stage_id: "stg02",
        pipeline_stage: {
          id: "stg02",
          name: "Đang tư vấn",
          order: 2,
        },
        consultation_status: {
          id: "sts06",
          name: "Có nhu cầu tìm hiểu",
          color_code: "#2563eb",
        },
      },
    });
    mockUseAllowedNextStatuses.mockReturnValue({
      data: [
        {
          id: "sts06",
          name: "Có nhu cầu tìm hiểu",
          color_code: "#2563eb",
          stage_id: "stg02",
          display_order: 1,
          is_universal: false,
          outcome_type: null,
          stage: {
            id: "stg02",
            name: "Đang tư vấn",
            order: 2,
          },
        },
        {
          id: "sts07",
          name: "Đã tiếp nhận hồ sơ",
          color_code: "#16a34a",
          stage_id: "stg03",
          display_order: 2,
          is_universal: false,
          outcome_type: "positive",
          stage: {
            id: "stg03",
            name: "Đã nộp hồ sơ",
            order: 3,
          },
        },
      ],
      isLoading: false,
      isError: false,
      error: null,
    });
  });

  it("allows recording a new consultation while keeping the current status", async () => {
    render(<QuickConsultationSectionV2 leadId={1} />);

    const currentStatusButton = screen.getByRole("button", {
      name: /Chuyển sang trạng thái: Có nhu cầu tìm hiểu/i,
    });

    expect(currentStatusButton).not.toBeDisabled();

    fireEvent.click(currentStatusButton);

    const saveButton = await screen.findByRole("button", { name: /Lưu ngay/i });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({
        leadId: 1,
        data: {
          status_id: "sts06",
          method: "phone",
          notes: "Ghi nhận: Có nhu cầu tìm hiểu",
          scheduled_at: null,
        },
      });
    });
  });
});
