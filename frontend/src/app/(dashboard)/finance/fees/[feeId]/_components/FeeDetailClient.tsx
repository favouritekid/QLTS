// src/app/(dashboard)/finance/fees/[feeId]/_components/FeeDetailClient.tsx
"use client"

import * as React from "react"
import { useRouter, useSearchParams } from "next/navigation"
import Link from "next/link"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Progress } from "@/components/ui/progress"
import { Separator } from "@/components/ui/separator"
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
  Calculator,
  Percent,
  XCircle,
  RefreshCw,
  FileText,
  CreditCard,
  AlertTriangle,
  User,
  Calendar,
  Receipt,
} from "lucide-react"
import { useFeeViewModel } from "@/hooks/finance/useFeeViewModel"
import { AmountDisplay, FeeStatusBadge, InvoiceStatusBadge } from "@/components/finance"
import { FEE_TYPE_LABELS, type FeeType, type InvoiceStatus } from "@/types/finance.types"
import { cn } from "@/lib/utils"
import { FeeWaiveDialog } from "./FeeWaiveDialog"
import { FeeCancelDialog } from "./FeeCancelDialog"
import { FeeRecalculateDialog } from "./FeeRecalculateDialog"

// =============================================================================
// TYPES
// =============================================================================

interface FeeDetailClientProps {
  feeId: number
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

/**
 * FeeDetailClient - Comprehensive fee detail view
 *
 * Features:
 * - Fee summary with amounts and progress
 * - Invoice list with status and quick actions
 * - Applied discounts display
 * - Waive/Cancel/Recalculate actions
 */
export function FeeDetailClient({ feeId }: FeeDetailClientProps) {
  const router = useRouter()
  const searchParams = useSearchParams()

  // State for dialogs
  const [waiveDialogOpen, setWaiveDialogOpen] = React.useState(
    searchParams.get("action") === "waive"
  )
  const [cancelDialogOpen, setCancelDialogOpen] = React.useState(
    searchParams.get("action") === "cancel"
  )
  const [recalculateDialogOpen, setRecalculateDialogOpen] = React.useState(
    searchParams.get("action") === "recalculate"
  )

  // Fetch fee detail
  const { data: fee, isLoading, error } = useFeeViewModel(feeId)

  // Handle dialog close and URL cleanup
  const handleDialogClose = React.useCallback(() => {
    setWaiveDialogOpen(false)
    setCancelDialogOpen(false)
    setRecalculateDialogOpen(false)
    // Remove action from URL
    router.replace(`/finance/fees/${feeId}`)
  }, [feeId, router])

  if (isLoading) {
    return <FeeDetailSkeleton />
  }

  if (error || !fee) {
    return (
      <div className="h-full flex flex-col p-4 sm:p-6">
        <Button variant="ghost" size="sm" onClick={() => router.back()} className="w-fit mb-4">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Quay lại
        </Button>
        <Card className="border-destructive">
          <CardContent className="p-6 text-center">
            <AlertTriangle className="h-8 w-8 text-destructive mx-auto mb-2" />
            <p className="text-destructive font-medium">Không thể tải thông tin học phí</p>
            <p className="text-sm text-muted-foreground mt-1">
              {error?.message || "Học phí không tồn tại hoặc bạn không có quyền truy cập"}
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
            <h1 className="text-2xl font-bold tracking-tight">
              {fee.fee_type_label}
            </h1>
            <FeeStatusBadge status={fee.status} showIcon />
          </div>
          <p className="text-muted-foreground mt-1">
            Năm học {fee.academic_year}
          </p>
        </div>

        {/* Actions */}
        <div className="flex flex-wrap gap-2">
          {fee.show_waive_button && (
            <Button variant="outline" onClick={() => setWaiveDialogOpen(true)}>
              <Percent className="h-4 w-4 mr-2" />
              Miễn giảm
            </Button>
          )}
          {fee.show_recalculate_button && (
            <Button variant="outline" onClick={() => setRecalculateDialogOpen(true)}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Tính lại
            </Button>
          )}
          {fee.show_cancel_button && (
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

      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          title="Tổng học phí"
          value={<AmountDisplay amount={fee.base_amount_formatted} size="lg" showCurrency={false} />}
          icon={<Calculator className="h-4 w-4" />}
        />
        <StatCard
          title="Giảm giá"
          value={<AmountDisplay amount={fee.total_discount_formatted} size="lg" showCurrency={false} />}
          icon={<Percent className="h-4 w-4" />}
          variant={fee.has_discounts ? "success" : "default"}
        />
        <StatCard
          title="Phải thu"
          value={<AmountDisplay amount={fee.final_amount_formatted} size="lg" showCurrency={false} />}
          icon={<Receipt className="h-4 w-4" />}
        />
        <StatCard
          title="Còn lại"
          value={<AmountDisplay amount={fee.remaining_amount_formatted} size="lg" showCurrency={false} />}
          icon={<CreditCard className="h-4 w-4" />}
          variant={fee.is_paid ? "success" : fee.is_overdue ? "danger" : "warning"}
        />
      </div>

      {/* Progress */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">Tiến độ thanh toán</span>
            <span className="text-sm font-medium">{fee.payment_progress}%</span>
          </div>
          <Progress value={fee.payment_progress} className="h-3" />
          <div className="flex justify-between mt-2 text-xs text-muted-foreground">
            <span>Đã thanh toán: {fee.paid_amount_formatted}</span>
            {fee.waived_amount_formatted !== "0 ₫" && (
              <span>Đã miễn giảm: {fee.waived_amount_formatted}</span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Invoices */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <FileText className="h-5 w-5" />
              Hóa đơn ({fee.invoices.length})
            </CardTitle>
            <CardDescription>Danh sách hóa đơn theo đợt thanh toán</CardDescription>
          </CardHeader>
          <CardContent>
            {fee.invoices.length === 0 ? (
              <p className="text-muted-foreground text-center py-8">
                Chưa có hóa đơn nào
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Số HĐ</TableHead>
                    <TableHead>Đợt</TableHead>
                    <TableHead>Trạng thái</TableHead>
                    <TableHead className="text-right">Số tiền</TableHead>
                    <TableHead className="text-right">Còn lại</TableHead>
                    <TableHead>Hạn</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {fee.invoices.map((invoice) => (
                    <TableRow
                      key={invoice.id}
                      className="cursor-pointer hover:bg-muted/50"
                      onClick={() => router.push(`/finance/invoices/${invoice.id}`)}
                    >
                      <TableCell className="font-mono text-sm">
                        {invoice.invoice_number}
                      </TableCell>
                      <TableCell>Đợt {invoice.installment_no}</TableCell>
                      <TableCell>
                        <InvoiceStatusBadge
                          status={invoice.status as InvoiceStatus}
                          size="sm"
                        />
                      </TableCell>
                      <TableCell className="text-right">
                        <AmountDisplay amount={invoice.amount} showCurrency={false} size="sm" />
                      </TableCell>
                      <TableCell className="text-right">
                        <AmountDisplay
                          amount={invoice.remaining_amount}
                          showCurrency={false}
                          size="sm"
                          className={cn(
                            parseFloat(invoice.remaining_amount) > 0 && "text-warning-600"
                          )}
                        />
                      </TableCell>
                      <TableCell className="text-sm">
                        {new Intl.DateTimeFormat("vi-VN", {
                          day: "2-digit",
                          month: "2-digit",
                          year: "numeric",
                        }).format(new Date(invoice.due_date))}
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
          {/* Applied Discounts */}
          {fee.has_discounts && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <Percent className="h-5 w-5" />
                  Giảm giá áp dụng
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {fee.applied_discounts.map((discount) => (
                  <div
                    key={discount.id}
                    className="flex items-center justify-between py-2 border-b last:border-0"
                  >
                    <div>
                      <p className="font-medium text-sm">{discount.policy_name}</p>
                      <p className="text-xs text-muted-foreground">
                        Thứ tự: {discount.application_order}
                      </p>
                    </div>
                    <AmountDisplay
                      amount={discount.discount_amount}
                      size="sm"
                      className="text-success-600"
                    />
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {/* Installment Plan */}
          {fee.has_installment_plan && fee.installment_plan && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <Calendar className="h-5 w-5" />
                  Kế hoạch trả góp
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Kế hoạch:</span>
                    <span className="font-medium">{fee.installment_plan.name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Số đợt:</span>
                    <span>{fee.installment_plan.installment_count} đợt</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Phí trễ hạn:</span>
                    <span>{fee.installment_plan.penalty_rate}%</span>
                  </div>
                </div>
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
                <span className="text-muted-foreground">Mã học phí:</span>
                <span className="font-mono">#{fee.id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Tạo lúc:</span>
                <span>
                  {new Intl.DateTimeFormat("vi-VN", {
                    day: "2-digit",
                    month: "2-digit",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  }).format(new Date(fee.created_at))}
                </span>
              </div>
              {fee.notes && (
                <>
                  <Separator className="my-2" />
                  <div>
                    <span className="text-muted-foreground">Ghi chú:</span>
                    <p className="mt-1">{fee.notes}</p>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Dialogs */}
      <FeeWaiveDialog
        open={waiveDialogOpen}
        onOpenChange={(open) => {
          if (!open) handleDialogClose()
          else setWaiveDialogOpen(open)
        }}
        feeId={feeId}
        maxAmount={fee.remaining_amount}
        maxAmountFormatted={fee.remaining_amount_formatted}
      />

      <FeeCancelDialog
        open={cancelDialogOpen}
        onOpenChange={(open) => {
          if (!open) handleDialogClose()
          else setCancelDialogOpen(open)
        }}
        feeId={feeId}
        feeType={fee.fee_type_label}
      />

      <FeeRecalculateDialog
        open={recalculateDialogOpen}
        onOpenChange={(open) => {
          if (!open) handleDialogClose()
          else setRecalculateDialogOpen(open)
        }}
        feeId={feeId}
        feeType={fee.fee_type_label}
        currentBaseAmount={fee.base_amount}
        currentBaseAmountFormatted={fee.base_amount_formatted}
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

function FeeDetailSkeleton() {
  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-6">
      <Skeleton className="h-8 w-24" />
      <div className="space-y-2">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-48" />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-lg" />
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Skeleton className="h-96 rounded-lg lg:col-span-2" />
        <Skeleton className="h-96 rounded-lg" />
      </div>
    </div>
  )
}

export default FeeDetailClient
