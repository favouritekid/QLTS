"use client"

/**
 * Tuition Tab Component
 *
 * Displays tuition fee information by integrating with the Finance module.
 * Uses FeeStatusLink for READ-ONLY cross-reference to maintain phase separation.
 *
 * @see FRONTEND_ARCHITECTURE_V3.md - Phase Separation
 */

import Link from "next/link"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  CreditCard,
  Receipt,
  ExternalLink,
  AlertTriangle,
  CheckCircle,
  Clock,
  Calculator,
  FileText,
} from "lucide-react"
import { useProfileFinanceSummary } from "@/hooks/finance/useFees"
import {
  AmountDisplay,
  FeeStatusBadge,
} from "@/components/finance"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import type { FeeStatus } from "@/types/finance.types"
import { FEE_TYPE_LABELS } from "@/types/finance.types"
import { cn } from "@/lib/utils"

interface TuitionTabProps {
  profile: AdmissionProfileResponse
}

export function TuitionTab({ profile }: TuitionTabProps) {
  const { data: summary, isLoading, error } = useProfileFinanceSummary(profile.id)

  // Loading state
  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-48 w-full rounded-lg" />
        <Skeleton className="h-32 w-full rounded-lg" />
        <Skeleton className="h-48 w-full rounded-lg" />
      </div>
    )
  }

  // Error or no data - show prompt to calculate fee
  if (error || !summary) {
    return (
      <div className="space-y-6">
        <Card>
          <CardContent className="py-12 text-center">
            <Calculator className="h-16 w-16 mx-auto text-muted-foreground/30 mb-4" />
            <h3 className="text-lg font-medium mb-2">Chưa có thông tin học phí</h3>
            <p className="text-muted-foreground text-sm mb-6 max-w-md mx-auto">
              Học phí chưa được tính cho hồ sơ này. Chuyển đến module Tài chính để tính phí.
            </p>
            <Button asChild>
              <Link href={`/finance/fees?action=calculate&profile_id=${profile.id}`}>
                <Calculator className="h-4 w-4 mr-2" />
                Tính học phí
              </Link>
            </Button>
          </CardContent>
        </Card>

        <NoticeCard />
      </div>
    )
  }

  const hasFees = summary.fees.length > 0
  const totalRemaining = parseFloat(summary.total_remaining.replace(/[^\d.-]/g, "")) || 0
  const isPaid = hasFees && totalRemaining === 0
  const hasOverdue = summary.overdue_invoices > 0

  // No fees yet
  if (!hasFees) {
    return (
      <div className="space-y-6">
        <Card>
          <CardContent className="py-12 text-center">
            <Calculator className="h-16 w-16 mx-auto text-muted-foreground/30 mb-4" />
            <h3 className="text-lg font-medium mb-2">Chưa tính học phí</h3>
            <p className="text-muted-foreground text-sm mb-6 max-w-md mx-auto">
              Hồ sơ cần được tính học phí trước khi có thể thanh toán.
            </p>
            <Button asChild>
              <Link href={`/finance/fees?action=calculate&profile_id=${profile.id}`}>
                <Calculator className="h-4 w-4 mr-2" />
                Tính học phí
              </Link>
            </Button>
          </CardContent>
        </Card>

        <NoticeCard />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Summary Card */}
      <Card
        className={cn(
          hasOverdue && "border-destructive/50",
          isPaid && "border-success-500/50"
        )}
      >
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <CreditCard className="h-5 w-5" />
            Tổng quan học phí
          </CardTitle>
          <CardDescription>
            Thông tin học phí và tiến độ thanh toán
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Tổng học phí"
              value={<AmountDisplay amount={summary.total_fees} showCurrency={false} size="lg" />}
              variant="default"
            />
            <StatCard
              label="Đã thanh toán"
              value={<AmountDisplay amount={summary.total_paid} showCurrency={false} size="lg" />}
              variant="success"
            />
            <StatCard
              label="Còn lại"
              value={<AmountDisplay amount={summary.total_remaining} showCurrency={false} size="lg" />}
              variant={isPaid ? "success" : hasOverdue ? "danger" : "warning"}
            />
            <StatCard
              label="Trạng thái"
              value={
                isPaid ? (
                  <div className="flex items-center gap-1.5 text-success-600">
                    <CheckCircle className="h-5 w-5" />
                    <span>Đã thanh toán</span>
                  </div>
                ) : hasOverdue ? (
                  <div className="flex items-center gap-1.5 text-destructive">
                    <AlertTriangle className="h-5 w-5" />
                    <span>Quá hạn</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-1.5 text-warning-600">
                    <Clock className="h-5 w-5" />
                    <span>Chờ thanh toán</span>
                  </div>
                )
              }
              variant={isPaid ? "success" : hasOverdue ? "danger" : "warning"}
            />
          </div>

          {/* Overdue alert */}
          {hasOverdue && (
            <div className="mt-4 p-3 rounded-lg bg-destructive/10 border border-destructive/30 flex items-center gap-3">
              <AlertTriangle className="h-5 w-5 text-destructive shrink-0" />
              <div className="flex-1">
                <p className="font-medium text-destructive">
                  Có {summary.overdue_invoices} hóa đơn quá hạn
                </p>
                <p className="text-sm text-muted-foreground">
                  Vui lòng thanh toán sớm để tránh phí trễ hạn
                </p>
              </div>
              <Button variant="destructive" size="sm" asChild>
                <Link href={`/finance/invoices?profile_id=${profile.id}&status=overdue`}>
                  Xem chi tiết
                </Link>
              </Button>
            </div>
          )}

          {/* Action button */}
          <div className="mt-6 flex justify-end">
            <Button asChild>
              <Link href={`/finance/fees?profile_id=${profile.id}`}>
                <ExternalLink className="h-4 w-4 mr-2" />
                Quản lý trong Finance
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Fee List */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Receipt className="h-5 w-5" />
            Danh sách học phí ({summary.fees.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {summary.fees.map((fee) => (
              <Link
                key={fee.id}
                href={`/finance/fees/${fee.id}`}
                className="flex items-center justify-between p-3 border rounded-lg hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-primary/10 rounded">
                    <FileText className="h-4 w-4 text-primary" />
                  </div>
                  <div>
                    <p className="font-medium">
                      {FEE_TYPE_LABELS[fee.fee_type] ?? fee.fee_type}
                      {fee.semester_no ? ` — HK${fee.semester_no}` : ""}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Năm học: {fee.academic_year}
                      {fee.semester_no ? ` | HK${fee.semester_no}` : ""}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <AmountDisplay amount={fee.final_amount} size="sm" />
                    <p className="text-xs text-muted-foreground">
                      Còn: <AmountDisplay amount={fee.remaining_amount} size="sm" showCurrency={false} />
                    </p>
                  </div>
                  <FeeStatusBadge status={fee.status} size="sm" />
                </div>
              </Link>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* View all invoices link */}
      {summary.pending_invoices > 0 || summary.overdue_invoices > 0 ? (
        <Card>
          <CardContent className="py-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Receipt className="h-5 w-5 text-muted-foreground" />
                <div>
                  <p className="font-medium">Hóa đơn</p>
                  <p className="text-xs text-muted-foreground">
                    {summary.pending_invoices > 0 && `${summary.pending_invoices} chờ thanh toán`}
                    {summary.pending_invoices > 0 && summary.overdue_invoices > 0 && " • "}
                    {summary.overdue_invoices > 0 && (
                      <span className="text-destructive">{summary.overdue_invoices} quá hạn</span>
                    )}
                  </p>
                </div>
              </div>
              <Button variant="outline" size="sm" asChild>
                <Link href={`/finance/invoices?profile_id=${profile.id}`}>
                  Xem hóa đơn
                  <ExternalLink className="h-3 w-3 ml-1" />
                </Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <NoticeCard />
    </div>
  )
}

// =============================================================================
// HELPER COMPONENTS
// =============================================================================

interface StatCardProps {
  label: string
  value: React.ReactNode
  variant?: "default" | "success" | "warning" | "danger"
}

function StatCard({ label, value, variant = "default" }: StatCardProps) {
  return (
    <div
      className={cn(
        "p-4 rounded-lg",
        variant === "default" && "bg-muted/50",
        variant === "success" && "bg-success-50 dark:bg-success-950/20",
        variant === "warning" && "bg-warning-50 dark:bg-warning-950/20",
        variant === "danger" && "bg-destructive/10"
      )}
    >
      <p
        className={cn(
          "text-sm",
          variant === "default" && "text-muted-foreground",
          variant === "success" && "text-success-600",
          variant === "warning" && "text-warning-600",
          variant === "danger" && "text-destructive"
        )}
      >
        {label}
      </p>
      <div
        className={cn(
          "font-bold",
          variant === "success" && "text-success-700",
          variant === "warning" && "text-warning-700",
          variant === "danger" && "text-destructive"
        )}
      >
        {value}
      </div>
    </div>
  )
}

function NoticeCard() {
  return (
    <Card className="border-dashed border-primary/30 bg-primary/5">
      <CardContent className="pt-4">
        <div className="flex items-start gap-3">
          <Calculator className="h-5 w-5 text-primary mt-0.5" />
          <div className="text-sm">
            <p className="font-medium text-primary">Lưu ý</p>
            <p className="text-muted-foreground">
              Tab này hiển thị thông tin học phí từ module Tài chính. Để thực hiện các
              thao tác như ghi nhận thanh toán, xác minh, hoặc hoàn tiền, vui lòng sử
              dụng module <Link href="/finance" className="text-primary hover:underline">Finance</Link>.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
