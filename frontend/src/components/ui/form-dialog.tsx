"use client";

import { useState, createContext, useContext, useCallback } from "react";
import { Dialog } from "@/components/ui/dialog";
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

/**
 * Context to provide requestClose function to dialog children
 */
interface FormDialogContextValue {
  /** Request to close the dialog (will show confirmation if dirty) */
  requestClose: () => void;
}

const FormDialogContext = createContext<FormDialogContextValue | null>(null);

/**
 * Hook to access FormDialog's requestClose function
 * Use this in Cancel buttons instead of calling onOpenChange directly
 */
export function useFormDialogClose() {
  const context = useContext(FormDialogContext);
  if (!context) {
    throw new Error("useFormDialogClose must be used within FormDialog");
  }
  return context.requestClose;
}

/**
 * FormDialog - Dialog wrapper with unsaved changes confirmation
 *
 * Prevents accidental data loss by intercepting close attempts
 * when form has unsaved changes (isDirty state).
 *
 * Features:
 * - Intercepts all close actions: overlay click, X button, ESC key, Cancel button
 * - Shows AlertDialog confirmation when form is dirty
 * - Provides useFormDialogClose() hook for Cancel buttons
 * - Semantic UI with AlertDialog for warnings
 *
 * @example
 * ```tsx
 * const { formState: { isDirty } } = useForm();
 *
 * <FormDialog open={open} onOpenChange={setOpen} isDirty={isDirty}>
 *   <DialogContent>
 *     <Form>
 *       <CancelButton /> // Uses useFormDialogClose() hook
 *     </Form>
 *   </DialogContent>
 * </FormDialog>
 * ```
 */
interface FormDialogProps extends React.ComponentProps<typeof Dialog> {
  /** Whether the form has unsaved changes */
  isDirty: boolean;
  children: React.ReactNode;
}

export function FormDialog({
  open,
  onOpenChange,
  isDirty,
  children,
  ...props
}: FormDialogProps) {
  const [showConfirm, setShowConfirm] = useState(false);

  const handleOpenChange = useCallback((newOpen: boolean) => {
    // If attempting to close (newOpen = false) AND form is dirty
    if (!newOpen && isDirty) {
      setShowConfirm(true); // Intercept and show confirmation
    } else {
      // If opening OR form is clean -> allow action
      onOpenChange?.(newOpen);
    }
  }, [isDirty, onOpenChange]);

  const handleConfirmClose = useCallback(() => {
    setShowConfirm(false);
    onOpenChange?.(false); // Actually close the main dialog
  }, [onOpenChange]);

  // Provide requestClose function via context
  const requestClose = useCallback(() => {
    handleOpenChange(false);
  }, [handleOpenChange]);

  return (
    <FormDialogContext.Provider value={{ requestClose }}>
      <Dialog open={open} onOpenChange={handleOpenChange} {...props}>
        {children}
      </Dialog>

      {/* AlertDialog for confirmation (semantic for warnings) */}
      <AlertDialog open={showConfirm} onOpenChange={setShowConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Bạn có chắc chắn muốn thoát?</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có những thay đổi chưa được lưu. Nếu thoát, dữ liệu này sẽ bị
              mất vĩnh viễn.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Ở lại chỉnh sửa</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmClose}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Thoát và Hủy thay đổi
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </FormDialogContext.Provider>
  );
}
