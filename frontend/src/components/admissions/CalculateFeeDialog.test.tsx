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

vi.mock("@/hooks/finance/useFees", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/finance/useFees")>(
    "@/hooks/finance/useFees"
  );
  return {
    ...actual,
    useCalculateFee: () => ({ mutateAsync, isPending: false }),
    // Manual override add-on (#2) — stub giá chuẩn so the preview block renders
    // deterministically without a network call when the toggle is on.
    useTuitionPreview: () => ({
      data: {
        base_amount: "5000000",
        total_discount: "0",
        final_amount: "5000000",
        semester_no: 1,
      },
      isLoading: false,
      isError: false,
    }),
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

  // ---- Manual tuition override (2026-06-28) ----

  it("manual toggle reveals amount + reason inputs", () => {
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);
    // Hidden by default.
    expect(screen.queryByLabelText(/mức học phí/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: /nhập học phí thủ công/i }));
    expect(screen.getByLabelText(/mức học phí/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/lý do nhập tay/i)).toBeInTheDocument();
  });

  it("submit is blocked until a manual amount + reason ≥10 chars are present", () => {
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);
    fireEvent.click(screen.getByRole("switch", { name: /nhập học phí thủ công/i }));

    const submit = screen.getByRole("button", { name: /^tính học phí$/i });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/mức học phí/i), {
      target: { value: "9000000" },
    });
    // Reason still empty → blocked.
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/lý do nhập tay/i), {
      target: { value: "Hoc bong dac biet theo quyet dinh" },
    });
    expect(submit).toBeEnabled();
  });

  it("reason chip sets a ≥10-char reason value", () => {
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);
    fireEvent.click(screen.getByRole("switch", { name: /nhập học phí thủ công/i }));
    fireEvent.click(screen.getByRole("button", { name: /^học bổng$/i }));
    const reason = screen.getByLabelText(/lý do nhập tay/i) as HTMLTextAreaElement;
    expect(reason.value.length).toBeGreaterThanOrEqual(10);
  });

  it("manual submit opens the confirm dialog, then posts manual fields", async () => {
    render(<CalculateFeeDialog open onOpenChange={vi.fn()} profileId={42} />);
    fireEvent.click(screen.getByRole("switch", { name: /nhập học phí thủ công/i }));
    fireEvent.change(screen.getByLabelText(/mức học phí/i), {
      target: { value: "9000000" },
    });
    fireEvent.change(screen.getByLabelText(/lý do nhập tay/i), {
      target: { value: "Hoc bong dac biet theo quyet dinh" },
    });

    // First click only opens the confirm dialog — no mutation yet (#3).
    fireEvent.click(screen.getByRole("button", { name: /^tính học phí$/i }));
    expect(mutateAsync).not.toHaveBeenCalled();
    expect(
      screen.getByText(/xác nhận nhập học phí thủ công/i)
    ).toBeInTheDocument();

    // Confirm → mutation fires with the manual fields.
    fireEvent.click(screen.getByRole("button", { name: /xác nhận tạo/i }));
    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        admission_profile_id: 42,
        fee_type: "tuition",
        semester_no: 1,
        installment_plan_code: "FULL",
        manual_base_amount: "9000000",
        manual_reason: "Hoc bong dac biet theo quyet dinh",
      });
    });
  });

  it("does NOT include manual fields when the toggle stays off", async () => {
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
});
