"use client"

/**
 * FeeQRTransferDialog — hiển thị mã QR chuyển khoản (VietQR) cho một khoản phí,
 * ngay trong tab "Học phí" của hồ sơ.
 *
 * Vì sao ở đây: officer (tư vấn viên) không được vào module Finance
 * (nav + proxy chặn), nhưng vẫn cần đưa mã QR cho phụ huynh chuyển khoản học
 * phí. Backend đã cấp officer quyền đọc `GET /api/invoices/by-fee/{fee_id}` và
 * `GET /api/invoices/{id}/vietqr`, nên dialog này thuần FE: từ `feeId` resolve
 * hóa đơn còn phải trả rồi tái dùng `VietQRDisplay`.
 *
 * QR chỉ là thông tin chuyển khoản read-only (KHÔNG phải thao tác ghi nhận
 * thanh toán) nên không gate theo role — mọi ai xem được tab đều dùng được.
 */

import * as React from "react"
import { AlertTriangle } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { VietQRDisplay } from "@/components/finance"
import { useInvoicesByFee, useInvoiceVietQR } from "@/hooks/finance/useInvoices"
import { formatVND } from "@/lib/zod/finance"
import type { Invoice } from "@/types/finance.types"

// Mirror backend PAYABLE_INVOICE_STATUSES — chỉ hóa đơn đã phát hành và còn nợ
// mới sinh được VietQR (BE cũng chặn draft/cancelled/paid ở endpoint /vietqr).
const PAYABLE_STATUSES: ReadonlyArray<Invoice["status"]> = ["issued", "partial", "overdue"]

function isPayable(invoice: Invoice): boolean {
  return (
    PAYABLE_STATUSES.includes(invoice.status) &&
    parseFloat(invoice.remaining_amount) > 0
  )
}

interface FeeQRTransferDialogProps {
  feeId: number
  /** Nhãn khoản phí (ví dụ "Học phí — HK1") hiển thị trong mô tả dialog. */
  feeLabel: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function FeeQRTransferDialog({
  feeId,
  feeLabel,
  open,
  onOpenChange,
}: FeeQRTransferDialogProps) {
  const {
    data: invoices,
    isLoading: invoicesLoading,
    error: invoicesError,
  } = useInvoicesByFee(feeId, { enabled: open })

  const payable = React.useMemo(
    () => (invoices ?? []).filter(isPayable),
    [invoices],
  )

  // Đợt đang chọn. Mặc định đợt payable đầu tiên; reset khi đóng dialog hoặc khi
  // tập hóa đơn đổi (mở lại cho khoản phí khác).
  const [selectedId, setSelectedId] = React.useState<number | null>(null)
  React.useEffect(() => {
    if (!open) {
      setSelectedId(null)
      return
    }
    if (selectedId === null || !payable.some((inv) => inv.id === selectedId)) {
      setSelectedId(payable[0]?.id ?? null)
    }
  }, [open, payable, selectedId])

  const {
    data: vietqr,
    isLoading: vietqrLoading,
    error: vietqrError,
    refetch: refetchVietQR,
  } = useInvoiceVietQR(selectedId ?? 0, { enabled: open && !!selectedId })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Mã QR chuyển khoản</DialogTitle>
          <DialogDescription>
            {feeLabel} — quét mã hoặc sao chép thông tin để phụ huynh chuyển khoản học phí.
          </DialogDescription>
        </DialogHeader>

        {invoicesLoading ? (
          <div className="space-y-3">
            <Skeleton className="mx-auto h-44 w-44 rounded-md" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
          </div>
        ) : invoicesError ? (
          <EmptyNotice text="Không thể tải hóa đơn của khoản phí này. Vui lòng thử lại." />
        ) : payable.length === 0 ? (
          <EmptyNotice text="Chưa có hóa đơn cần thanh toán. Hóa đơn có thể chưa được phát hành hoặc khoản phí đã thu đủ." />
        ) : (
          <div className="space-y-3">
            {payable.length > 1 && (
              <div className="space-y-1.5">
                <span className="text-sm text-muted-foreground">Chọn đợt thanh toán</span>
                <Select
                  value={selectedId ? String(selectedId) : undefined}
                  onValueChange={(v) => setSelectedId(Number(v))}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Chọn đợt..." />
                  </SelectTrigger>
                  <SelectContent>
                    {payable.map((inv) => (
                      <SelectItem key={inv.id} value={String(inv.id)}>
                        Đợt {inv.installment_no} — còn {formatVND(inv.remaining_amount)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <VietQRDisplay
              data={vietqr}
              isLoading={vietqrLoading}
              error={vietqrError}
              onRetry={() => refetchVietQR()}
            />
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function EmptyNotice({ text }: { text: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-dashed p-4 text-sm text-muted-foreground">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <p>{text}</p>
    </div>
  )
}

export default FeeQRTransferDialog
