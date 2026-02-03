// src/app/(dashboard)/finance/payments/_components/PaymentListClient.tsx
"use client"

import * as React from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
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
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import {
  Clock,
  CheckCircle,
  XCircle,
  AlertTriangle,
  CreditCard,
  Filter,
  RefreshCw,
} from "lucide-react"
import { usePayments, useVerifyPayment, useRejectPayment } from "@/hooks/finance/usePayments"
import {
  toPendingPaymentListViewModel,
  toPaymentListViewModel,
  type PendingPaymentViewModel,
  type PaymentListItemViewModel,
} from "@/hooks/finance/usePaymentViewModel"
import { PendingPaymentCard, PaymentCard, AmountDisplay } from "@/components/finance"
import { cn } from "@/lib/utils"
import { toast } from "sonner"

// =============================================================================
// FILTER OPTIONS
// =============================================================================

const PAYMENT_STATUS_OPTIONS = [
  { value: "pending", label: "Chờ xác minh" },
  { value: "all", label: "Tất cả" },
  { value: "verified", label: "Đã xác minh" },
  { value: "rejected", label: "Từ chối" },
]

// =============================================================================
// MAIN COMPONENT
// =============================================================================

/**
 * PaymentListClient - Verification queue for Maker-Checker workflow
 *
 * Features:
 * - Shows pending payments needing verification
 * - Highlights payments waiting > 24 hours
 * - Verify/Reject actions with confirmation dialogs
 * - Maker-Checker: Users cannot verify their own payments
 */
