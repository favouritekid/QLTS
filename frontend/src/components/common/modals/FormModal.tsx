// src/components/common/modals/FormModal.tsx
"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

export interface FormModalProps {
  /** Whether the modal is open */
  open: boolean;
  /** Callback when open state changes */
  onOpenChange: (open: boolean) => void;
  /** Modal title */
  title: string;
  /** Modal description */
  description?: string;
  /** Form content */
  children: React.ReactNode;
  /** Save button text */
  saveText?: string;
  /** Cancel button text */
  cancelText?: string;
  /** Callback when save is clicked */
  onSave?: () => Promise<void> | void;
  /** Callback when cancel is clicked */
  onCancel?: () => void;
  /** Loading state */
  isLoading?: boolean;
  /** Disable save button */
  disabled?: boolean;
  /** Hide footer (for custom form buttons) */
  hideFooter?: boolean;
  /** Modal size */
  size?: "sm" | "md" | "lg" | "xl" | "full";
  /** Additional content class name */
  contentClassName?: string;
}

// =============================================================================
// SIZE MAPPING
// =============================================================================

const SIZE_CLASSES = {
  sm: "sm:max-w-[425px]",
  md: "sm:max-w-[550px]",
  lg: "sm:max-w-[700px]",
  xl: "sm:max-w-[900px]",
  full: "sm:max-w-[90vw]",
};

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function FormModal({
  open,
  onOpenChange,
  title,
  description,
  children,
  saveText = "Luu",
  cancelText = "Huy",
  onSave,
  onCancel,
  isLoading = false,
  disabled = false,
  hideFooter = false,
  size = "md",
  contentClassName,
}: FormModalProps) {
  // Handle save click
  const handleSave = React.useCallback(async () => {
    if (onSave) {
      await onSave();
    }
  }, [onSave]);

  // Handle cancel click
  const handleCancel = React.useCallback(() => {
    if (isLoading) return;
    onCancel?.();
    onOpenChange(false);
  }, [onCancel, onOpenChange, isLoading]);

  // Handle keyboard events
  const handleKeyDown = React.useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape" && !isLoading) {
        handleCancel();
      }
    },
    [handleCancel, isLoading]
  );

  return (
    <Dialog open={open} onOpenChange={isLoading ? undefined : onOpenChange}>
      <DialogContent
        className={cn(SIZE_CLASSES[size], contentClassName)}
        onKeyDown={handleKeyDown}
        onInteractOutside={(e) => {
          if (isLoading) {
            e.preventDefault();
          }
        }}
      >
        {/* Loading overlay */}
        {isLoading && (
          <div className="absolute inset-0 bg-background/80 flex items-center justify-center z-50 rounded-lg">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        )}

        {/* Header */}
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && (
            <DialogDescription>{description}</DialogDescription>
          )}
        </DialogHeader>

        {/* Content */}
        <div className="py-4">{children}</div>

        {/* Footer */}
        {!hideFooter && (
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={handleCancel}
              disabled={isLoading}
            >
              {cancelText}
            </Button>
            {onSave && (
              <Button
                type="button"
                onClick={handleSave}
                disabled={disabled || isLoading}
              >
                {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {saveText}
              </Button>
            )}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default FormModal;
