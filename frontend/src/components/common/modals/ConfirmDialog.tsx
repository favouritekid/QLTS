// src/components/common/modals/ConfirmDialog.tsx
"use client";

import * as React from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
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
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

export type ConfirmDialogVariant = "default" | "destructive";

export interface ConfirmDialogProps {
  /** Whether the dialog is open */
  open: boolean;
  /** Callback when open state changes */
  onOpenChange: (open: boolean) => void;
  /** Dialog title */
  title: string;
  /** Dialog description */
  description?: string;
  /** Confirm button text */
  confirmText?: string;
  /** Cancel button text */
  cancelText?: string;
  /** Callback when confirm is clicked */
  onConfirm: () => Promise<void> | void;
  /** Callback when cancel is clicked */
  onCancel?: () => void;
  /** Visual variant */
  variant?: ConfirmDialogVariant;
  /** Show warning icon */
  showIcon?: boolean;
  /** Custom icon */
  icon?: React.ReactNode;
  /** Loading state */
  isLoading?: boolean;
  /** Disable confirm button */
  disabled?: boolean;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmText = "Xac nhan",
  cancelText = "Huy",
  onConfirm,
  onCancel,
  variant = "default",
  showIcon = true,
  icon,
  isLoading = false,
  disabled = false,
}: ConfirmDialogProps) {
  const [loading, setLoading] = React.useState(false);

  const actualLoading = isLoading || loading;

  // Handle confirm click
  const handleConfirm = React.useCallback(async () => {
    try {
      setLoading(true);
      await onConfirm();
      onOpenChange(false);
    } catch (error) {
      // Error should be handled by the caller
      console.error("Confirm dialog error:", error);
    } finally {
      setLoading(false);
    }
  }, [onConfirm, onOpenChange]);

  // Handle cancel click
  const handleCancel = React.useCallback(() => {
    if (actualLoading) return;
    onCancel?.();
    onOpenChange(false);
  }, [onCancel, onOpenChange, actualLoading]);

  // Determine icon
  const displayIcon = icon || (
    <AlertTriangle
      className={cn(
        "h-5 w-5",
        variant === "destructive" ? "text-destructive" : "text-yellow-500"
      )}
    />
  );

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            {showIcon && displayIcon}
            {title}
          </AlertDialogTitle>
          {description && (
            <AlertDialogDescription>{description}</AlertDialogDescription>
          )}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel
            onClick={handleCancel}
            disabled={actualLoading}
          >
            {cancelText}
          </AlertDialogCancel>
          <AlertDialogAction asChild>
            <Button
              variant={variant === "destructive" ? "destructive" : "default"}
              onClick={handleConfirm}
              disabled={disabled || actualLoading}
            >
              {actualLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {confirmText}
            </Button>
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export default ConfirmDialog;
