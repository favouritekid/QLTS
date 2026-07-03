"use client"

/**
 * InvoiceVietQR — tải payload VietQR của MỘT hóa đơn rồi hiển thị (ảnh QR + số
 * tài khoản + nội dung) kèm trạng thái loading / error / retry, và nút CHIA SẺ
 * để officer gửi mã QR cho học viên / phụ huynh.
 *
 * Tách riêng để mọi nơi cần "hiện QR chuyển khoản cho một invoiceId" dùng chung
 * một khối — dialog QR ở workspace Finance (InvoiceQRDialog) lẫn dialog QR theo
 * khoản phí ở tab Học phí của hồ sơ (FeeQRTransferDialog) — thay vì tự dựng lại
 * cặp useInvoiceVietQR + VietQRDisplay.
 */

import * as React from "react"
import { Share2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { useInvoiceVietQR } from "@/hooks/finance/useInvoices"
import { renderVietQRCard } from "@/lib/finance/qr-card"
import { formatVND } from "@/lib/zod/finance"
import type { VietQRResponse } from "@/types/finance.types"
import { VietQRDisplay } from "./VietQRDisplay"

interface InvoiceVietQRProps {
  invoiceId: number
}

export function InvoiceVietQR({ invoiceId }: InvoiceVietQRProps) {
  const { data, isLoading, error, refetch } = useInvoiceVietQR(invoiceId)
  return (
    <div className="space-y-3">
      <VietQRDisplay
        data={data}
        isLoading={isLoading}
        error={error}
        onRetry={() => refetch()}
      />
      {data && <ShareQRButton data={data} />}
    </div>
  )
}

/** Caption kèm ảnh QR để học viên có đủ thông tin ngay cả khi không quét được. */
function buildCaption(data: VietQRResponse): string {
  return [
    "Chuyển khoản học phí",
    `Số tiền: ${formatVND(data.amount)}`,
    `STK: ${data.bank_account.account_number} — ${data.bank_account.account_name}`,
    `Nội dung: ${data.content}`,
  ].join("\n")
}

function ShareQRButton({ data }: { data: VietQRResponse }) {
  const [busy, setBusy] = React.useState(false)

  const handleShare = React.useCallback(async () => {
    setBusy(true)
    try {
      // Thẻ QR đầy đủ (QR + số tiền/nội dung/tên TK/số TK/ngân hàng) để học
      // viên tin tưởng khi quét — thay vì ảnh QR "trần".
      const blob = await renderVietQRCard(data)
      const file = new File(
        [blob],
        `vietqr-${data.bank_account.account_number}.png`,
        { type: "image/png" },
      )
      const caption = buildCaption(data)

      // Web Share Level 2 (chia sẻ file): mobile/tablet mở share sheet để gửi
      // thẳng qua Zalo / Messenger / email…
      const canShareFile =
        typeof navigator !== "undefined" &&
        typeof navigator.canShare === "function" &&
        navigator.canShare({ files: [file] })

      if (canShareFile) {
        await navigator.share({
          files: [file],
          title: "Mã QR chuyển khoản học phí",
          text: caption,
        })
        return
      }

      // Fallback (đa số desktop không hỗ trợ chia sẻ file): tải ảnh PNG về máy
      // để officer gửi cho học viên qua Zalo / email.
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = file.name
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      toast.success("Đã tải ảnh mã QR — gửi cho học viên qua Zalo/email")
    } catch (err) {
      // Người dùng bấm huỷ trên share sheet → im lặng, không báo lỗi.
      if ((err as Error)?.name !== "AbortError") {
        toast.error("Không thể chia sẻ mã QR. Vui lòng thử lại.")
      }
    } finally {
      setBusy(false)
    }
  }, [data])

  return (
    <Button
      variant="outline"
      className="w-full"
      onClick={handleShare}
      disabled={busy}
    >
      <Share2 className="mr-2 h-4 w-4" aria-hidden="true" />
      Chia sẻ mã QR cho học viên
    </Button>
  )
}

export default InvoiceVietQR
