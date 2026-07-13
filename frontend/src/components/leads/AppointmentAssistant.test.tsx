import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

import { AppointmentAssistant } from "./AppointmentAssistant";

// Mock hook dữ liệu — cô lập khỏi React Query / network. useServerNow +
// useAppointmentNudges chạy THẬT để kiểm hành vi nudge theo thời gian.
vi.mock("@/hooks/useMyAppointments", () => ({
  useMyAppointments: vi.fn(),
}));
import { useMyAppointments } from "@/hooks/useMyAppointments";

const mockUse = useMyAppointments as unknown as ReturnType<typeof vi.fn>;

const BASE = new Date("2026-07-13T02:58:00.000Z");
const iso = (offsetMs: number) => new Date(BASE.getTime() + offsetMs).toISOString();

/**
 * 1 hẹn ĐÃ quá giờ (seed baseline → không nudge) + 1 hẹn sẽ chạm giờ sau +3s
 * (→ nudge bung khi thời gian trôi qua). `scope` quyết định officer/admin.
 */
function data(scope: "own" | "all") {
  return {
    data: {
      server_time: BASE.toISOString(),
      scope,
      overdue_count: 1,
      upcoming_count: 1,
      appointments: [
        {
          lead_id: 1,
          lead_name: "Nguyễn Văn Bình",
          phone: "0900000001",
          source: "Website",
          scheduled_at: iso(-3600_000), // quá hạn 1h → seed, không nudge
          is_overdue: true,
          degree_level: "Cao đẳng",
          major: "Điều dưỡng",
          officer_name: null,
        },
        {
          lead_id: 2,
          lead_name: "Bùi Hoan",
          phone: "0900000002",
          source: "Zalo",
          scheduled_at: iso(3000), // chạm giờ sau 3s → nudge
          is_overdue: false,
          degree_level: "Cao đẳng",
          major: "Dược",
          officer_name: null,
        },
      ],
    },
    isLoading: false,
    isError: false,
  };
}

describe("AppointmentAssistant — trợ lý nhắc hẹn", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.setSystemTime(BASE);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("bong bóng hiện badge số hẹn trễ (lớp A)", () => {
    mockUse.mockReturnValue(data("own"));
    render(<AppointmentAssistant />);
    expect(
      screen.getByRole("button", { name: /Trợ lý nhắc hẹn · 1 hẹn trễ/ }),
    ).toBeInTheDocument();
  });

  it("nudge TỰ BUNG khi hẹn tới giờ — tư vấn viên (scope=own, lớp B)", () => {
    mockUse.mockReturnValue(data("own"));
    render(<AppointmentAssistant />);

    // Chưa tới giờ → chưa có nudge
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    // Trôi 4s (server_now vượt mốc hẹn +3s) → nudge bung
    act(() => {
      vi.advanceTimersByTime(4000);
    });

    const toast = screen.getByRole("alertdialog", { name: "Nhắc gọi lại" });
    expect(toast).toBeInTheDocument();
    expect(screen.getByText(/Tới giờ gọi lại/)).toBeInTheDocument();
    expect(screen.getByText("Bùi Hoan")).toBeInTheDocument();
    // Gọi ngay = tel: của hẹn tới giờ
    expect(screen.getByText("Gọi ngay").closest("a")).toHaveAttribute(
      "href",
      "tel:0900000002",
    );
    // Hẹn đã-quá-giờ lúc tải KHÔNG bung (đã seed baseline)
    expect(screen.queryByText("Nguyễn Văn Bình")).not.toBeInTheDocument();
  });

  it("KHÔNG nudge cho admin/manager (scope=all quá ồn)", () => {
    mockUse.mockReturnValue(data("all"));
    render(<AppointmentAssistant />);
    act(() => {
      vi.advanceTimersByTime(4000);
    });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});
