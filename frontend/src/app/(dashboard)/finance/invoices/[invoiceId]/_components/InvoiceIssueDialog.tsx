// src/app/(dashboard)/finance/invoices/[invoiceId]/_components/InvoiceIssueDialog.tsx
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
import { FileText, Loader2 } from "lucide-react"
import { useIssueInvoice } from "@/hooks/finance/useInvoices"
import { toast } from "sonner"

// =============================================================================
// TYPES
// =============================================================================

interface InvoiceIssueDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  invoiceId: number
  invoiceNumber: string
  feeId: number
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * InvoiceIssueDialog - Confirmation dialog to issue an invoice
 *
 * Changes invoice status from "draft" to "issued".
 */
export function InvoiceIssueDialog({
  open,
  onOpenChange,
  invoiceId,
  invoiceNumber,
  feeId,
}: InvoiceIssueDialogProps) {
  const issueMutation = useIssueInvoice()

  const handleIssue = async () => {
    try {
      await issueMutation.mutateAsync({ invoiceId, feeId })
      toast.success("Đã xuất hóa đơn thành công")
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
            <FileText className="h-5 w-5" />
            Xuất hóa đơn
          </AlertDialogTitle>
          <AlertDialogDescription className="space-y-2">
            {/* Description renders a <p>; block spans avoid <p>-in-<p>. */}
            <span className="block">
              Bạn có chắc chắn muốn xuất hóa đơn <strong className="font-mono">{invoiceNumber}</strong>?
            </span>
            <span className="block">
              Sau khi xuất, hóa đơn sẽ chuyển sang trạng thái &quot;Đã xuất&quot; và có thể ghi nhận thanh toán.
            </span>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={issueMutation.isPending}>
            Hủy
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleIssue}
            disabled={issueMutation.isPending}
          >
            {issueMutation.isPending && (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            )}
            Xuất hóa đơn
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export default InvoiceIssueDialog
