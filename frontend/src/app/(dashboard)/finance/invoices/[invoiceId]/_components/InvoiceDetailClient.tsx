// src/app/(dashboard)/finance/invoices/[invoiceId]/_components/InvoiceDetailClient.tsx
"use client"

import * as React from "react"
import { useRouter, useSearchParams } from "next/navigation"
import Link from "next/link"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Progress } from "@/components/ui/progress"
import { Separator } from "@/components/ui/separator"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  ArrowLeft,
  FileText,
  CreditCard,
  XCircle,
  AlertTriangle,
  Clock,
  CheckCircle,
  User,
  Receipt,
  Calendar,
} from "lucide-react"
import { useInvoiceViewModel } from "@/hooks/finance/useInvoiceViewModel"
import { AmountDisplay, InvoiceStatusBadge, PaymentStatusBadge } from "@/components/finance"
import { FEE_TYPE_LABELS, type PaymentStatus, type FeeType } from "@/types/finance.types"
import { cn } from "@/lib/utils"
import { PaymentRecordDialog } from "./PaymentRecordDialog"
import { InvoiceIssueDialog } from "./InvoiceIssueDialog"
import { InvoiceCancelDialog } from "./InvoiceCancelDialog"
import { InvoicePenaltyDialog } from "./InvoicePenaltyDialog"

// =============================================================================
// TYPES
// =============================================================================

