// src/app/(dashboard)/finance/invoices/_components/WorkspaceActionDialogs.tsx
/**
 * Single action-dialog host for the "Thu học phí" workspace.
 *
 * Both the spine row AND the FinanceProfileDrawer (and the "Chờ duyệt" queue)
 * raise actions through ONE `WorkspaceDialog` descriptor so every dialog is
 * mounted in one place with one source of state — no duplicated dialog logic
 * across surfaces. Mutations invalidate the workspace list / tab counts / the
 * open collection drawer via the shared invalidation helpers in the hooks (see
 * usePayments/useInvoices/useFees), so the context stays in sync without
 * closing the drawer.
 */

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
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { toast } from "sonner"

import { useVerifyPayment, useRejectPayment } from "@/hooks/finance/usePayments"
import { useInvoiceVietQR } from "@/hooks/finance/useInvoices"
import { VietQRDisplay } from "@/components/finance"

import { PaymentRecordDialog } from "../[invoiceId]/_components/PaymentRecordDialog"
import { InvoiceIssueDialog } from "../[invoiceId]/_components/InvoiceIssueDialog"
import { InvoiceCancelDialog } from "../[invoiceId]/_components/InvoiceCancelDialog"
import { InvoicePenaltyDialog } from "../[invoiceId]/_components/InvoicePenaltyDialog"
import { FeeWaiveDialog } from "../../fees/[feeId]/_components/FeeWaiveDialog"
import { CalculateFeeDialog } from "@/components/admissions/CalculateFeeDialog"

// =============================================================================
// DIALOG DESCRIPTOR
// =============================================================================

/** Minimal payment shape the verify/reject confirm needs (from either view model). */
export interface PaymentReviewTarget {
  id: number
  invoice_id: number
  reference_code: string | null
  amount_formatted: string
  created_by_display: string
}

export type WorkspaceDialog =
  | {
      type: "record"
      invoiceId: number
      feeId: number
      maxAmountFormatted: string
      invoiceNumber: string
    }
  | { type: "issue"; invoiceId: number; feeId: number; invoiceNumber: string }
  | { type: "cancel"; invoiceId: number; feeId: number; invoiceNumber: string }
  | {
      type: "penalty"
      invoiceId: number
      feeId: number
      invoiceNumber: string
      daysOverdue: number
    }
  | { type: "waive"; feeId: number; maxAmount: string; maxAmountFormatted: string }
  | { type: "verify"; payment: PaymentReviewTarget }
  | { type: "reject"; payment: PaymentReviewTarget }
  | { type: "qr"; invoiceId: number; invoiceNumber: string }
  | { type: "calculate"; profileId: number }

interface WorkspaceActionDialogsProps {
  dialog: WorkspaceDialog | null
  onClose: () => void
}

export function WorkspaceActionDialogs({ dialog, onClose }: WorkspaceActionDialogsProps) {
  const handleOpenChange = React.useCallback(
    (open: boolean) => {
      if (!open) onClose()
    },
    [onClose],
  )

  return (
    <>
      {dialog?.type === "record" && (
        <PaymentRecordDialog
          open
          onOpenChange={handleOpenChange}
          invoiceId={dialog.invoiceId}
          feeId={dialog.feeId}
          maxAmount={dialog.maxAmountFormatted}
        />
      )}

      {dialog?.type === "issue" && (
        <InvoiceIssueDialog
          open
          onOpenChange={handleOpenChange}
          invoiceId={dialog.invoiceId}
          invoiceNumber={dialog.invoiceNumber}
          feeId={dialog.feeId}
        />
      )}

      {dialog?.type === "cancel" && (
        <InvoiceCancelDialog
          open
          onOpenChange={handleOpenChange}
          invoiceId={dialog.invoiceId}
          invoiceNumber={dialog.invoiceNumber}
          feeId={dialog.feeId}
        />
      )}

      {dialog?.type === "penalty" && (
        <InvoicePenaltyDialog
          open
          onOpenChange={handleOpenChange}
          invoiceId={dialog.invoiceId}
          invoiceNumber={dialog.invoiceNumber}
          feeId={dialog.feeId}
          daysOverdue={dialog.daysOverdue}
        />
      )}

      {dialog?.type === "waive" && (
        <FeeWaiveDialog
          open
          onOpenChange={handleOpenChange}
          feeId={dialog.feeId}
          maxAmount={dialog.maxAmount}
          maxAmountFormatted={dialog.maxAmountFormatted}
        />
      )}

      {dialog?.type === "calculate" && (
        <CalculateFeeDialog
          open
          onOpenChange={handleOpenChange}
          profileId={dialog.profileId}
        />
      )}

      {(dialog?.type === "verify" || dialog?.type === "reject") && (
        <PaymentReviewDialog
          mode={dialog.type}
          payment={dialog.payment}
          onClose={onClose}
        />
      )}

      {dialog?.type === "qr" && (
        <InvoiceQRDialog
          invoiceId={dialog.invoiceId}
          invoiceNumber={dialog.invoiceNumber}
          onClose={onClose}
        />
      )}
    </>
  )
}

