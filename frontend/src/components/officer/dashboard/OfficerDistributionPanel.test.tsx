// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const mockUseOfficerDistribution = vi.fn();
vi.mock("@/hooks/officer/useOfficerDistribution", () => ({
  useOfficerDistribution: (...args: unknown[]) =>
    mockUseOfficerDistribution(...args),
}));

// ⚠️ CỐ Ý KHÔNG mock @/components/ui/popover: lời khuyên (`boost`) nằm TRONG
// TooltipContent nên phải mở tooltip bằng tương tác THẬT mới assert được. Mock
// tooltip sẽ render sẵn nội dung và test mất hết giá trị.
import {
  EntryDetails,
  OfficerDistributionPanel,
} from "./OfficerDistributionPanel";

const ME = {
  rank: 1,
  user_id: 18,
  full_name: "Hiền",
  unit_id: 14,
  unit_name: "Phòng Tuyển sinh",
  scoring_mode: "member",
  workload: 248,
  max_capacity: 400,
  weight: 2,
  self_sourced: 54,
  tuition_hold: 100,
  overlap: 20,
  dist_load: 114,
  deducted: 134,
  real_util_pct: 28.5,
  fill_pct: 62.0,
  eff_util_pct: 14.2,
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
    // 14.2 in ở CẢ thẻ "của bạn" lẫn hàng danh sách — hai vai trò khác nhau
    expect(screen.getAllByText("14.2").length).toBeGreaterThan(0);
    expect(screen.getByText("23")).toBeInTheDocument();
    expect(screen.getByText("BẠN")).toBeInTheDocument();
  });

  it("tách nhóm người đang không nhận lead", () => {
    mockPanel([ME, OFFLINE]);
    render(<OfficerDistributionPanel />);

    expect(screen.getByText("Đang không nhận lead")).toBeInTheDocument();
    expect(screen.getByText("Quốc Duy")).toBeInTheDocument();
  });

  it("lời khuyên của MÌNH đọc được NGAY, không phải bấm", () => {
    // Đây là lý do tồn tại của thẻ "Việc của bạn": `boost` là thứ duy nhất
    // officer hành động được, chôn nó trong popover = gần như không ai đọc.
    mockPanel([ME, PEER]);
    render(<OfficerDistributionPanel />);

    expect(screen.getByText("Việc của bạn")).toBeInTheDocument();
    expect(screen.getByText("LỜI KHUYÊN RIÊNG CỦA HIỀN")).toBeInTheDocument();
  });

  it("🔒 thẻ 'của bạn' KHÔNG hiện với người xem không có dòng nào của mình", () => {
    // Admin/manager: mọi entry đều is_current_user=false. Kể cả khi backend lỡ
    // rò `boost` của officer, mặt bảng phải câm.
    mockPanel([{ ...PEER, boost: "RÒ RỈ KHÔNG ĐƯỢC HIỆN" }]);
    render(<OfficerDistributionPanel />);

    expect(screen.queryByText("Việc của bạn")).not.toBeInTheDocument();
    expect(screen.queryByText("RÒ RỈ KHÔNG ĐƯỢC HIỆN")).not.toBeInTheDocument();
    // ...và tiêu đề không xưng "bạn" với người không nằm trong bảng
    expect(
      screen.getByText("Vì sao hệ thống chia lead cho từng người")
    ).toBeInTheDocument();
  });

  it("xưng 'bạn' chỉ khi người xem thật sự có dòng trong bảng", () => {
    mockPanel([ME, PEER]);
    render(<OfficerDistributionPanel />);

    expect(screen.getByText("Vì sao bạn được chia lead")).toBeInTheDocument();
  });

  it("thẻ 'của bạn' nói rõ thứ hạng, nhưng im khi đơn vị xếp luân phiên", () => {
    // `legacy` xếp theo lượt chứ không đọc điểm bận ⇒ in thứ hạng là nói sai
    // cơ chế phân phối.
    mockPanel([ME, PEER]);
    const first = render(<OfficerDistributionPanel />);
    expect(screen.getByText(/Đang xếp thứ/)).toBeInTheDocument();
    first.unmount();

    mockPanel([
      { ...ME, scoring_mode: "legacy" },
      { ...PEER, scoring_mode: "legacy" },
    ]);
    render(<OfficerDistributionPanel />);
    expect(screen.queryByText(/Đang xếp thứ/)).not.toBeInTheDocument();
  });

  // Nội dung tooltip test TRỰC TIẾP: Radix chỉ render nó vào portal khi mở, mà
  // jsdom không drive được tương tác mở của Radix (dự án cũng theo cách này ở
  // `dialog.test.tsx` — render Radix mở sẵn). Hover thật verify bằng smoke trình duyệt.
  it("nội dung tooltip dòng của MÌNH: có phép tính + lời khuyên riêng", () => {
    render(<EntryDetails e={ME} />);

    expect(screen.getByText("LỜI KHUYÊN RIÊNG CỦA HIỀN")).toBeInTheDocument();
    expect(screen.getByText(/chỉ bạn thấy/)).toBeInTheDocument();
    // phép tính hiện bằng số thật (không phải FE tự tính)
    expect(
      screen.getByText(/Điểm bận = 114 ÷ \(400×2\) ×100 = 14\.2/)
    ).toBeInTheDocument();
    expect(screen.getByText(/Chỗ đầy thật = 248\/400 = 62%/)).toBeInTheDocument();
    expect(
      screen.getByText(/Ngưỡng tạm dừng = \(248−100\)\/400 = 37%/)
    ).toBeInTheDocument();
  });

  it("nội dung tooltip ĐỒNG NGHIỆP: có chẩn đoán nhưng KHÔNG có lời khuyên", () => {
    render(<EntryDetails e={PEER} />);

    expect(
      screen.getByText("Tải chủ yếu là lead hệ thống chia.")
    ).toBeInTheDocument();
    // 🔒 tuyệt đối không rò lời khuyên của người khác
    expect(
      screen.queryByText("LỜI KHUYÊN RIÊNG CỦA HIỀN")
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/chỉ bạn thấy/)).not.toBeInTheDocument();
  });

  it("🔒 FAIL-CLOSED: peer lỡ có boost vẫn KHÔNG được lộ", () => {
    // Giả lập backend rò rỉ: entry của người khác lại kèm boost.
    // UI phải câm vì điều kiện render là is_current_user && boost.
    const leaky = { ...PEER, boost: "RÒ RỈ KHÔNG ĐƯỢC HIỆN" };
    render(<EntryDetails e={leaky} />);

    expect(screen.queryByText("RÒ RỈ KHÔNG ĐƯỢC HIỆN")).not.toBeInTheDocument();
    expect(screen.queryByText(/chỉ bạn thấy/)).not.toBeInTheDocument();
    // nhưng phần công khai vẫn render bình thường
    expect(
      screen.getByText("Tải chủ yếu là lead hệ thống chia.")
    ).toBeInTheDocument();
  });

  it("gom nhóm theo ĐƠN VỊ khi phạm vi trải nhiều đơn vị", () => {
    const otherUnit = {
      ...PEER,
      rank: 1, // rank đánh RIÊNG từng đơn vị ⇒ trùng số với dòng đơn vị khác
      user_id: 77,
      full_name: "Phạm Thu",
      unit_id: 15,
      unit_name: "Phòng Đào tạo",
      scoring_mode: "legacy",
    };
    mockPanel([ME, PEER, otherUnit]);
    render(<OfficerDistributionPanel />);

    // Có header đơn vị cho từng nhóm + cảnh báo không so chéo được
    expect(screen.getByText("Phòng Tuyển sinh")).toBeInTheDocument();
    expect(screen.getByText("Phòng Đào tạo")).toBeInTheDocument();
    expect(screen.getByText(/riêng trong từng đơn vị/)).toBeInTheDocument();
    // nhãn chế độ xếp hạng hiển thị bằng lời thường
    expect(screen.getByText(/cách xếp: theo điểm bận/)).toBeInTheDocument();
    expect(screen.getByText(/cách xếp: luân phiên/)).toBeInTheDocument();
  });

  it("KHÔNG hiện header đơn vị khi chỉ có một đơn vị", () => {
    mockPanel([ME, PEER]);
    render(<OfficerDistributionPanel />);

    expect(screen.queryByText("Phòng Tuyển sinh")).not.toBeInTheDocument();
    expect(screen.queryByText(/riêng trong từng đơn vị/)).not.toBeInTheDocument();
  });

  it("thanh đo dựng đúng 3 đoạn từ số backend (không tự tính lại)", () => {
    mockPanel([PEER]); // peer ⇒ đúng MỘT thanh (không có thẻ "của bạn")
    const { container } = render(<OfficerDistributionPanel />);

    // sys = eff_util_pct; weight = real_util - eff_util; skip = fill - real_util
    const widthOf = (seg: string) =>
      container.querySelector<HTMLElement>(`[data-seg="${seg}"]`)?.style.width;
    expect(widthOf("sys")).toBe("23%");
    expect(widthOf("weight")).toBe("5.5%");
    expect(widthOf("skip")).toBe("33.5%");
    // vạch mốc so ngưỡng đặt theo overload_gate_pct, KHÔNG theo fill_pct
    expect(container.querySelector<HTMLElement>('[data-seg="gate"]')?.style.left).toBe(
      "37%"
    );
  });

  it("thẻ 'của bạn' và hàng danh sách vẽ CÙNG một thanh", () => {
    // Hai chỗ cùng đọc `segmentsOf` ⇒ không thể lệch nhau; nếu sau này ai tách
    // logic ra hai nơi, test này đỏ.
    mockPanel([ME]);
    const { container } = render(<OfficerDistributionPanel />);

    const sys = Array.from(
      container.querySelectorAll<HTMLElement>('[data-seg="sys"]')
    ).map((el) => el.style.width);
    expect(sys).toHaveLength(2); // thẻ + hàng
    expect(new Set(sys)).toEqual(new Set(["14.2%"]));
  });

  it("mỗi con số trong bảng chi tiết đeo đúng màu của đoạn sinh ra nó", () => {
    // Đây là cầu nối bar ↔ số: không có nó người xem phải tự dò.
    const { container } = render(<EntryDetails e={ME} />);

    const swatch = (seg: string) =>
      container.querySelector<HTMLElement>(`[data-swatch="${seg}"]`);
    // "không tính" = đoạn xanh lá, "hệ thống tính"/"điểm bận" = đoạn chàm,
    // "ưu tiên kỳ cựu" = đoạn xanh dương nhạt
    expect(swatch("skip")?.className).toContain("bg-success-500");
    expect(swatch("sys")?.className).toContain("bg-primary");
    expect(swatch("weight")?.className).toContain("bg-info-500");
  });

  it("KHÔNG hiện dòng 'ưu tiên kỳ cựu' khi trọng số = 1", () => {
    const { container } = render(<EntryDetails e={{ ...ME, weight: 1 }} />);
    expect(container.querySelector('[data-swatch="weight"]')).toBeNull();
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

  it("nhãn 'không tính' KHÔNG trình bày như phép cộng khi có phần giao", () => {
    // deducted = self + tuition − overlap. Nếu in "54 + 100" cạnh "−134",
    // người đọc thấy một phép cộng không bằng tổng của chính nó.
    render(<EntryDetails e={ME} />);
    expect(
      screen.getByText(/tự tìm 54, đã đóng tiền 100, trùng 20/)
    ).toBeInTheDocument();
    expect(screen.queryByText(/tự tìm 54 \+ đã đóng tiền 100/)).not.toBeInTheDocument();
  });

  it("không có phần giao thì vẫn dùng dấu + cho dễ đọc", () => {
    render(<EntryDetails e={{ ...ME, overlap: 0, self_sourced: 34, deducted: 134 }} />);
    expect(
      screen.getByText(/tự tìm 34 \+ đã đóng tiền 100/)
    ).toBeInTheDocument();
  });

  it("CHẠM/BẤM mở được bảng chi tiết — đường dùng trên điện thoại", async () => {
    const user = (await import("@testing-library/user-event")).default.setup();
    mockPanel([ME]);
    render(<OfficerDistributionPanel />);

    expect(screen.queryByText(/chỉ bạn thấy/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Hiền/ }));
    expect(await screen.findByText(/chỉ bạn thấy/)).toBeInTheDocument();
  });

  it("một đơn vị vẫn nói rõ cách xếp (legacy không được hiện điểm bận trơ)", () => {
    mockUseOfficerDistribution.mockReturnValue({
      data: {
        unit_id: 14,
        total_officers: 1,
        scoring_mode: "legacy",
        flags_snapshot: {},
        entries: [{ ...ME, scoring_mode: "legacy" }],
      },
      isLoading: false,
      error: null,
    });
    render(<OfficerDistributionPanel />);
    expect(screen.getByText(/Cách xếp của đơn vị/)).toBeInTheDocument();
    expect(screen.getByText(/xếp theo lượt/)).toBeInTheDocument();
  });
});

