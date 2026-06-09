// src/app/(dashboard)/finance/_components/FinanceDashboardClient.tsx
"use client"

import * as React from "react"
import Link from "next/link"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Calculator,
  CreditCard,
  Receipt,
  AlertTriangle,
  TrendingUp,
  ArrowRight,
  Plus,
  CalendarDays,
} from "lucide-react"
import { useFinanceDashboard } from "@/hooks/finance/useFinanceDashboard"
import { AmountDisplay } from "@/components/finance"
import { cn } from "@/lib/utils"
import { DashboardDateProvider, useDashboardDate } from "@/contexts/DashboardDateContext"
import { DateRangeFilter } from "@/components/officer/dashboard/DateRangeFilter"

// =============================================================================
// STAT CARD COMPONENT
// =============================================================================

interface StatCardProps {
  title: string
  value: React.ReactNode
  description?: string
  icon: React.ReactNode
  href?: string
  variant?: "default" | "warning" | "success"
  isLoading?: boolean
}

function StatCard({
  title,
  value,
  description,
  icon,
  href,
  variant = "default",
  isLoading,
}: StatCardProps) {
  const content = (
    <Card
      className={cn(
        "hover:shadow-md transition-shadow",
        variant === "warning" && "border-warning-500 bg-warning-50/50 dark:bg-warning-950/20",
        variant === "success" && "border-success-500 bg-success-50/50 dark:bg-success-950/20"
      )}
    >
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <div
          className={cn(
            "p-2 rounded-full",
            variant === "default" && "bg-primary/10 text-primary",
            variant === "warning" && "bg-warning-100 text-warning-600",
            variant === "success" && "bg-success-100 text-success-600"
          )}
        >
          {icon}
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-8 w-24" />
        ) : (
          <div className="text-2xl font-bold">{value}</div>
        )}
        {description && (
          <p className="text-xs text-muted-foreground mt-1">{description}</p>
        )}
      </CardContent>
    </Card>
  )

  if (href) {
    return (
      <Link href={href} className="block">
        {content}
      </Link>
    )
  }

  return content
}

// =============================================================================
// QUICK ACTION CARD
// =============================================================================

interface QuickActionProps {
  title: string
  description: string
  icon: React.ReactNode
  href: string
}

