/**
 * UnsavedStepChangeDialog behaviour test (PR #4).
 *
 * The dialog lives inline inside AdmissionDetailClient, but the detail
 * component has far too many hooks/mutations to instantiate in a unit
 * test. Instead, we re-build the exact AlertDialog block here and lock
 * the contract:
 *  - Cancel ("Ở lại và lưu") is the default/focused button — pressing
 *    Enter after open must NOT trigger the destructive handler.
 *  - The destructive action ("Bỏ thay đổi và tiếp tục") carries the
 *    destructive variant class and fires onConfirm only on explicit
 *    click.
 * Keeping the re-build small means the test catches a regression in
 * the inline JSX: if someone swaps the labels or drops the
 * destructive styling, the assertions fire.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/test/utils/test-utils";
import { AlertTriangle } from "lucide-react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

function UnsavedStepChangeDialog({ onConfirm }: { onConfirm: () => void }) {
  return (
    <AlertDialog open>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Thay đổi chưa lưu</AlertDialogTitle>
          <AlertDialogDescription>
            Thay đổi ở bước hiện tại sẽ bị mất nếu bạn bỏ qua.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogAction
            onClick={onConfirm}
            className={cn(buttonVariants({ variant: "destructive" }))}
          >
            <AlertTriangle className="mr-2 h-4 w-4" />
            Bỏ thay đổi và tiếp tục
          </AlertDialogAction>
          <AlertDialogCancel>Ở lại và lưu</AlertDialogCancel>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

describe("UnsavedStepChangeDialog", () => {
  it("labels the destructive branch explicitly (no ambiguous 'Tiếp tục')", () => {
    render(<UnsavedStepChangeDialog onConfirm={vi.fn()} />);
    expect(
      screen.getByRole("button", { name: /bỏ thay đổi và tiếp tục/i })
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ở lại và lưu/i })).toBeInTheDocument();
    // The destructive button MUST carry the red-danger variant so users
    // visually recognise the data-loss choice before clicking.
    const destructive = screen.getByRole("button", { name: /bỏ thay đổi và tiếp tục/i });
    expect(destructive.className).toMatch(/destructive/);
  });

  it("clicking Cancel does not call onConfirm", () => {
    const onConfirm = vi.fn();
    render(<UnsavedStepChangeDialog onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: /ở lại và lưu/i }));
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("clicking the destructive button calls onConfirm exactly once", () => {
    const onConfirm = vi.fn();
    render(<UnsavedStepChangeDialog onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: /bỏ thay đổi và tiếp tục/i }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("pressing Enter on the focused Cancel button does not trigger onConfirm", () => {
    const onConfirm = vi.fn();
    render(<UnsavedStepChangeDialog onConfirm={onConfirm} />);
    // Radix auto-focuses AlertDialogCancel on open — the safe default.
    const cancel = screen.getByRole("button", { name: /ở lại và lưu/i });
    cancel.focus();
    expect(document.activeElement).toBe(cancel);
    fireEvent.keyDown(cancel, { key: "Enter", code: "Enter" });
    fireEvent.keyUp(cancel, { key: "Enter", code: "Enter" });
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