export function PaymentListClient() {
  const router = useRouter()
  const searchParams = useSearchParams()

  // State
  const [statusFilter, setStatusFilter] = React.useState<string>(
    searchParams.get("status") || "pending"
  )
  const [selectedPayment, setSelectedPayment] = React.useState<
    PendingPaymentViewModel | PaymentListItemViewModel | null
  >(null)
  const [dialogType, setDialogType] = React.useState<"verify" | "reject" | null>(null)
  const [rejectionReason, setRejectionReason] = React.useState("")

  // Fetch payments
  const { data, isLoading, error, refetch } = usePayments({
    status: statusFilter === "all" ? undefined : (statusFilter as "pending" | "verified" | "rejected" | "refunded"),
    page: 1,
    page_size: 50,
  })

  // Mutations
  const verifyMutation = useVerifyPayment()
  const rejectMutation = useRejectPayment()

  // Transform to view models
  const payments = React.useMemo(() => {
    if (!data?.items) return []
    if (statusFilter === "pending") {
      return toPendingPaymentListViewModel(data.items)
    }
    return toPaymentListViewModel(data.items)
  }, [data?.items, statusFilter])

  // Stats
  const stats = React.useMemo(() => {
    const pending = payments.filter((p) => p.status === "pending")
    const needsAttention = statusFilter === "pending"
      ? (pending as PendingPaymentViewModel[]).filter((p) => p.needs_attention).length
      : 0
    return {
      total: pending.length,
      needsAttention,
    }
  }, [payments, statusFilter])

  // Handlers
  const handleVerify = (payment: PendingPaymentViewModel | PaymentListItemViewModel) => {
    setSelectedPayment(payment)
    setDialogType("verify")
  }

  const handleReject = (payment: PendingPaymentViewModel | PaymentListItemViewModel) => {
    setSelectedPayment(payment)
    setDialogType("reject")
    setRejectionReason("")
  }

  const handleView = (payment: PendingPaymentViewModel | PaymentListItemViewModel) => {
    // Navigate to invoice detail which shows payments
    router.push(`/finance/invoices/${payment.invoice_id}`)
  }

  const confirmVerify = async () => {
    if (!selectedPayment) return

    try {
      await verifyMutation.mutateAsync({
        paymentId: selectedPayment.id,
        invoiceId: selectedPayment.invoice_id,
      })
      toast.success("Đã xác minh thanh toán")
      setDialogType(null)
      setSelectedPayment(null)
      refetch()
    } catch (error) {
      toast.error("Không thể xác minh thanh toán")
    }
  }

  const confirmReject = async () => {
    if (!selectedPayment || !rejectionReason.trim()) return

    try {
      await rejectMutation.mutateAsync({
        paymentId: selectedPayment.id,
        invoiceId: selectedPayment.invoice_id,
        data: { rejection_reason: rejectionReason.trim() },
      })
      toast.success("Đã từ chối thanh toán")
      setDialogType(null)
      setSelectedPayment(null)
      setRejectionReason("")
      refetch()
    } catch (error) {
      toast.error("Không thể từ chối thanh toán")
    }
  }

  if (error) {
    return (
      <div className="h-full flex flex-col p-4 sm:p-6">
        <Card className="border-destructive">
          <CardContent className="p-6 text-center">
            <AlertTriangle className="h-8 w-8 text-destructive mx-auto mb-2" />
            <p className="text-destructive font-medium">Không thể tải danh sách</p>
            <p className="text-sm text-muted-foreground mt-1">
              Vui lòng thử lại sau
            </p>
            <Button variant="outline" className="mt-4" onClick={() => refetch()}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Thử lại
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Xác minh thanh toán</h1>
          <p className="text-muted-foreground">
            Xét duyệt các khoản thanh toán chờ xác minh
          </p>
        </div>
        <Button variant="outline" onClick={() => refetch()}>
          <RefreshCw className="h-4 w-4 mr-2" />
          Làm mới
        </Button>
      </div>

      {/* Stats */}
      {statusFilter === "pending" && (
        <div className="flex flex-wrap gap-4">
          <Card className="flex-1 min-w-[150px]">
            <CardContent className="p-4 flex items-center gap-4">
              <div className="p-3 rounded-full bg-primary/10 text-primary">
                <Clock className="h-5 w-5" />
              </div>
              <div>
                <p className="text-2xl font-bold">{stats.total}</p>
                <p className="text-xs text-muted-foreground">Chờ xác minh</p>
              </div>
            </CardContent>
          </Card>
          {stats.needsAttention > 0 && (
            <Card className="flex-1 min-w-[150px] border-warning-500 bg-warning-50/50 dark:bg-warning-950/20">
              <CardContent className="p-4 flex items-center gap-4">
                <div className="p-3 rounded-full bg-warning-100 text-warning-600">
                  <AlertTriangle className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-warning-600">{stats.needsAttention}</p>
                  <p className="text-xs text-muted-foreground">Quá 24h chưa xử lý</p>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Filter */}
      <div className="flex items-center gap-2">
        <Filter className="h-4 w-4 text-muted-foreground" />
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="Trạng thái" />
          </SelectTrigger>
          <SelectContent>
            {PAYMENT_STATUS_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Content */}
      {isLoading ? (
        <PaymentListSkeleton />
      ) : payments.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <CheckCircle className="h-12 w-12 text-success-500 mx-auto mb-4" />
            <p className="text-lg font-medium">Không có thanh toán chờ xử lý</p>
            <p className="text-sm text-muted-foreground mt-1">
              Tất cả thanh toán đã được xử lý
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {statusFilter === "pending"
            ? (payments as PendingPaymentViewModel[]).map((payment) => (
                <PendingPaymentCard
                  key={payment.id}
                  payment={payment}
                  onView={handleView}
                  onVerify={handleVerify}
                  onReject={handleReject}
                />
              ))
            : (payments as PaymentListItemViewModel[]).map((payment) => (
                <PaymentCard
                  key={payment.id}
                  payment={payment}
                  onView={handleView}
                  onVerify={handleVerify}
                  onReject={handleReject}
                />
              ))}
        </div>
      )}

      {/* Verify Confirmation Dialog */}
      <AlertDialog
        open={dialogType === "verify"}
        onOpenChange={(open) => !open && setDialogType(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác minh thanh toán</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc chắn muốn xác minh thanh toán này?
            </AlertDialogDescription>
          </AlertDialogHeader>
          {selectedPayment && (
            <div className="py-4 space-y-2">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Mã tham chiếu:</span>
                <span className="font-medium">
                  {selectedPayment.reference_code || `#${selectedPayment.id}`}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Số tiền:</span>
                <AmountDisplay
                  amount={selectedPayment.amount_formatted}
                  size="md"
                  className="font-medium"
                />
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Người tạo:</span>
                <span>{selectedPayment.created_by_display}</span>
              </div>
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmVerify}
              disabled={verifyMutation.isPending}
              className="bg-success-600 hover:bg-success-700"
            >
              {verifyMutation.isPending ? "Đang xử lý..." : "Xác minh"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Reject Confirmation Dialog */}
      <AlertDialog
        open={dialogType === "reject"}
        onOpenChange={(open) => !open && setDialogType(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Từ chối thanh toán</AlertDialogTitle>
            <AlertDialogDescription>
              Vui lòng nhập lý do từ chối. Người tạo sẽ được thông báo.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {selectedPayment && (
            <div className="py-4 space-y-4">
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Mã tham chiếu:</span>
                  <span className="font-medium">
                    {selectedPayment.reference_code || `#${selectedPayment.id}`}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Số tiền:</span>
                  <AmountDisplay
                    amount={selectedPayment.amount_formatted}
                    size="sm"
                    className="font-medium"
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="rejection-reason">
                  Lý do từ chối <span className="text-destructive">*</span>
                </Label>
                <Textarea
                  id="rejection-reason"
                  placeholder="Nhập lý do từ chối..."
                  value={rejectionReason}
                  onChange={(e) => setRejectionReason(e.target.value)}
                  rows={3}
                />
              </div>
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmReject}
              disabled={rejectMutation.isPending || !rejectionReason.trim()}
              className="bg-destructive hover:bg-destructive/90"
            >
              {rejectMutation.isPending ? "Đang xử lý..." : "Từ chối"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

// =============================================================================
// LOADING SKELETON
// =============================================================================

function PaymentListSkeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {[...Array(6)].map((_, i) => (
        <Skeleton key={i} className="h-52 rounded-lg" />
      ))}
    </div>
  )
}

export default PaymentListClient
