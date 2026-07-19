// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

const mockUseOfficerDistribution = vi.fn();
vi.mock("@/hooks/officer/useOfficerDistribution", () => ({
  useOfficerDistribution: (...args: unknown[]) =>
    mockUseOfficerDistribution(...args),
}));

// ⚠️ CỐ Ý KHÔNG mock @/components/ui/tooltip: lời khuyên (`boost`) nằm TRONG
// TooltipContent nên phải mở tooltip bằng tương tác THẬT mới assert được. Mock
// tooltip sẽ render sẵn nội dung và test mất hết giá trị.
import {
  EntryTooltip,
  OfficerDistributionPanel,
} from "./OfficerDistributionPanel";

const ME = {
  rank: 1,
  user_id: 18,
  username: "hien",
  full_name: "Hiền",
  unit_id: 14,
  unit_name: "Phòng Tuyển sinh",
  scoring_mode: "member",
  workload: 248,
  max_capacity: 400,
  weight: 2,
  self_sourced: 34,
  tuition_hold: 100,
  dist_load: 114,
  deducted: 134,
  real_util_pct: 28.5,
  fill_pct: 62.0,
  eff_util_pct: 14.3,
  score: 0.1425,
  overload_gate_pct: 37.0,
  overloaded: false,
  at_capacity: false,
  eligible_for_assignment: true,
  availability_status: "available",
  archetype: { key: "tuition_heavy", label: "Chủ yếu chờ học phí" },
  diagnosis: "100/248 lead đã đóng tiền nên không bị tính.",
  boost: "LỜI KHUYÊN RIÊNG CỦA HIỀN",
  is_current_user: true,
};

const PEER = {
  ...ME,
  rank: 2,
  user_id: 25,
  username: "kien",
  full_name: "Kiên",
  eff_util_pct: 23.0,
  archetype: { key: "balanced", label: "Cân bằng" },
  diagnosis: "Tải chủ yếu là lead hệ thống chia.",
  boost: null,
  is_current_user: false,
};

const OFFLINE = {
  ...PEER,
  rank: 3,
  user_id: 99,
  username: "quocduy",
  full_name: "Quốc Duy",
  eligible_for_assignment: false,
  availability_status: "offline",
  archetype: { key: "paused", label: "Đang tắt nhận lead" },
};

function mockPanel(entries: unknown[]) {
  mockUseOfficerDistribution.mockReturnValue({
    data: {
      unit_id: 14,
      total_officers: entries.length,
      scoring_mode: "member",
      flags_snapshot: { member_weighted: true },
      entries,
    },
    isLoading: false,
    error: null,
  });
}

describe("OfficerDistributionPanel", () => {
  beforeEach(() => {
    mockUseOfficerDistribution.mockReset();
  });

  it("hiện mọi người trong đơn vị kèm điểm bận", () => {
    mockPanel([ME, PEER]);
    render(<OfficerDistributionPanel />);

    expect(screen.getByText("Hiền")).toBeInTheDocument();
    expect(screen.getByText("Kiên")).toBeInTheDocument();
    expect(screen.getByText("14.3")).toBeInTheDocument();
    expect(screen.getByText("23")).toBeInTheDocument();
    expect(screen.getByText("BẠN")).toBeInTheDocument();
  });

  it("tách nhóm người đang không nhận lead", () => {
    mockPanel([ME, OFFLINE]);
    render(<OfficerDistributionPanel />);

    expect(screen.getByText("Đang không nhận lead")).toBeInTheDocument();
    expect(screen.getByText("Quốc Duy")).toBeInTheDocument();
  });

  it("KHÔNG lộ lời khuyên khi tooltip chưa mở", () => {
    mockPanel([ME, PEER]);
    render(<OfficerDistributionPanel />);

    expect(
      screen.queryByText("LỜI KHUYÊN RIÊNG CỦA HIỀN")
    ).not.toBeInTheDocument();
  });

  // Nội dung tooltip test TRỰC TIẾP: Radix chỉ render nó vào portal khi mở, mà
  // jsdom không drive được tương tác mở của Radix (dự án cũng theo cách này ở
  // `dialog.test.tsx` — render Radix mở sẵn). Hover thật verify bằng smoke trình duyệt.
  it("nội dung tooltip dòng của MÌNH: có phép tính + lời khuyên riêng", () => {
    render(<EntryTooltip e={ME} />);

    expect(screen.getByText("LỜI KHUYÊN RIÊNG CỦA HIỀN")).toBeInTheDocument();
    expect(screen.getByText(/Dành riêng cho bạn/)).toBeInTheDocument();
    // phép tính hiện bằng số thật (không phải FE tự tính)
    expect(
      screen.getByText(/Điểm bận = 114 ÷ \(400×2\) ×100 = 14\.3/)
    ).toBeInTheDocument();
    expect(screen.getByText(/Chỗ đầy thật = 248\/400 = 62%/)).toBeInTheDocument();
    expect(
      screen.getByText(/Ngưỡng tạm dừng = \(248−100\)\/400 = 37%/)
    ).toBeInTheDocument();
  });

  it("nội dung tooltip ĐỒNG NGHIỆP: có chẩn đoán nhưng KHÔNG có lời khuyên", () => {
    render(<EntryTooltip e={PEER} />);

    expect(
      screen.getByText("Tải chủ yếu là lead hệ thống chia.")
    ).toBeInTheDocument();
    // 🔒 tuyệt đối không rò lời khuyên của người khác
    expect(
      screen.queryByText("LỜI KHUYÊN RIÊNG CỦA HIỀN")
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Dành riêng cho bạn/)).not.toBeInTheDocument();
  });

  it("thanh đo dựng đúng 3 đoạn từ số backend (không tự tính lại)", () => {
    mockPanel([ME]);
    const { container } = render(<OfficerDistributionPanel />);

    // sys = eff_util_pct; weight = real_util - eff_util; skip = fill - real_util
    const widths = Array.from(
      container.querySelectorAll<HTMLElement>("span.h-full")
    ).map((el) => el.style.width);
    expect(widths).toEqual(["14.3%", "14.2%", "33.5%"]);
  });

  it("hiện skeleton khi đang tải và thông báo khi lỗi", () => {
    mockUseOfficerDistribution.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    });
    const { rerender } = render(<OfficerDistributionPanel />);
    expect(screen.queryByText("Hiền")).not.toBeInTheDocument();

    mockUseOfficerDistribution.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("boom"),
    });
    rerender(<OfficerDistributionPanel />);
    expect(
      screen.getByText(/Không tải được bảng điểm bận/)
    ).toBeInTheDocument();
  });
});