// =============================================================================
// Hai đường mở bảng chi tiết. Rê chuột là lớp tăng tiến cho máy để bàn; nó
// KHÔNG được lấy mất hành vi bấm-để-giữ, vì bảng dài và người đọc phải rời
// chuột được. jsdom không có `matchMedia` nên phải mock để bật nhánh này.
// =============================================================================
describe("OfficerDistributionPanel — rê chuột vs bấm ghim", () => {
  const DIAG = "Tải chủ yếu là lead hệ thống chia.";

  beforeEach(() => {
    mockUseOfficerDistribution.mockReset();
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      configurable: true,
      value: (query: string) => ({
        matches: true, // giả lập máy có chuột thật
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }),
    });
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    // Trả jsdom về trạng thái không-hover để không rò sang file test khác.
    delete (window as unknown as Record<string, unknown>).matchMedia;
  });

  const settle = async (ms: number) => {
    await act(async () => {
      vi.advanceTimersByTime(ms);
    });
  };

  it("rê vào thì mở, rê ra thì đóng", async () => {
    mockPanel([PEER]);
    render(<OfficerDistributionPanel />);
    const row = screen.getByRole("button", { name: /Kiên/ });

    fireEvent.pointerEnter(row, { pointerType: "mouse" });
    await settle(300);
    expect(screen.getByText(DIAG)).toBeInTheDocument();

    fireEvent.pointerLeave(row, { pointerType: "mouse" });
    await settle(300);
    expect(screen.queryByText(DIAG)).not.toBeInTheDocument();
  });

  it("BẤM là ghim: rê chuột ra vẫn đọc tiếp được", async () => {
    mockPanel([PEER]);
    render(<OfficerDistributionPanel />);
    const row = screen.getByRole("button", { name: /Kiên/ });

    fireEvent.click(row);
    await settle(0);
    expect(screen.getByText(DIAG)).toBeInTheDocument();

    fireEvent.pointerLeave(row, { pointerType: "mouse" });
    await settle(600);
    expect(screen.getByText(DIAG)).toBeInTheDocument();
  });

  it("máy KHÔNG có chuột: rê không mở, mà chạm thì vẫn mở và giữ", async () => {
    // Chốt chặn thật cho điện thoại là media query, không phải `pointerType`
    // (jsdom không truyền được trường đó nên đừng test bằng nó). Trên cảm ứng
    // pointerEnter bắn kèm cú chạm rồi pointerLeave ngay khi nhấc ngón — nếu
    // nhánh rê chuột ăn cặp sự kiện này thì bảng vừa mở đã tự đóng.
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      configurable: true,
      value: (query: string) => ({
        matches: false, // không hover, không con trỏ tinh
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }),
    });

    mockPanel([PEER]);
    render(<OfficerDistributionPanel />);
    const row = screen.getByRole("button", { name: /Kiên/ });

    fireEvent.pointerEnter(row);
    await settle(300);
    expect(screen.queryByText(DIAG)).not.toBeInTheDocument();

    fireEvent.click(row); // cú chạm thật sự
    await settle(0);
    fireEvent.pointerLeave(row);
    await settle(600);
    expect(screen.getByText(DIAG)).toBeInTheDocument();
  });
});
