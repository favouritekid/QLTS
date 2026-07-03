"use client"

/**
 * InvoiceVietQR — tải payload VietQR của MỘT hóa đơn rồi hiển thị (ảnh QR + số
 * tài khoản + nội dung) kèm trạng thái loading / error / retry.
 *
 * Tách riêng để mọi nơi cần "hiện QR chuyển khoản cho một invoiceId" dùng chung
 * một khối — dialog QR ở workspace Finance (InvoiceQRDialog) lẫn dialog QR theo
 * khoản phí ở tab Học phí của hồ sơ (FeeQRTransferDialog) — thay vì tự dựng lại
 * cặp useInvoiceVietQR + VietQRDisplay.
 */

import { useInvoiceVietQR } from "@/hooks/finance/useInvoices"
import { VietQRDisplay } from "./VietQRDisplay"

interface InvoiceVietQRProps {
  invoiceId: number
}

export function InvoiceVietQR({ invoiceId }: InvoiceVietQRProps) {
  const { data, isLoading, error, refetch } = useInvoiceVietQR(invoiceId)
  return (
    <VietQRDisplay
      data={data}
      isLoading={isLoading}
      error={error}
      onRetry={() => refetch()}
    />
  )
}

export default InvoiceVietQR
