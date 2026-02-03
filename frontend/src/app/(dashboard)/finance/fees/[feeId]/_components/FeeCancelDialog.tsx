// src/app/(dashboard)/finance/fees/[feeId]/_components/FeeCancelDialog.tsx
"use client"

import * as React from "react"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { AlertTriangle, Loader2 } from "lucide-react"
import { useCancelFee } from "@/hooks/finance/useFees"
import { toast } from "sonner"

// =============================================================================
// TYPES
// =============================================================================

interface FeeCancelDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  feeId: number
  feeType: string
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * FeeCancelDialog - Confirmation dialog to cancel a fee
 *
 * @example
 * ```tsx
 * <FeeCancelDialog
 *   open={isOpen}
 *   onOpenChange={setIsOpen}
 *   feeId={123}
 *   feeType="Học phí"
 * />
 * ```
 */
export function FeeCancelDialog({
  open,
  onOpenChange,
  feeId,
  feeType,
}: FeeCancelDialogProps) {
  const cancelMutation = useCancelFee()

  const handleCancel = async () => {
    try {
      await cancelMutation.mutateAsync({ feeId, reason: "Hủy theo yêu cầu" })
      toast.success("Đã hủy học phí thành công")
      onOpenChange(false)
    } catch (error) {
      // Error toast is handled by the mutation hook
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-destructive" />
            Xác nhận hủy học phí
          </AlertDialogTitle>
          <AlertDialogDescription className="space-y-2">
            <p>
              Bạn có chắc chắn muốn hủy khoản <strong>{feeType}</strong> này?
            </p>
            <p className="text-destructive font-medium">
              Hành động này không thể hoàn tác. Tất cả hóa đơn liên quan sẽ bị hủy theo.
            </p>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={cancelMutation.isPending}>
            Không, giữ lại
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleCancel}
            disabled={cancelMutation.isPending}
            className="bg-destructive hover:bg-destructive/90"
          >
            {cancelMutation.isPending && (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            )}
            Xác nhận hủy
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export default FeeCancelDialog
