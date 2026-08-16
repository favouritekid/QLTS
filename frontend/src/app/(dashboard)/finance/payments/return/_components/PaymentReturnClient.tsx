// src/app/(dashboard)/finance/payments/return/_components/PaymentReturnClient.tsx
"use client"

import * as React from "react"
import { useRouter, useSearchParams } from "next/navigation"
import Link from "next/link"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  Loader2,
  ArrowLeft,
  Receipt,
  RefreshCw,
} from "lucide-react"
import { usePaymentIntent } from "@/hooks/finance/usePayments"
import { AmountDisplay } from "@/components/finance"
import { cn } from "@/lib/utils"

// =============================================================================
// TYPES
// =============================================================================

type PaymentStatus = "success" | "failed" | "pending" | "cancelled" | "expired" | "unknown"

interface PaymentResult {
  status: PaymentStatus
  title: string
  description: string
  icon: React.ReactNode
  iconClass: string
  bgClass: string
  borderClass: string
}

// =============================================================================
// STATUS CONFIG
// =============================================================================

const STATUS_CONFIG: Record<PaymentStatus, Omit<PaymentResult, "status">> = {
  success: {
    title: "Thanh toán thành công",
    description: "Giao dịch đã được hoàn tất. Cảm ơn bạn đã thanh toán.",
    icon: <CheckCircle className="h-16 w-16" />,
    iconClass: "text-success-500",
    bgClass: "bg-success-50/50 dark:bg-success-950/20",
    borderClass: "border-success-500/50",
  },
  failed: {
    title: "Thanh toán thất bại",
    description: "Giao dịch không thành công. Vui lòng thử lại hoặc chọn phương thức khác.",
    icon: <XCircle className="h-16 w-16" />,
    iconClass: "text-destructive",
    bgClass: "bg-destructive/5",
    borderClass: "border-destructive/50",
  },
  pending: {
    title: "Đang xử lý",
    description: "Giao dịch đang được xử lý. Vui lòng đợi...",
    icon: <Loader2 className="h-16 w-16 animate-spin" />,
    iconClass: "text-primary",
    bgClass: "bg-primary/5",
    borderClass: "border-primary/50",
  },
  cancelled: {
    title: "Đã hủy",
    description: "Bạn đã hủy giao dịch thanh toán.",
    icon: <XCircle className="h-16 w-16" />,
    iconClass: "text-muted-foreground",
    bgClass: "bg-muted/50",
    borderClass: "border-muted",
  },
  expired: {
    title: "Giao dịch hết hạn",
    description: "Phiên thanh toán đã hết hạn. Vui lòng thử lại.",
    icon: <AlertTriangle className="h-16 w-16" />,
    iconClass: "text-warning-500",
    bgClass: "bg-warning-50/50 dark:bg-warning-950/20",
    borderClass: "border-warning-500/50",
  },
  unknown: {
    title: "Không xác định",
    description: "Không thể xác định trạng thái giao dịch. Vui lòng kiểm tra lại hóa đơn.",
    icon: <AlertTriangle className="h-16 w-16" />,
    iconClass: "text-muted-foreground",
    bgClass: "bg-muted/50",
    borderClass: "border-muted",
  },
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Trạng thái thanh toán CHỈ được lấy từ máy chủ.
 *
 * ⚠️ Bản trước ưu tiên ngược: `// Priority: query param > intent status`. Tham
 * số `?status=` nằm trong URL nên người xem sửa được, và nó THẮNG trạng thái mà
 * máy chủ đã xác minh. Mở
 * `/finance/payments/return?intent_id=<intent PENDING có thật>&status=success`
 * là thấy thẻ xanh "Thanh toán thành công" kèm SỐ TIỀN THẬT lấy từ máy chủ —
 * đủ để chụp màn hình làm "bằng chứng đã thanh toán".
 *
 * Máy chủ có sự thật và đã xác minh nó: `payment_intent_service.process_callback`
 * kiểm chữ ký cổng rồi mới đặt `intent.status` và tạo phiếu thu. Giao diện không
 * có lý do gì để tin URL hơn thứ ấy.
 *
 * Còn tham số `?status=` thì KHÔNG AI đặt trong luồng thật: `return_url` gửi cho
 * cổng là `{origin}/finance/payments/return` trần, cổng chỉ nối thêm `vnp_*` của
 * nó. Bỏ nhánh này vì vậy không làm hỏng luồng nào đang chạy.
 */
function parseStatus(intentStatus?: string): PaymentStatus {
  if (intentStatus === "completed") return "success"
  if (intentStatus === "failed") return "failed"
  if (intentStatus === "cancelled") return "cancelled"
  if (intentStatus === "expired") return "expired"
  if (intentStatus === "pending" || intentStatus === "created") return "pending"
  return "unknown"
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

/**
 * PaymentReturnClient - Handles payment gateway return
 *
 * Expected query params:
 * - status: success | failed | cancelled | pending
 * - intent_id: PaymentIntent ID (optional)
 * - invoice_id: Invoice ID (optional)
 * - reference: Gateway reference (optional)
 * - error: Error message (optional)
 */
export function PaymentReturnClient() {
  const router = useRouter()
  const searchParams = useSearchParams()

  // Parse query params. `status` KHÔNG được đọc: xem `parseStatus`.
  const intentId = searchParams.get("intent_id")
  const errorMessage = searchParams.get("error")
  const reference = searchParams.get("reference") || searchParams.get("vnp_TxnRef")

  // Fetch payment intent if ID provided
  const {
    data: intent,
    isLoading: intentLoading,
    error: intentError,
  } = usePaymentIntent(intentId ? parseInt(intentId) : 0, {
    enabled: !!intentId,
  })

  // Đã xác minh = máy chủ trả về intent. Tải lỗi, 404, hoặc không có
  // `intent_id` đều là CHƯA xác minh — và chưa xác minh thì không được khẳng
  // định điều gì, kể cả khi URL nói "success".
  const daXacMinh = !!intentId && !intentError && !!intent

  const finalStatus = React.useMemo(() => {
    return daXacMinh ? parseStatus(intent?.status) : "unknown"
  }, [daXacMinh, intent?.status])

  // Get status config
  const config = STATUS_CONFIG[finalStatus]

  // Get invoice ID from intent if not in params
  // Đích của hành động cũng phải do MÁY CHỦ quyết, không phải URL.
  //
  // Bản trước: `invoiceId || intent?.invoice_id?.toString()` — tham số URL
  // thắng. Hệ quả: với một intent đã xác minh, thêm `&invoice_id=999` là đổi
  // đích của "Xem hoá đơn"/"Thử lại" sang hoá đơn KHÁC hoá đơn thật của intent;
  // và khi chưa xác minh được gì, chỉ cần `invoice_id` trong URL là hai nút ấy
  // vẫn mọc. Trạng thái đã lấy từ máy chủ mà đích hành động vẫn lấy từ URL thì
  // hàng rào mới đóng được một nửa.
  const targetInvoiceId =
    daXacMinh && intent ? intent.invoice_id.toString() : undefined

  // Loading state
  if (intentId && intentLoading) {
    return (
      <div className="h-full flex flex-col items-center justify-center p-4 sm:p-6">
        <Loader2 className="h-16 w-16 animate-spin text-primary mb-6" />
        <p className="text-lg font-medium">Đang xác nhận thanh toán...</p>
        <p className="text-sm text-muted-foreground mt-1">
          Vui lòng không đóng trang này
        </p>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col items-center justify-center p-4 sm:p-6">
      <Card
        className={cn(
          "w-full max-w-md text-center",
          config.bgClass,
          config.borderClass
        )}
      >
        <CardHeader className="pb-4">
          <div className={cn("mx-auto mb-4", config.iconClass)}>{config.icon}</div>
          <CardTitle className="text-2xl">{config.title}</CardTitle>
          <CardDescription className="text-base">{config.description}</CardDescription>
        </CardHeader>

        <CardContent className="space-y-4">
          {/* Chưa xác minh được: nói thẳng, đừng để người đọc tự suy */}
          {!daXacMinh && (
            <div
              data-testid="canh-bao-chua-xac-minh"
              className="p-3 rounded-lg bg-muted text-muted-foreground text-sm text-left"
            >
              <p className="font-medium">Chưa đối chiếu được với hệ thống</p>
              <p>
                {intentId
                  ? "Không đọc được giao dịch từ máy chủ. Trạng thái hiển thị ở đây không phải kết quả đã xác minh."
                  : "Đường dẫn không kèm mã giao dịch, nên không có gì để đối chiếu. Hãy mở hoá đơn để xem trạng thái thật."}
              </p>
            </div>
          )}

          {/* Error message — chuỗi này đến TỪ URL, không phải từ máy chủ */}
          {errorMessage && (
            <div className="p-3 rounded-lg bg-destructive/10 text-destructive text-sm">
              <p className="font-medium">Chi tiết lỗi (theo đường dẫn, chưa đối chiếu):</p>
              <p>{decodeURIComponent(errorMessage)}</p>
            </div>
          )}

          {/* Transaction details */}
          {(reference || intent) && (
            <div className="space-y-2 text-sm text-left bg-background/50 p-3 rounded-lg">
              {reference && (
                <div className="flex justify-between">
                  {/* `reference` lấy từ URL ⇒ chưa đối chiếu. `gateway_ref` bên
                      dưới mới là giá trị máy chủ ghi nhận. */}
                  <span className="text-muted-foreground">Mã giao dịch (chưa đối chiếu):</span>
                  <span className="font-mono font-medium">{reference}</span>
                </div>
              )}
              {intent?.amount && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Số tiền:</span>
                  <AmountDisplay amount={intent.amount} size="sm" />
                </div>
              )}
              {intent?.gateway_ref && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Mã GD cổng:</span>
                  <span className="font-mono text-xs">{intent.gateway_ref}</span>
                </div>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex flex-col sm:flex-row gap-2 pt-4">
            {targetInvoiceId && (
              <Button variant="outline" className="flex-1" asChild>
                <Link href={`/finance/invoices/${targetInvoiceId}`}>
                  <Receipt className="h-4 w-4 mr-2" />
                  Xem hóa đơn
                </Link>
              </Button>
            )}
            {finalStatus === "failed" && targetInvoiceId && (
              <Button className="flex-1" asChild>
                <Link href={`/finance/invoices/${targetInvoiceId}?action=online-payment`}>
                  <RefreshCw className="h-4 w-4 mr-2" />
                  Thử lại
                </Link>
              </Button>
            )}
            {!targetInvoiceId && (
              <Button variant="outline" className="flex-1" asChild>
                <Link href="/finance">
                  <ArrowLeft className="h-4 w-4 mr-2" />
                  Về Tài chính
                </Link>
              </Button>
            )}
          </div>

          {/* Dashboard link */}
          <div className="pt-2">
            <Button variant="link" size="sm" asChild>
              <Link href="/finance">
                <ArrowLeft className="h-4 w-4 mr-1" />
                Quay về Dashboard
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Auto-refresh for pending */}
      {finalStatus === "pending" && intentId && (
        <p className="text-xs text-muted-foreground mt-4 animate-pulse">
          Tự động làm mới sau mỗi 5 giây...
        </p>
      )}
    </div>
  )
}

export default PaymentReturnClient