interface InvoiceDetailClientProps {
  invoiceId: number
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

/**
 * InvoiceDetailClient - Comprehensive invoice detail view
 *
 * Features:
 * - Invoice summary with amounts and due date
 * - Payment history timeline
 * - Issue, Cancel, Record Payment actions
 */
export function InvoiceDetailClient({ invoiceId }: InvoiceDetailClientProps) {
  const router = useRouter()
  const searchParams = useSearchParams()

  // Dialog states
  const [recordPaymentOpen, setRecordPaymentOpen] = React.useState(
    searchParams.get("action") === "record-payment"
  )
  const [issueDialogOpen, setIssueDialogOpen] = React.useState(
    searchParams.get("action") === "issue"
  )
  const [cancelDialogOpen, setCancelDialogOpen] = React.useState(
    searchParams.get("action") === "cancel"
  )
  const [penaltyDialogOpen, setPenaltyDialogOpen] = React.useState(
    searchParams.get("action") === "penalty"
  )

  // Fetch invoice detail
  const { data: invoice, isLoading, error } = useInvoiceViewModel(invoiceId)

  // Handle dialog close
  const handleDialogClose = React.useCallback(() => {
    setRecordPaymentOpen(false)
    setIssueDialogOpen(false)
    setCancelDialogOpen(false)
    setPenaltyDialogOpen(false)
    router.replace(`/finance/invoices/${invoiceId}`)
  }, [invoiceId, router])

  if (isLoading) {
    return <InvoiceDetailSkeleton />
  }

  if (error || !invoice) {
    return (
      <div className="h-full flex flex-col p-4 sm:p-6">
        <Button variant="ghost" size="sm" onClick={() => router.back()} className="w-fit mb-4">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Quay lại
        </Button>
        <Card className="border-destructive">
          <CardContent className="p-6 text-center">
            <AlertTriangle className="h-8 w-8 text-destructive mx-auto mb-2" />
            <p className="text-destructive font-medium">Không thể tải thông tin hóa đơn</p>
            <p className="text-sm text-muted-foreground mt-1">
              Hóa đơn không tồn tại hoặc bạn không có quyền truy cập
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-6">
      {/* Back button */}
      <Button variant="ghost" size="sm" onClick={() => router.back()} className="w-fit">
        <ArrowLeft className="h-4 w-4 mr-2" />
        Quay lại
      </Button>

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight font-mono">
              {invoice.invoice_number}
            </h1>
            <InvoiceStatusBadge status={invoice.status} showIcon />
          </div>
          <p className="text-muted-foreground mt-1">
            Đợt {invoice.installment_no}
            {invoice.fee && (
              <>
                {" "}• <Link href={`/finance/fees/${invoice.fee.id}`} className="hover:underline">
                  {FEE_TYPE_LABELS[invoice.fee.fee_type as FeeType] ?? invoice.fee.fee_type}
                </Link>
              </>
            )}
          </p>
        </div>

        {/* Actions */}
        <div className="flex flex-wrap gap-2">
          {invoice.show_issue_button && (
            <Button onClick={() => setIssueDialogOpen(true)}>
              <FileText className="h-4 w-4 mr-2" />
              Xuất hóa đơn
            </Button>
          )}
          {invoice.show_record_payment_button && (
            <Button onClick={() => setRecordPaymentOpen(true)}>
              <CreditCard className="h-4 w-4 mr-2" />
              Ghi nhận thanh toán
            </Button>
          )}
          {invoice.show_penalty_button && (
            <Button
              variant="outline"
              className="text-warning-600 hover:text-warning-700"
              onClick={() => setPenaltyDialogOpen(true)}
            >
              <AlertTriangle className="h-4 w-4 mr-2" />
              Áp dụng phí trễ hạn
            </Button>
          )}
          {invoice.show_cancel_button && (
            <Button
              variant="outline"
              className="text-destructive hover:text-destructive"
              onClick={() => setCancelDialogOpen(true)}
            >
              <XCircle className="h-4 w-4 mr-2" />
              Hủy
            </Button>
          )}
        </div>
      </div>

      {/* Due date alert */}
      {invoice.is_overdue && (
        <Card className="border-destructive bg-destructive/5">
          <CardContent className="p-4 flex items-center gap-3">
            <AlertTriangle className="h-5 w-5 text-destructive shrink-0" />
            <div>
              <p className="font-medium text-destructive">Hóa đơn đã quá hạn</p>
              <p className="text-sm text-muted-foreground">
                Hạn thanh toán: {invoice.due_date_formatted}
                {invoice.days_until_due !== null && (
                  <span> ({Math.abs(invoice.days_until_due)} ngày trước)</span>
                )}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {invoice.is_due_soon && !invoice.is_overdue && (
        <Card className="border-warning-500 bg-warning-50/50 dark:bg-warning-950/20">
          <CardContent className="p-4 flex items-center gap-3">
            <Clock className="h-5 w-5 text-warning-600 shrink-0" />
            <div>
              <p className="font-medium text-warning-600">Sắp đến hạn thanh toán</p>
              <p className="text-sm text-muted-foreground">
                Còn {invoice.days_until_due} ngày (hạn: {invoice.due_date_formatted})
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          title="Số tiền"
          value={<AmountDisplay amount={invoice.amount_formatted} size="lg" showCurrency={false} />}
          icon={<Receipt className="h-4 w-4" />}
        />
        <StatCard
          title="Đã thanh toán"
          value={<AmountDisplay amount={invoice.paid_amount_formatted} size="lg" showCurrency={false} />}
          icon={<CheckCircle className="h-4 w-4" />}
          variant={invoice.is_paid ? "success" : "default"}
        />
        <StatCard
          title="Còn lại"
          value={<AmountDisplay amount={invoice.remaining_amount_formatted} size="lg" showCurrency={false} />}
          icon={<CreditCard className="h-4 w-4" />}
          variant={invoice.is_paid ? "success" : "warning"}
        />
        <StatCard
          title="Hạn thanh toán"
          value={invoice.due_date_formatted}
          icon={<Calendar className="h-4 w-4" />}
          variant={invoice.is_overdue ? "danger" : invoice.is_due_soon ? "warning" : "default"}
        />
      </div>

      {/* Progress */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">Tiến độ thanh toán</span>
            <span className="text-sm font-medium">{invoice.payment_progress}%</span>
          </div>
          <Progress value={invoice.payment_progress} className="h-3" />
        </CardContent>
      </Card>

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Payment History */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <CreditCard className="h-5 w-5" />
              Lịch sử thanh toán ({invoice.payments?.length || 0})
            </CardTitle>
            <CardDescription>Các khoản thanh toán đã ghi nhận</CardDescription>
          </CardHeader>
          <CardContent>
            {!invoice.payments || invoice.payments.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                <CreditCard className="h-8 w-8 mx-auto mb-2 opacity-50" />
                <p>Chưa có thanh toán nào</p>
                {invoice.show_record_payment_button && (
                  <Button
                    variant="link"
                    className="mt-2"
                    onClick={() => setRecordPaymentOpen(true)}
                  >
                    Ghi nhận thanh toán đầu tiên
                  </Button>
                )}
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Mã tham chiếu</TableHead>
                    <TableHead>Trạng thái</TableHead>
                    <TableHead className="text-right">Số tiền</TableHead>
                    <TableHead>Ngày</TableHead>
                    <TableHead>Ngày tạo</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {invoice.payments.map((payment) => (
                    <TableRow key={payment.id}>
                      <TableCell className="font-mono text-sm">
                        #{payment.id}
                      </TableCell>
                      <TableCell>
                        <PaymentStatusBadge
                          status={payment.status as PaymentStatus}
                          size="sm"
                        />
                      </TableCell>
                      <TableCell className="text-right">
                        <AmountDisplay amount={payment.amount} showCurrency={false} size="sm" />
                      </TableCell>
                      <TableCell className="text-sm">
                        {payment.payment_date
                          ? new Intl.DateTimeFormat("vi-VN").format(new Date(payment.payment_date))
                          : "-"}
                      </TableCell>
                      <TableCell className="text-sm">
                        {new Intl.DateTimeFormat("vi-VN").format(new Date(payment.created_at))}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Fee Info */}
          {invoice.fee && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Thông tin học phí</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Loại phí:</span>
                  <span>
                    {FEE_TYPE_LABELS[invoice.fee.fee_type as FeeType] ?? invoice.fee.fee_type}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Tổng học phí:</span>
                  <AmountDisplay amount={invoice.fee.final_amount} showCurrency={false} size="sm" />
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Năm học:</span>
                  <span>{invoice.fee.academic_year}</span>
                </div>
                <Separator className="my-2" />
                <Button variant="outline" size="sm" className="w-full" asChild>
                  <Link href={`/finance/fees/${invoice.fee.id}`}>
                    Xem chi tiết học phí
                  </Link>
                </Button>
              </CardContent>
            </Card>
          )}

          {/* Meta Info */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Thông tin</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Mã hóa đơn:</span>
                <span className="font-mono">{invoice.invoice_number}</span>
              </div>
              {invoice.issued_at_formatted && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Ngày xuất:</span>
                  <span>{invoice.issued_at_formatted}</span>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Dialogs */}
      <PaymentRecordDialog
        open={recordPaymentOpen}
        onOpenChange={(open) => {
          if (!open) handleDialogClose()
          else setRecordPaymentOpen(open)
        }}
        invoiceId={invoiceId}
        maxAmount={invoice.remaining_amount_formatted}
        feeId={invoice.fee?.id}
      />

      <InvoiceIssueDialog
        open={issueDialogOpen}
        onOpenChange={(open) => {
          if (!open) handleDialogClose()
          else setIssueDialogOpen(open)
        }}
        invoiceId={invoiceId}
        invoiceNumber={invoice.invoice_number}
        feeId={invoice.fee_id}
      />

      <InvoiceCancelDialog
        open={cancelDialogOpen}
        onOpenChange={(open) => {
          if (!open) handleDialogClose()
          else setCancelDialogOpen(open)
        }}
        invoiceId={invoiceId}
        invoiceNumber={invoice.invoice_number}
        feeId={invoice.fee_id}
      />

      <InvoicePenaltyDialog
        open={penaltyDialogOpen}
        onOpenChange={(open) => {
          if (!open) handleDialogClose()
          else setPenaltyDialogOpen(open)
        }}
        invoiceId={invoiceId}
        invoiceNumber={invoice.invoice_number}
        feeId={invoice.fee_id}
        daysOverdue={invoice.days_until_due !== null && invoice.days_until_due < 0
          ? Math.abs(invoice.days_until_due)
          : undefined}
      />
    </div>
  )
}

// =============================================================================
// STAT CARD
// =============================================================================

interface StatCardProps {
  title: string
  value: React.ReactNode
  icon: React.ReactNode
  variant?: "default" | "success" | "warning" | "danger"
}

function StatCard({ title, value, icon, variant = "default" }: StatCardProps) {
  return (
    <Card
      className={cn(
        variant === "success" && "border-success-500/50 bg-success-50/30 dark:bg-success-950/20",
        variant === "warning" && "border-warning-500/50 bg-warning-50/30 dark:bg-warning-950/20",
        variant === "danger" && "border-destructive/50 bg-destructive/5"
      )}
    >
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-muted-foreground">{title}</span>
          <div
            className={cn(
              "p-1.5 rounded-full",
              variant === "default" && "bg-muted text-muted-foreground",
              variant === "success" && "bg-success-100 text-success-600",
              variant === "warning" && "bg-warning-100 text-warning-600",
              variant === "danger" && "bg-destructive/10 text-destructive"
            )}
          >
            {icon}
          </div>
        </div>
        <div className="font-semibold">{value}</div>
      </CardContent>
    </Card>
  )
}

// =============================================================================
// SKELETON
// =============================================================================

function InvoiceDetailSkeleton() {
  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-6">
      <Skeleton className="h-8 w-24" />
      <div className="space-y-2">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-64" />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-lg" />
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Skeleton className="h-80 rounded-lg lg:col-span-2" />
        <Skeleton className="h-80 rounded-lg" />
      </div>
    </div>
  )
}

export default InvoiceDetailClient
