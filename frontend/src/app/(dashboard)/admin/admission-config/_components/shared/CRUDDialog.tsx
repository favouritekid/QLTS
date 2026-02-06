/**
 * CRUDDialog - Reusable Dialog for Create/Edit Forms
 *
 * Provides consistent dialog UI for all CRUD operations
 */

"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";

// ============================================
// TYPES
// ============================================

interface CRUDDialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  isEdit: boolean;
  onSubmit: () => void;
  isSubmitting: boolean;
  children: React.ReactNode;
  submitLabel?: string;
  cancelLabel?: string;
}

// ============================================
// COMPONENT
// ============================================

export function CRUDDialog({
  open,
  onClose,
  title,
  description,
  isEdit,
  onSubmit,
  isSubmitting,
  children,
  submitLabel,
  cancelLabel = "Hủy",
}: CRUDDialogProps) {
  const defaultSubmitLabel = isEdit ? "Cập nhật" : "Thêm mới";

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>

        <div className="space-y-4 py-4">{children}</div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={isSubmitting}
          >
            {cancelLabel}
          </Button>
          <Button
            type="button"
            onClick={onSubmit}
            disabled={isSubmitting}
          >
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {submitLabel || defaultSubmitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
