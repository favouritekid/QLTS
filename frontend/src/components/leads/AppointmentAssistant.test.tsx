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

// Tick từng giây MỘT (mỗi lần 1 act = 1 flush) — mô phỏng đúng nhịp setInterval
// 1s thật: engine "arm khi thấy tương lai" cần quan sát hẹn ở từng mốc trước khi
// nó chạm giờ. (Nhảy `advanceTimersByTime(4000)` một phát bị React gộp thành 1
// render → bỏ qua các mốc trung gian → không giống thực tế.)
function tick(seconds: number) {
  for (let i = 0; i < seconds; i++) {
    act(() => {
      vi.advanceTimersByTime(1000);
    });
  }
}

function appt(
  id: number,
  offsetMs: number,
  is_overdue: boolean,
  name = `Lead ${id}`,
) {
  return {
    lead_id: id,
    lead_name: name,
    phone: `090000000${id}`,
    source: "Website",
    scheduled_at: iso(offsetMs),
    is_overdue,
    degree_level: "Cao đẳng",
    major: "Dược",
    officer_name: null,
  };
}

function resp(
  scope: "own" | "all",
  appointments: ReturnType<typeof appt>[],
  overdue_count = 0,
  upcoming_count = 0,
) {
  return {
    data: { server_time: BASE.toISOString(), scope, overdue_count, upcoming_count, appointments },
    isLoading: false,
    isError: false,
  };
}

/** Kịch bản mặc định: 1 hẹn đã quá giờ (đã lỡ) + 1 hẹn chạm giờ sau +3s. */
function data(scope: "own" | "all") {
  return resp(
    scope,
    [appt(1, -3600_000, true, "Nguyễn Văn Bình"), appt(2, 3000, false, "Bùi Hoan")],
    1,
    1,
  );
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
    tick(4);

    const toast = screen.getByRole("alertdialog", { name: "Nhắc gọi lại" });
    expect(toast).toBeInTheDocument();
    expect(screen.getByText(/Tới giờ gọi lại/)).toBeInTheDocument();
    expect(screen.getByText("Bùi Hoan")).toBeInTheDocument();
    // Gọi ngay = tel: của hẹn tới giờ
    expect(screen.getByText("Gọi ngay").closest("a")).toHaveAttribute(
      "href",
      "tel:0900000002",
    );
    // Hẹn đã-quá-giờ lúc tải KHÔNG bung (đã ghi nhận là "đã lỡ")
    expect(screen.queryByText("Nguyễn Văn Bình")).not.toBeInTheDocument();
  });

  it("KHÔNG nudge cho admin/manager (scope=all quá ồn)", () => {
    mockUse.mockReturnValue(data("all"));
    render(<AppointmentAssistant />);
    tick(4);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("dời lịch → nudge LẠI đúng giờ mới (khóa dedupe lead@scheduled_at)", () => {
    mockUse.mockReturnValue(resp("own", [appt(7, 3000, false, "Phan Đức")], 0, 1));
    render(<AppointmentAssistant />);
    tick(4); // vượt +3s → nudge lần 1
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();

    // Cùng lead 7 nhưng scheduled_at MỚI (dời sang +9s) → khóa mới
    mockUse.mockReturnValue(resp("own", [appt(7, 9000, false, "Phan Đức")], 0, 1));
    tick(1); // re-render nhận data mới → toast cũ auto-đóng (khóa cũ biến mất), arm khóa mới
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    tick(5); // tới +10s > +9s → nudge LẠI (khóa cũ chỉ theo lead_id sẽ bị chặn)
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("Phan Đức")).toBeInTheDocument();
  });

  it("hẹn quá-giờ XUẤT HIỆN muộn (refetch) KHÔNG bung — chỉ crossing thật mới nudge", () => {
    mockUse.mockReturnValue(resp("own", [appt(8, 30_000, false)], 0, 1)); // hẹn tương lai xa
    render(<AppointmentAssistant />);
    tick(2); // A armed, chưa tới giờ
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    // Refetch thêm hẹn ĐÃ quá giờ (lần đầu thấy đã trễ) → phải im
    mockUse.mockReturnValue(resp("own", [appt(8, 30_000, false), appt(9, -1000, true)], 1, 1));
    tick(1);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});
