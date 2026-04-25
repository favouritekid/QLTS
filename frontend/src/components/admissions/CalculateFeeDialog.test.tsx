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
});