// =============================================================================
// PAYMENT VERIFY / REJECT (maker-checker)
// =============================================================================

function PaymentReviewDialog({
  mode,
  payment,
  onClose,
}: {
  mode: "verify" | "reject"
  payment: PaymentReviewTarget
  onClose: () => void
}) {
  const verifyMutation = useVerifyPayment()
  const rejectMutation = useRejectPayment()
  const [reason, setReason] = React.useState("")
  const isReject = mode === "reject"
  const pending = isReject ? rejectMutation.isPending : verifyMutation.isPending

  const confirm = async () => {
    try {
      if (isReject) {
        if (!reason.trim()) return
        await rejectMutation.mutateAsync({
          paymentId: payment.id,
          invoiceId: payment.invoice_id,
          data: { rejection_reason: reason.trim() },
        })
        toast.success("Đã từ chối thanh toán")
      } else {
        await verifyMutation.mutateAsync({
          paymentId: payment.id,
          invoiceId: payment.invoice_id,
        })
        toast.success("Đã xác minh thanh toán")
      }
      onClose()
    } catch {
      // toast handled by the mutation hook
    }
  }

  return (
    <AlertDialog open onOpenChange={(o) => !o && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {isReject ? "Từ chối thanh toán" : "Xác minh thanh toán"}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {isReject
              ? "Vui lòng nhập lý do từ chối. Người tạo sẽ được thông báo."
              : "Bạn có chắc chắn muốn xác minh thanh toán này?"}
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-2 py-2 text-sm">
          <div className="flex justify-between gap-3">
            <span className="text-muted-foreground">Mã tham chiếu</span>
            <span className="font-medium">{payment.reference_code || `#${payment.id}`}</span>
          </div>
          <div className="flex justify-between gap-3">
            <span className="text-muted-foreground">Số tiền</span>
            <span className="font-medium tabular-nums">{payment.amount_formatted}</span>
          </div>
          <div className="flex justify-between gap-3">
            <span className="text-muted-foreground">Người tạo</span>
            <span className="min-w-0 truncate">{payment.created_by_display}</span>
          </div>
        </div>

        {isReject && (
          <div className="space-y-2">
            <Label htmlFor="ws-reject-reason">
              Lý do từ chối <span className="text-destructive">*</span>
            </Label>
            <Textarea
              id="ws-reject-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Nhập lý do từ chối…"
              rows={3}
              autoFocus
            />
          </div>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Hủy</AlertDialogCancel>
          <AlertDialogAction
            onClick={(e) => {
              // Keep the dialog open until the mutation resolves (manual close).
              e.preventDefault()
              confirm()
            }}
            disabled={pending || (isReject && !reason.trim())}
            className={
              isReject
                ? "bg-destructive hover:bg-destructive/90"
                : "bg-success-600 hover:bg-success-700"
            }
          >
            {pending ? "Đang xử lý…" : isReject ? "Từ chối" : "Xác minh"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

// =============================================================================
// VIETQR (read-only transfer info)
// =============================================================================

function InvoiceQRDialog({
  invoiceId,
  invoiceNumber,
  onClose,
}: {
  invoiceId: number
  invoiceNumber: string
  onClose: () => void
}) {
  const { data, isLoading, error, refetch } = useInvoiceVietQR(invoiceId)

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Chuyển khoản — {invoiceNumber}</DialogTitle>
          <DialogDescription>
            Quét mã hoặc sao chép thông tin để chuyển khoản học phí.
          </DialogDescription>
        </DialogHeader>
        <VietQRDisplay
          data={data}
          isLoading={isLoading}
          error={error}
          onRetry={() => refetch()}
        />
      </DialogContent>
    </Dialog>
  )
}
