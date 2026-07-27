/**
 * CalculateFeeDialog behaviour test (PR #7).
 *
 * Asserts the dialog contract only — full fee calculation is covered
 * by backend tests. We verify:
 *  - Tuition variant shows the semester dropdown; non-tuition hides it.
 *  - Submitting posts the form values (including semester_no for tuition,
 *    omitted for non-tuition) to useCalculateFee.
 *  - Cancel closes without firing the mutation.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@/test/utils/test-utils";

import { CalculateFeeDialog } from "./CalculateFeeDialog";

const mutateAsync = vi.fn();

// useAuth điều khiển role để test vùng "Miễn/giảm" (chỉ admin/manager/accountant).
// Mặc định officer → vùng giảm ẩn (các test cũ không đổi). Đổi .role trong test.
type PolicyOption = {
  id: number;
  name: string;
  discount_type: string;
  discount_value: string;
  amount: string;
  selectable: boolean;
  reason: string | null;
  reason_text: string | null;
  selected: boolean;
  applied: boolean;
};

const { mockAuth, mockPreview } = vi.hoisted(() => ({
  mockAuth: { role: "officer" },
  mockPreview: {
    data: {
      base_amount: "5000000",
      total_discount: "0",
      final_amount: "5000000",
      semester_no: 1,
      discount_policies: [] as PolicyOption[],
    },
    isLoading: false,
    isError: false,
  },
}));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: mockAuth }),
}));

vi.mock("@/hooks/finance/useFees", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/finance/useFees")>(
    "@/hooks/finance/useFees"
  );
  return {
    ...actual,
    useCalculateFee: () => ({ mutateAsync, isPending: false }),
    // Lịch thu "đóng trước" + danh sách ưu đãi — stub để khối preview render tất
    // định, không gọi mạng. Test đổi ``mockPreview.data`` để dựng từng ca.
    useTuitionPreview: () => mockPreview,
  };
});

// PR #7 review: dialog fetches active plans instead of hard-coding codes.
// Stub them so the Select renders without a real network call.
vi.mock("@/hooks/finance/useInstallmentPlans", () => ({
  useInstallmentPlans: () => ({
    data: [
      { id: 1, code: "FULL", name: "Thanh toán 1 lần", is_active: true, schedule: [] },
      { id: 2, code: "TWO_TERM", name: "Thanh toán 2 đợt", is_active: true, schedule: [] },
      { id: 3, code: "QUARTERLY", name: "Thanh toán theo quý", is_active: true, schedule: [] },
    ],
    isLoading: false,
  }),
}));

describe("CalculateFeeDialog", () => {
  beforeEach(() => {
    mutateAsync.mockReset();
    mutateAsync.mockResolvedValue({ id: 1, admission_profile_id: 42 });
    mockAuth.role = "officer"; // mặc định: vùng miễn/giảm ẩn
    mockPreview.data.discount_policies = []; // mặc định: ngành chưa gắn ưu đãi
    mockPreview.data.total_discount = "0";
    mockPreview.data.final_amount = "5000000";
  });

  it("renders semester dropdown only for tuition fee_type", () => {
    render(
      <CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />
    );
    // Default fee_type is tuition → semester label + select visible.
    // `getByLabelText` matches the semester_no <Label htmlFor="semester_no">.
    expect(screen.getByLabelText(/học kỳ/i)).toBeInTheDocument();
  });

  it("fires mutation with semester_no when submitting tuition", async () => {
    render(
      <CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />
    );
    fireEvent.click(screen.getByRole("button", { name: /^tính học phí$/i }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        admission_profile_id: 42,
        fee_type: "tuition",
        semester_no: 1,
        installment_plan_code: "FULL",
      });
    });
  });

  it("cancel button closes dialog without calling mutation", () => {
    const onOpenChange = vi.fn();
    render(
      <CalculateFeeDialog open onOpenChange={onOpenChange} profileId={42} />
    );
    fireEvent.click(screen.getByRole("button", { name: /hủy/i }));
    expect(mutateAsync).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  // ---- Lịch thu "đóng trước" (2026-06-29) ----

  it("down-payment toggle reveals amount + due-date inputs", () => {
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);
    // Hidden by default.
    expect(screen.queryByLabelText(/số đóng đợt đầu/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: /đóng trước theo đợt/i }));
    expect(screen.getByLabelText(/số đóng đợt đầu/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/hạn đợt đầu/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/hạn phần còn lại/i)).toBeInTheDocument();
  });

  it("submit is blocked until down-payment + both due dates are present", () => {
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);
    fireEvent.click(screen.getByRole("switch", { name: /đóng trước theo đợt/i }));

    const submit = screen.getByRole("button", { name: /^tính học phí$/i });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/số đóng đợt đầu/i), {
      target: { value: "2000000" },
    });
    // Dates still empty → blocked.
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/hạn đợt đầu/i), {
      target: { value: "2026-09-01" },
    });
    fireEvent.change(screen.getByLabelText(/hạn phần còn lại/i), {
      target: { value: "2026-11-01" },
    });
    expect(submit).toBeEnabled();
  });

  it("posts collection_schedule_mode + down-payment fields (no plan code)", async () => {
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);
    fireEvent.click(screen.getByRole("switch", { name: /đóng trước theo đợt/i }));
    fireEvent.change(screen.getByLabelText(/số đóng đợt đầu/i), {
      target: { value: "2000000" },
    });
    fireEvent.change(screen.getByLabelText(/hạn đợt đầu/i), {
      target: { value: "2026-09-01" },
    });
    fireEvent.change(screen.getByLabelText(/hạn phần còn lại/i), {
      target: { value: "2026-11-01" },
    });

    fireEvent.click(screen.getByRole("button", { name: /^tính học phí$/i }));
    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        admission_profile_id: 42,
        fee_type: "tuition",
        semester_no: 1,
        collection_schedule_mode: "down_payment",
        down_payment: "2000000",
        down_payment_due: "2026-09-01",
        remainder_due: "2026-11-01",
      });
    });
  });

  it("posts installment_plan_code (no schedule fields) when toggle stays off", async () => {
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);
    fireEvent.click(screen.getByRole("button", { name: /^tính học phí$/i }));
    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        admission_profile_id: 42,
        fee_type: "tuition",
        semester_no: 1,
        installment_plan_code: "FULL",
      });
    });
  });

  // ---- Miễn/giảm học phí (Pha 2, 2026-06-29) ----

  it("discount section hidden for officer, visible for finance staff", () => {
    const { unmount } = render(
      <CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />
    );
    // Officer (mặc định) → không thấy toggle miễn/giảm.
    expect(
      screen.queryByRole("switch", { name: /miễn\/giảm học phí/i })
    ).not.toBeInTheDocument();
    unmount();

    mockAuth.role = "accountant";
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);
    expect(
      screen.getByRole("switch", { name: /miễn\/giảm học phí/i })
    ).toBeInTheDocument();
  });

  it("manual discount submit posts target_final_amount + reason", async () => {
    mockAuth.role = "accountant";
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);
    fireEvent.click(screen.getByRole("switch", { name: /miễn\/giảm học phí/i }));
    fireEvent.change(screen.getByLabelText(/học phí áp dụng/i), {
      target: { value: "1000000" },
    });
    fireEvent.change(screen.getByLabelText(/^lý do/i), {
      target: { value: "Hoc bong dac biet theo quyet dinh" },
    });

    fireEvent.click(screen.getByRole("button", { name: /^tính học phí$/i }));
    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        admission_profile_id: 42,
        fee_type: "tuition",
        semester_no: 1,
        installment_plan_code: "FULL",
        target_final_amount: "1000000",
        manual_discount_reason: "Hoc bong dac biet theo quyet dinh",
      });
    });
  });

  it("manual discount blocked until target < final + reason >=10", () => {
    mockAuth.role = "manager";
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);
    fireEvent.click(screen.getByRole("switch", { name: /miễn\/giảm học phí/i }));

    const submit = screen.getByRole("button", { name: /^tính học phí$/i });
    expect(submit).toBeDisabled();

    // target hợp lệ (< 5,000,000 mock) nhưng chưa có lý do → vẫn chặn.
    fireEvent.change(screen.getByLabelText(/học phí áp dụng/i), {
      target: { value: "1000000" },
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/^lý do/i), {
      target: { value: "Hoc bong dac biet theo quyet dinh" },
    });
    expect(submit).toBeEnabled();
  });

  // ===================================================================
  // Ưu đãi theo CHÍNH SÁCH của ngành (owner chốt 26-07)
  // ===================================================================

  const policy = (over: Partial<PolicyOption> = {}): PolicyOption => ({
    id: 4,
    name: "Giảm đăng ký sớm",
    discount_type: "percentage",
    discount_value: "10",
    amount: "500000",
    selectable: true,
    reason: null,
    reason_text: null,
    selected: true,
    applied: true,
    ...over,
  });

  it("ẩn hẳn khối ưu đãi khi ngành chưa gắn chính sách nào", () => {
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);
    expect(screen.queryByText(/ưu đãi học phí/i)).not.toBeInTheDocument();
  });

  it("hiện lý do và khoá ô tích với chính sách không áp được", () => {
    mockPreview.data.discount_policies = [
      policy(),
      policy({
        id: 6,
        name: "Giảm đối tượng ưu tiên",
        selectable: false,
        selected: false,
        applied: false,
        reason: "khong_thuoc_doi_tuong_da_xac_minh",
        reason_text: "Hồ sơ không thuộc đối tượng ưu tiên đã được xác minh",
      }),
    ];
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);

    expect(screen.getByText(/ưu đãi học phí/i)).toBeInTheDocument();
    // Lý do phải HIỆN — "có ưu đãi mà không bấm được" là câu kế toán sẽ hỏi.
    expect(
      screen.getByText(/không thuộc đối tượng ưu tiên đã được xác minh/i)
    ).toBeInTheDocument();

    const disabled = screen.getByLabelText(/giảm đối tượng ưu tiên/i);
    expect(disabled).toBeDisabled();
    expect(screen.getByLabelText(/giảm đăng ký sớm/i)).toBeEnabled();
  });

  it("nói rõ khi ưu đãi đã tích nhưng KHÔNG được áp", () => {
    // is_stackable mặc định FALSE ở CSDL nên tổ hợp này rất dễ gặp: engine áp
    // ưu đãi độc quyền rồi dừng, ô tích thứ hai không có hiệu lực. Im lặng thì
    // tổng tiền bên dưới trông như tính sai.
    mockPreview.data.discount_policies = [
      policy({ id: 4, name: "Ưu đãi độc quyền" }),
      policy({
        id: 9,
        name: "Ưu đãi cộng dồn",
        selected: true,
        applied: false,
        reason: "bi_chan_boi_chinh_sach_khong_cong_don",
        reason_text: "Không cộng dồn được với ưu đãi đã áp trước đó",
      }),
    ];
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);

    expect(screen.getByText(/không được áp/i)).toBeInTheDocument();
    expect(
      screen.getByText(/không cộng dồn được với ưu đãi đã áp trước đó/i)
    ).toBeInTheDocument();
  });

  it("không gửi discount_policy_ids khi người dùng KHÔNG đụng vào ô tích", async () => {
    mockPreview.data.discount_policies = [policy()];
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);
    fireEvent.click(screen.getByRole("button", { name: /^tính học phí$/i }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        admission_profile_id: 42,
        fee_type: "tuition",
        semester_no: 1,
        installment_plan_code: "FULL",
      });
    });
  });

  it("bỏ tích hết thì gửi mảng RỖNG (không áp ưu đãi nào)", async () => {
    mockPreview.data.discount_policies = [policy()];
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);

    fireEvent.click(screen.getByLabelText(/giảm đăng ký sớm/i));
    fireEvent.click(screen.getByRole("button", { name: /^tính học phí$/i }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        admission_profile_id: 42,
        fee_type: "tuition",
        semester_no: 1,
        installment_plan_code: "FULL",
        discount_policy_ids: [],
      });
    });
  });

  it("tích lại một chính sách đã bỏ thì gửi đúng id đó", async () => {
    mockPreview.data.discount_policies = [
      policy({ selected: false }),
      policy({ id: 9, name: "Giảm con em cán bộ", selected: false }),
    ];
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);

    fireEvent.click(screen.getByLabelText(/giảm con em cán bộ/i));
    fireEvent.click(screen.getByRole("button", { name: /^tính học phí$/i }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        admission_profile_id: 42,
        fee_type: "tuition",
        semester_no: 1,
        installment_plan_code: "FULL",
        discount_policy_ids: [9],
      });
    });
  });
});
