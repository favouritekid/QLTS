"use client"

/**
 * FeeQRTransferDialog — hiển thị mã QR chuyển khoản (VietQR) cho một khoản phí,
 * ngay trong tab "Học phí" của hồ sơ.
 *
 * Vì sao ở đây: officer (tư vấn viên) không được vào module Finance
 * (nav + proxy chặn), nhưng vẫn cần đưa mã QR cho phụ huynh chuyển khoản học
 * phí. Backend đã cấp officer quyền đọc `GET /api/invoices/by-fee/{fee_id}` và
 * `GET /api/invoices/{id}/vietqr`, nên dialog này thuần FE: từ `feeId` resolve
 * hóa đơn còn phải trả rồi tái dùng `InvoiceVietQR`.
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
import { InvoiceVietQR } from "@/components/finance"
import { useInvoicesByFee } from "@/hooks/finance/useInvoices"
import { formatVND } from "@/lib/zod/finance"
import { isInvoicePayable } from "@/types/finance.types"

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
    () => (invoices ?? []).filter(isInvoicePayable),
    [invoices],
  )

  // Đợt người dùng chọn thủ công (null = chưa chọn). Giá trị hiệu lực suy ra
  // THẲNG khi render (đợt đã chọn nếu còn hợp lệ, ngược lại đợt payable đầu) —
  // không auto-select bằng useEffect nên tránh 1-frame trống / uncontrolled-flip
  // và không có state-write-in-effect. State tự mất khi dialog unmount lúc đóng.
  const [manualSelectedId, setManualSelectedId] = React.useState<number | null>(null)
  const selectedId =
    manualSelectedId !== null && payable.some((inv) => inv.id === manualSelectedId)
      ? manualSelectedId
      : (payable[0]?.id ?? null)

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
        ) : selectedId === null ? (
          <EmptyNotice text="Chưa có hóa đơn cần thanh toán. Hóa đơn có thể chưa được phát hành hoặc khoản phí đã thu đủ." />
        ) : (
          <div className="space-y-3">
            {payable.length > 1 && (
              <div className="space-y-1.5">
                <span id="fee-qr-installment-label" className="text-sm text-muted-foreground">
                  Chọn đợt thanh toán
                </span>
                <Select
                  value={String(selectedId)}
                  onValueChange={(v) => setManualSelectedId(Number(v))}
                >
                  <SelectTrigger aria-labelledby="fee-qr-installment-label">
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
            <InvoiceVietQR invoiceId={selectedId} />
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