function QuickAction({ title, description, icon, href }: QuickActionProps) {
  return (
    <Link href={href}>
      <Card className="hover:shadow-md hover:border-primary/50 transition-shadow cursor-pointer h-full">
        <CardContent className="p-4 flex items-center gap-4">
          <div className="p-3 rounded-lg bg-primary/10 text-primary shrink-0">
            {icon}
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-medium text-sm">{title}</p>
            <p className="text-xs text-muted-foreground truncate">{description}</p>
          </div>
          <ArrowRight className="h-4 w-4 text-muted-foreground shrink-0" />
        </CardContent>
      </Card>
    </Link>
  )
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

/**
 * Inner component that uses the date context
 */
function FinanceDashboardInner() {
  const { startDate, endDate } = useDashboardDate()
  const { data: stats, isLoading, error } = useFinanceDashboard({
    startDate,
    endDate,
  })

  if (error) {
    return (
      <div className="h-full flex flex-col p-4 sm:p-6">
        <Card className="border-destructive">
          <CardContent className="p-6 text-center">
            <AlertTriangle className="h-8 w-8 text-destructive mx-auto mb-2" />
            <p className="text-destructive font-medium">Không thể tải dữ liệu</p>
            <p className="text-sm text-muted-foreground mt-1">
              Vui lòng thử lại sau
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Tổng quan tài chính</h1>
            <p className="text-muted-foreground">
              Quản lý học phí, hóa đơn và thanh toán
            </p>
          </div>
          <Button asChild>
            <Link href="/finance/fees?action=calculate">
              <Plus className="h-4 w-4 mr-2" />
              Tính phí mới
            </Link>
          </Button>
        </div>

        {/* Date Range Filter */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <CalendarDays className="h-4 w-4" />
            <span>Lọc theo thời gian:</span>
          </div>
          <DateRangeFilter />
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Chờ xác minh"
          value={stats?.pending_payments_count ?? 0}
          description="Thanh toán chờ duyệt"
          icon={<CreditCard className="h-4 w-4" />}
          href="/finance/payments"
          variant={stats?.pending_payments_count && stats.pending_payments_count > 0 ? "warning" : "default"}
          isLoading={isLoading}
        />
        <StatCard
          title="Hóa đơn quá hạn"
          value={stats?.overdue_invoices_count ?? 0}
          description={stats?.overdue_amount ? `${stats.overdue_amount}` : undefined}
          icon={<AlertTriangle className="h-4 w-4" />}
          href="/finance/invoices?status=overdue"
          variant={stats?.overdue_invoices_count && stats.overdue_invoices_count > 0 ? "warning" : "default"}
          isLoading={isLoading}
        />
        <StatCard
          title="Thu hôm nay"
          value={
            isLoading ? (
              "..."
            ) : (
              <AmountDisplay
                amount={stats?.today_collections ?? "0"}
                size="xl"
                showCurrency={false}
              />
            )
          }
          icon={<TrendingUp className="h-4 w-4" />}
          variant="success"
          isLoading={isLoading}
        />
        <StatCard
          title="Thu trong kỳ"
          value={
            isLoading ? (
              "..."
            ) : (
              <AmountDisplay
                amount={stats?.period_collections ?? "0"}
                size="xl"
                showCurrency={false}
              />
            )
          }
          description={stats?.period_start && stats?.period_end ? `${stats.period_start} → ${stats.period_end}` : undefined}
          icon={<CalendarDays className="h-4 w-4" />}
          isLoading={isLoading}
        />
      </div>

      {/* Quick Actions and Info */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Quick Actions */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Thao tác nhanh</CardTitle>
            <CardDescription>Các tác vụ thường dùng</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <QuickAction
              title="Tính phí mới"
              description="Tính học phí cho hồ sơ đã duyệt"
              icon={<Calculator className="h-5 w-5" />}
              href="/finance/fees?action=calculate"
            />
            <QuickAction
              title="Xem danh sách phí"
              description="Quản lý tất cả học phí"
              icon={<Calculator className="h-5 w-5" />}
              href="/finance/fees"
            />
            <QuickAction
              title="Quản lý hóa đơn"
              description="Xuất và theo dõi hóa đơn"
              icon={<Receipt className="h-5 w-5" />}
              href="/finance/invoices"
            />
            <QuickAction
              title="Xác minh thanh toán"
              description={`${stats?.pending_payments_count ?? 0} thanh toán chờ xử lý`}
              icon={<CreditCard className="h-5 w-5" />}
              href="/finance/payments"
            />
          </CardContent>
        </Card>

        {/* Info Card */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Tổng quan</CardTitle>
            <CardDescription>Thống kê nhanh</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex justify-between items-center py-2 border-b">
              <span className="text-muted-foreground">Phí chờ xử lý</span>
              <span className="font-medium">{stats?.pending_fees_count ?? 0}</span>
            </div>
            <div className="flex justify-between items-center py-2 border-b">
              <span className="text-muted-foreground">Tổng phí chờ thu</span>
              <AmountDisplay
                amount={stats?.pending_fees_amount ?? "0"}
                size="md"
                className="font-medium"
              />
            </div>
            <div className="flex justify-between items-center py-2 border-b">
              <span className="text-muted-foreground">Thanh toán dư chờ xử lý</span>
              <span className="font-medium">{stats?.pending_overpayments_count ?? 0}</span>
            </div>
            <div className="flex justify-between items-center py-2">
              <span className="text-muted-foreground">Yêu cầu hoàn tiền</span>
              <span className="font-medium">{stats?.pending_refunds_count ?? 0}</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

/**
 * FinanceDashboardClient - Client component for Finance Dashboard
 *
 * Displays:
 * - Key statistics (pending payments, overdue, collections)
 * - Date range filter for period collections
 * - Quick actions
 * - Overview statistics
 *
 * Wrapped with DashboardDateProvider to enable date filtering.
 */
export function FinanceDashboardClient() {
  return (
    <DashboardDateProvider defaultPreset="7d">
      <FinanceDashboardInner />
    </DashboardDateProvider>
  )
}

export default FinanceDashboardClient
