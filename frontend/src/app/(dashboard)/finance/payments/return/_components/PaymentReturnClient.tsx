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

function parseStatus(statusParam: string | null, intentStatus?: string): PaymentStatus {
  // Priority: query param > intent status
  if (statusParam) {
    const normalized = statusParam.toLowerCase()
    if (normalized === "success" || normalized === "completed" || normalized === "00") {
      return "success"
    }
    if (normalized === "failed" || normalized === "failure" || normalized === "error") {
      return "failed"
    }
    if (normalized === "cancelled" || normalized === "cancel") {
      return "cancelled"
    }
    if (normalized === "pending" || normalized === "processing") {
      return "pending"
    }
    if (normalized === "expired") {
      return "expired"
    }
  }

  // Fall back to intent status
  if (intentStatus) {
    if (intentStatus === "completed") return "success"
    if (intentStatus === "failed") return "failed"
    if (intentStatus === "cancelled") return "cancelled"
    if (intentStatus === "expired") return "expired"
    if (intentStatus === "pending" || intentStatus === "created") return "pending"
  }

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

  // Parse query params
  const statusParam = searchParams.get("status")
  const intentId = searchParams.get("intent_id")
  const invoiceId = searchParams.get("invoice_id")
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

  // Determine final status
  const finalStatus = React.useMemo(() => {
    return parseStatus(statusParam, intent?.status)
  }, [statusParam, intent?.status])

  // Get status config
  const config = STATUS_CONFIG[finalStatus]

  // Get invoice ID from intent if not in params
  const targetInvoiceId = invoiceId || intent?.invoice_id?.toString()

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
          {/* Error message */}
          {errorMessage && (
            <div className="p-3 rounded-lg bg-destructive/10 text-destructive text-sm">
              <p className="font-medium">Chi tiết lỗi:</p>
              <p>{decodeURIComponent(errorMessage)}</p>
            </div>
          )}

          {/* Transaction details */}
          {(reference || intent) && (
            <div className="space-y-2 text-sm text-left bg-background/50 p-3 rounded-lg">
              {reference && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Mã giao dịch:</span>
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
                  Về Finance
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
