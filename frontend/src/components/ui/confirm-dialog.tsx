// src/components/ui/confirm-dialog.tsx
/**
 * @deprecated Use `@/components/common/modals/ConfirmDialog` instead.
 * This file re-exports from the canonical location for backwards compatibility.
 *
 * Migration:
 * - import { ConfirmDialog } from "@/components/ui/confirm-dialog";
 * + import { ConfirmDialog } from "@/components/common/modals/ConfirmDialog";
 */

export {
  ConfirmDialog,
  type ConfirmDialogProps,
  type ConfirmDialogVariant,
} from "@/components/common/modals/ConfirmDialog";
