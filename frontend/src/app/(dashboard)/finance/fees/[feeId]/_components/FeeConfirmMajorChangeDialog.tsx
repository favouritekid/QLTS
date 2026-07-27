// src/app/(dashboard)/finance/fees/[feeId]/_components/FeeConfirmMajorChangeDialog.tsx
"use client"

import * as React from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { ArrowRight, CheckCircle2, Loader2 } from "lucide-react"
import { useConfirmMajorChange } from "@/hooks/finance/useFees"
import { formatVND } from "@/lib/zod/finance"

interface FeeConfirmMajorChangeDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  feeId: number
  fromMajorName: string | null
  toMajorName: string | null
  finalAmount: string
  paidAmount: string
  deltaAmount: string | null
}

/**
 * Kế toán xác nhận học phí đổi ngành đã reprice. Thin-client: hiển thị A→B +
 * số liệu BE trả (không tự tính), xác nhận PUT confirm-major-change. Sau xác
 * nhận: cờ chờ clear, officer tiếp tục (xuất giấy / duyệt).
 *
 * Không có form: reprice đã ghi đúng số tiền (BE CẮT 1) nên đây chỉ là chốt
 * kiểm soát maker-checker, không nhập liệu.
 */
export function FeeConfirmMajorChangeDialog({
  open,
  onOpenChange,
  feeId,
  fromMajorName,
  toMajorName,
  finalAmount,
  paidAmount,
  deltaAmount,
}: FeeConfirmMajorChangeDialogProps) {
  const confirmMutation = useConfirmMajorChange()

  const handleConfirm = async () => {
    try {
      await confirmMutation.mutateAsync({ feeId })
      onOpenChange(false)
    } catch {
      // Error toast handled by mutation hook
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5" />
            Xác nhận đổi ngành
          </DialogTitle>
          <DialogDescription>
            Học phí đã được định giá lại theo ngành mới. Xác nhận để chốt và cho
            phép cán bộ tuyển sinh tiếp tục (xuất giấy báo / duyệt hồ sơ).
          </DialogDescription>
        </DialogHeader>

        {/* A → B */}
        <div className="flex items-center justify-center gap-3 rounded-lg border bg-muted/40 p-3 text-sm">
          <span className="max-w-[40%] truncate text-muted-foreground">
            {fromMajorName ?? "(ngành cũ)"}
          </span>
          <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="max-w-[40%] truncate font-medium">
            {toMajorName ?? "(ngành mới)"}
          </span>
        </div>

        {/* Số liệu tiền (BE-owned) */}
        <dl className="space-y-1.5 text-sm">
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Học phí ngành mới</dt>
            <dd className="font-medium">{formatVND(finalAmount)}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Đã đóng</dt>
            <dd>{formatVND(paidAmount)}</dd>
          </div>
          {deltaAmount != null && (
            <div className="flex justify-between border-t pt-1.5">
              <dt className="text-muted-foreground">Còn phải thu</dt>
              <dd className="font-medium text-amber-700 dark:text-amber-400">
                {formatVND(deltaAmount)}
              </dd>
            </div>
          )}
        </dl>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={confirmMutation.isPending}
          >
            Hủy
          </Button>
          <Button type="button" onClick={handleConfirm} disabled={confirmMutation.isPending}>
            {confirmMutation.isPending && (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
            )}
            Xác nhận đổi ngành
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default FeeConfirmMajorChangeDialog
