import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import { ReminderBody } from "./AppointmentReminder";

// Mock hook dữ liệu — cô lập component khỏi React Query / network.
vi.mock("@/hooks/useMyAppointments", () => ({
  useMyAppointments: vi.fn(),
  isForbiddenError: () => false, // mặc định không bị 403 → widget render
}));
import { useMyAppointments } from "@/hooks/useMyAppointments";

const mockUse = useMyAppointments as unknown as ReturnType<typeof vi.fn>;

const NOW = "2026-07-13T02:58:00.000Z";

function withData() {
  return {
    data: {
      server_time: NOW,
      scope: "all", // admin/manager xem toàn bộ → có officer_name
      overdue_count: 2,
      upcoming_count: 1,
      appointments: [
        {
          lead_id: 1,
          lead_name: "Nguyễn Văn Bình",
          phone: "0900000001",
          source: "Website",
          scheduled_at: "2026-07-12T23:46:00.000Z", // quá hạn nhất → hero
          is_overdue: true,
          degree_level: "Cao đẳng",
          major: "Điều dưỡng",
          officer_name: "Trần Quản Lý",
        },
        {
          lead_id: 2,
          lead_name: "Bùi Hoan",
          phone: "0900000002",
          source: "Zalo",
          scheduled_at: "2026-07-13T02:32:00.000Z", // quá hạn
          is_overdue: true,
          degree_level: "Trung cấp",
          major: "Kế toán",
          officer_name: "Lê Tư Vấn",
        },
        {
          lead_id: 3,
          lead_name: "Thanh Hương",
          phone: "0900000003",
          source: "Facebook",
          scheduled_at: "2026-07-13T03:40:00.000Z", // sắp tới
          is_overdue: false,
          degree_level: "Đại học",
          major: "Công nghệ thông tin",
          officer_name: "Phạm Officer",
        },
      ],
    },
    isLoading: false,
    isError: false,
  };
}

describe("AppointmentReminder / ReminderBody", () => {
  beforeEach(() => vi.clearAllMocks());

  it("render hero + hàng + đường BÂY GIỜ + Gọi ngay khi có lịch hẹn", () => {
    mockUse.mockReturnValue(withData());
    render(<ReminderBody />);

    // hero = lead quá hạn nhất (đầu danh sách ASC)
    expect(screen.getByText("Nguyễn Văn Bình")).toBeInTheDocument();
    // các hàng còn lại
    expect(screen.getByText("Bùi Hoan")).toBeInTheDocument();
    expect(screen.getByText("Thanh Hương")).toBeInTheDocument();
    // signature: đường BÂY GIỜ chia quá hạn / sắp tới
    expect(screen.getByText(/BÂY GIỜ/)).toBeInTheDocument();
    // Gọi ngay = tel: của hero
    const call = screen.getByText("Gọi ngay").closest("a");
    expect(call).toHaveAttribute("href", "tel:0900000001");
    // trình độ viết tắt (getDegreeLevelAbbr): "Cao đẳng" → "CĐ" + tên NV (scope=all)
    expect(screen.getByText(/CĐ Điều dưỡng · Trần Quản Lý/)).toBeInTheDocument();
    // scope=all (admin/manager) → tiêu đề "Lịch hẹn tư vấn" (không phải "của bạn")
    expect(screen.getByText("Lịch hẹn tư vấn")).toBeInTheDocument();
  });

  it("empty state khi không có lịch hẹn", () => {
    mockUse.mockReturnValue({
      data: { server_time: NOW, scope: "own", overdue_count: 0, upcoming_count: 0, appointments: [] },
      isLoading: false,
      isError: false,
    });
    render(<ReminderBody />);
    expect(screen.getByText(/Hết hẹn/)).toBeInTheDocument();
  });

  it("error state không crash", () => {
    mockUse.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    render(<ReminderBody />);
    expect(screen.getByText(/Không tải được/)).toBeInTheDocument();
  });
});
