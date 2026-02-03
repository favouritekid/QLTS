// src/app/(dashboard)/finance/fees/[feeId]/_components/FeeRecalculateDialog.tsx
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
import { RefreshCw, Loader2, AlertTriangle } from "lucide-react"
import { useRecalculateFee } from "@/hooks/finance/useFees"
import { toast } from "sonner"

// =============================================================================
// TYPES
// =============================================================================

interface FeeRecalculateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  feeId: number
  feeType: string
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * FeeRecalculateDialog - Confirmation dialog to recalculate a fee
 *
 * Recalculates the fee based on current discount policies.
 * This will regenerate all invoices.
 *
 * @example
 * ```tsx
 * <FeeRecalculateDialog
 *   open={isOpen}
 *   onOpenChange={setIsOpen}
 *   feeId={123}
 *   feeType="Học phí"
 * />
 * ```
 */
export function FeeRecalculateDialog({
  open,
  onOpenChange,
  feeId,
  feeType,
}: FeeRecalculateDialogProps) {
  const recalculateMutation = useRecalculateFee()

  const handleRecalculate = async () => {
    try {
      await recalculateMutation.mutateAsync(feeId)
      toast.success("Đã tính lại phí thành công")
      onOpenChange(false)
    } catch (error) {
      // Error handled by mutation hook
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <RefreshCw className="h-5 w-5" />
            Tính lại học phí
          </AlertDialogTitle>
          <AlertDialogDescription className="space-y-3">
            <p>
              Bạn có chắc chắn muốn tính lại khoản <strong>{feeType}</strong> này?
            </p>
            <div className="bg-warning-50 dark:bg-warning-950/30 border border-warning-200 dark:border-warning-800 rounded-lg p-3">
              <div className="flex gap-2">
                <AlertTriangle className="h-5 w-5 text-warning-600 shrink-0 mt-0.5" />
                <div className="text-sm text-warning-800 dark:text-warning-200">
                  <p className="font-medium">Lưu ý quan trọng:</p>
                  <ul className="list-disc list-inside mt-1 space-y-1">
                    <li>Hệ thống sẽ tính lại dựa trên chính sách giảm giá hiện tại</li>
                    <li>Các hóa đơn chưa thanh toán sẽ được tạo lại</li>
                    <li>Số tiền có thể thay đổi so với ban đầu</li>
                  </ul>
                </div>
              </div>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={recalculateMutation.isPending}>
            Hủy
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleRecalculate}
            disabled={recalculateMutation.isPending}
          >
            {recalculateMutation.isPending && (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            )}
            Tính lại
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export default FeeRecalculateDialog
