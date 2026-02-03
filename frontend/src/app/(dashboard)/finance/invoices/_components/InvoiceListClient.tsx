// src/app/(dashboard)/finance/invoices/_components/InvoiceListClient.tsx
"use client"

import * as React from "react"
import { useRouter, useSearchParams } from "next/navigation"
import Link from "next/link"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Progress } from "@/components/ui/progress"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Search,
  MoreHorizontal,
  Eye,
  FileText,
  XCircle,
  CreditCard,
  AlertTriangle,
  Filter,
  X,
  Clock,
} from "lucide-react"
import { useInvoices } from "@/hooks/finance/useInvoices"
import { toInvoiceListViewModel, type InvoiceListItemViewModel } from "@/hooks/finance/useInvoiceViewModel"
import { AmountDisplay, InvoiceStatusBadge } from "@/components/finance"
import { INVOICE_STATUS_LABELS, type InvoiceStatus } from "@/types/finance.types"
import { cn } from "@/lib/utils"
import { useMediaQuery } from "@/hooks/useMediaQuery"

// =============================================================================
// FILTER OPTIONS
// =============================================================================

const INVOICE_STATUS_OPTIONS: { value: InvoiceStatus | "all"; label: string }[] = [
  { value: "all", label: "Tất cả trạng thái" },
  { value: "draft", label: "Nháp" },
  { value: "issued", label: "Đã xuất" },
  { value: "partial", label: "Thanh toán một phần" },
  { value: "paid", label: "Đã thanh toán" },
  { value: "overdue", label: "Quá hạn" },
  { value: "cancelled", label: "Đã hủy" },
]

// =============================================================================
// TYPES
// =============================================================================

interface InvoiceFilters {
  status?: InvoiceStatus
  fee_id?: number
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

/**
 * InvoiceListClient - Client component for Invoice list page
 *
 * Features:
 * - Filterable and searchable invoice list
 * - Responsive: Table on desktop, Cards on mobile
 * - Quick actions: View, Issue, Cancel, Record Payment
 */
export function InvoiceListClient() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const isMobile = useMediaQuery("(max-width: 768px)")

  // Parse URL params
  const initialFilters: InvoiceFilters = {
    status: (searchParams.get("status") as InvoiceStatus) || undefined,
    fee_id: searchParams.get("fee_id") ? parseInt(searchParams.get("fee_id")!) : undefined,
  }

  // Local state
  const [filters, setFilters] = React.useState<InvoiceFilters>(initialFilters)
  const [searchQuery, setSearchQuery] = React.useState("")
  const [page, setPage] = React.useState(1)

  // Fetch invoices
  const { data, isLoading, error } = useInvoices({
    page,
    page_size: 20,
    status: filters.status,
    fee_id: filters.fee_id,
  })

  // Transform to view models
  const invoiceViewModels = React.useMemo(() => {
    if (!data?.items) return []
    return toInvoiceListViewModel(data.items)
  }, [data?.items])

  // Filter by search query (client-side)
  const filteredInvoices = React.useMemo(() => {
    if (!searchQuery) return invoiceViewModels
    const query = searchQuery.toLowerCase()
    return invoiceViewModels.filter(
      (invoice) => invoice.invoice_number.toLowerCase().includes(query)
    )
  }, [invoiceViewModels, searchQuery])

  // Update URL when filters change
  const updateFilters = React.useCallback(
    (newFilters: Partial<InvoiceFilters>) => {
      const updated = { ...filters, ...newFilters }
      setFilters(updated)

      // Update URL
      const params = new URLSearchParams()
      if (updated.status) params.set("status", updated.status)
      if (updated.fee_id) params.set("fee_id", updated.fee_id.toString())

      const queryString = params.toString()
      router.push(`/finance/invoices${queryString ? `?${queryString}` : ""}`)
    },
    [filters, router]
  )

  // Clear all filters
  const clearFilters = React.useCallback(() => {
    setFilters({})
    setSearchQuery("")
    router.push("/finance/invoices")
  }, [router])

  // Navigation handlers
  const handleView = (invoice: InvoiceListItemViewModel) => {
    router.push(`/finance/invoices/${invoice.id}`)
  }

  const handleIssue = (invoice: InvoiceListItemViewModel) => {
    router.push(`/finance/invoices/${invoice.id}?action=issue`)
  }

  const handleCancel = (invoice: InvoiceListItemViewModel) => {
    router.push(`/finance/invoices/${invoice.id}?action=cancel`)
  }

  const handleRecordPayment = (invoice: InvoiceListItemViewModel) => {
    router.push(`/finance/invoices/${invoice.id}?action=record-payment`)
  }

  // Check if any filters are active
  const hasActiveFilters = filters.status || filters.fee_id

  if (error) {
    return (
      <div className="h-full flex flex-col p-4 sm:p-6">
        <Card className="border-destructive">
          <CardContent className="p-6 text-center">
            <p className="text-destructive font-medium">Không thể tải danh sách hóa đơn</p>
            <p className="text-sm text-muted-foreground mt-1">Vui lòng thử lại sau</p>
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
          <h1 className="text-2xl font-bold tracking-tight">Quản lý hóa đơn</h1>
          <p className="text-muted-foreground">
            {data?.total ?? 0} hóa đơn
            {hasActiveFilters && " (đã lọc)"}
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Tìm theo số hóa đơn..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>

        {/* Status filter */}
        <Select
          value={filters.status ?? "all"}
          onValueChange={(value) =>
            updateFilters({ status: value === "all" ? undefined : (value as InvoiceStatus) })
          }
        >
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="Trạng thái" />
          </SelectTrigger>
          <SelectContent>
            {INVOICE_STATUS_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Clear filters */}
        {hasActiveFilters && (
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            <X className="h-4 w-4 mr-1" />
            Xóa bộ lọc
          </Button>
        )}
      </div>

      {/* Fee filter badge */}
      {filters.fee_id && (
        <div className="flex items-center gap-2 text-sm">
          <Filter className="h-4 w-4 text-muted-foreground" />
          <span className="text-muted-foreground">Lọc theo phí:</span>
          <span className="font-medium">#{filters.fee_id}</span>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2"
            onClick={() => updateFilters({ fee_id: undefined })}
          >
            <X className="h-3 w-3" />
          </Button>
        </div>
      )}

      {/* Content */}
      {isLoading ? (
        <InvoiceListSkeleton isMobile={isMobile} />
      ) : filteredInvoices.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <p className="text-muted-foreground">Không có hóa đơn nào</p>
            {hasActiveFilters && (
              <Button variant="link" onClick={clearFilters} className="mt-2">
                Xóa bộ lọc để xem tất cả
              </Button>
            )}
          </CardContent>
        </Card>
      ) : isMobile ? (
        <InvoiceCardList
          invoices={filteredInvoices}
          onView={handleView}
          onIssue={handleIssue}
          onCancel={handleCancel}
          onRecordPayment={handleRecordPayment}
        />
      ) : (
        <InvoiceTable
          invoices={filteredInvoices}
          onView={handleView}
          onIssue={handleIssue}
          onCancel={handleCancel}
          onRecordPayment={handleRecordPayment}
        />
      )}

      {/* Pagination */}
      {data && data.pages > 1 && (
        <div className="flex justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page === 1}
            onClick={() => setPage((p) => p - 1)}
          >
            Trước
          </Button>
          <span className="flex items-center px-4 text-sm text-muted-foreground">
            Trang {page} / {data.pages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page === data.pages}
            onClick={() => setPage((p) => p + 1)}
          >
            Sau
          </Button>
        </div>
      )}
    </div>
  )
}

// =============================================================================
// TABLE VIEW (Desktop)
// =============================================================================

interface InvoiceTableProps {
  invoices: InvoiceListItemViewModel[]
  onView: (invoice: InvoiceListItemViewModel) => void
  onIssue: (invoice: InvoiceListItemViewModel) => void
  onCancel: (invoice: InvoiceListItemViewModel) => void
  onRecordPayment: (invoice: InvoiceListItemViewModel) => void
}

function InvoiceTable({
  invoices,
  onView,
  onIssue,
  onCancel,
  onRecordPayment,
}: InvoiceTableProps) {
  return (
    <Card>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Số hóa đơn</TableHead>
            <TableHead>Đợt</TableHead>
            <TableHead>Trạng thái</TableHead>
            <TableHead className="text-right">Số tiền</TableHead>
            <TableHead className="text-right">Còn lại</TableHead>
            <TableHead>Tiến độ</TableHead>
            <TableHead>Hạn thanh toán</TableHead>
            <TableHead className="w-[50px]"></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {invoices.map((invoice) => (
            <TableRow
              key={invoice.id}
              className="cursor-pointer hover:bg-muted/50"
              onClick={() => onView(invoice)}
            >
              <TableCell className="font-medium font-mono">
                {invoice.invoice_number}
              </TableCell>
              <TableCell>Đợt {invoice.installment_no}</TableCell>
              <TableCell>
                <InvoiceStatusBadge status={invoice.status as InvoiceStatus} size="sm" />
              </TableCell>
              <TableCell className="text-right">
                <AmountDisplay amount={invoice.amount_formatted} showCurrency={false} />
              </TableCell>
              <TableCell className="text-right">
                <AmountDisplay
                  amount={invoice.remaining_amount_formatted}
                  showCurrency={false}
                  className={cn(
                    parseFloat(invoice.remaining_amount_formatted.replace(/[^\d]/g, "")) > 0 &&
                      "text-warning-600"
                  )}
                />
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <Progress value={invoice.payment_progress} className="w-16 h-2" />
                  <span className="text-xs text-muted-foreground w-8">
                    {invoice.payment_progress}%
                  </span>
                </div>
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-1.5">
                  {invoice.is_overdue && (
                    <AlertTriangle className="h-3.5 w-3.5 text-destructive" />
                  )}
                  {invoice.is_due_soon && !invoice.is_overdue && (
                    <Clock className="h-3.5 w-3.5 text-warning-500" />
                  )}
                  <span className={cn(invoice.is_overdue && "text-destructive font-medium")}>
                    {invoice.due_date_formatted}
                  </span>
                </div>
              </TableCell>
              <TableCell onClick={(e) => e.stopPropagation()}>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-8 w-8">
                      <MoreHorizontal className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => onView(invoice)}>
                      <Eye className="h-4 w-4 mr-2" />
                      Xem chi tiết
                    </DropdownMenuItem>
                    {invoice.can_issue && (
                      <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onClick={() => onIssue(invoice)}>
                          <FileText className="h-4 w-4 mr-2" />
                          Xuất hóa đơn
                        </DropdownMenuItem>
                      </>
                    )}
                    {invoice.can_record_payment && (
                      <DropdownMenuItem onClick={() => onRecordPayment(invoice)}>
                        <CreditCard className="h-4 w-4 mr-2" />
                        Ghi nhận thanh toán
                      </DropdownMenuItem>
                    )}
                    {invoice.can_cancel && (
                      <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          onClick={() => onCancel(invoice)}
                          className="text-destructive focus:text-destructive"
                        >
                          <XCircle className="h-4 w-4 mr-2" />
                          Hủy
                        </DropdownMenuItem>
                      </>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  )
}

// =============================================================================
// CARD LIST VIEW (Mobile)
// =============================================================================

interface InvoiceCardListProps {
  invoices: InvoiceListItemViewModel[]
  onView: (invoice: InvoiceListItemViewModel) => void
  onIssue: (invoice: InvoiceListItemViewModel) => void
  onCancel: (invoice: InvoiceListItemViewModel) => void
  onRecordPayment: (invoice: InvoiceListItemViewModel) => void
}

function InvoiceCardList({
  invoices,
  onView,
  onIssue,
  onCancel,
  onRecordPayment,
}: InvoiceCardListProps) {
  return (
    <div className="space-y-3">
      {invoices.map((invoice) => (
        <InvoiceCard
          key={invoice.id}
          invoice={invoice}
          onView={onView}
          onIssue={onIssue}
          onCancel={onCancel}
          onRecordPayment={onRecordPayment}
        />
      ))}
    </div>
  )
}

// =============================================================================
// INVOICE CARD (Mobile)
// =============================================================================

interface InvoiceCardProps {
  invoice: InvoiceListItemViewModel
  onView: (invoice: InvoiceListItemViewModel) => void
  onIssue: (invoice: InvoiceListItemViewModel) => void
  onCancel: (invoice: InvoiceListItemViewModel) => void
  onRecordPayment: (invoice: InvoiceListItemViewModel) => void
}

function InvoiceCard({
  invoice,
  onView,
  onIssue,
  onCancel,
  onRecordPayment,
}: InvoiceCardProps) {
  const hasActions = invoice.can_issue || invoice.can_cancel || invoice.can_record_payment

  return (
    <Card className={cn(
      "hover:shadow-md transition-shadow",
      invoice.is_overdue && "border-destructive/50 bg-destructive/5"
    )}>
      <CardContent className="p-4 space-y-3">
        {/* Header */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <p className="font-mono font-medium text-sm">{invoice.invoice_number}</p>
            <p className="text-xs text-muted-foreground">Đợt {invoice.installment_no}</p>
          </div>
          <div className="flex items-center gap-2">
            <InvoiceStatusBadge status={invoice.status as InvoiceStatus} size="sm" />
            {hasActions && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-8 w-8">
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => onView(invoice)}>
                    <Eye className="h-4 w-4 mr-2" />
                    Xem chi tiết
                  </DropdownMenuItem>
                  {invoice.can_issue && (
                    <DropdownMenuItem onClick={() => onIssue(invoice)}>
                      <FileText className="h-4 w-4 mr-2" />
                      Xuất hóa đơn
                    </DropdownMenuItem>
                  )}
                  {invoice.can_record_payment && (
                    <DropdownMenuItem onClick={() => onRecordPayment(invoice)}>
                      <CreditCard className="h-4 w-4 mr-2" />
                      Ghi nhận thanh toán
                    </DropdownMenuItem>
                  )}
                  {invoice.can_cancel && (
                    <DropdownMenuItem
                      onClick={() => onCancel(invoice)}
                      className="text-destructive"
                    >
                      <XCircle className="h-4 w-4 mr-2" />
                      Hủy
                    </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        </div>

        {/* Amounts */}
        <div className="flex justify-between items-end">
          <div>
            <p className="text-xs text-muted-foreground">Số tiền</p>
            <AmountDisplay amount={invoice.amount_formatted} size="lg" showCurrency={false} />
          </div>
          <div className="text-right">
            <p className="text-xs text-muted-foreground">Còn lại</p>
            <AmountDisplay
              amount={invoice.remaining_amount_formatted}
              size="md"
              showCurrency={false}
              className={cn(
                parseFloat(invoice.remaining_amount_formatted.replace(/[^\d]/g, "")) > 0 &&
                  "text-warning-600"
              )}
            />
          </div>
        </div>

        {/* Progress */}
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs">
            <span className="text-muted-foreground">Tiến độ</span>
            <span className="font-medium">{invoice.payment_progress}%</span>
          </div>
          <Progress value={invoice.payment_progress} className="h-2" />
        </div>

        {/* Due date */}
        <div className="flex justify-between items-center text-xs pt-2 border-t">
          <span className="text-muted-foreground">Hạn thanh toán</span>
          <div className="flex items-center gap-1.5">
            {invoice.is_overdue && (
              <AlertTriangle className="h-3.5 w-3.5 text-destructive" />
            )}
            {invoice.is_due_soon && !invoice.is_overdue && (
              <Clock className="h-3.5 w-3.5 text-warning-500" />
            )}
            <span className={cn(invoice.is_overdue && "text-destructive font-medium")}>
              {invoice.due_date_formatted}
            </span>
          </div>
        </div>

        {/* Action button */}
        <Button
          variant="outline"
          className="w-full min-h-[44px]"
          onClick={() => onView(invoice)}
        >
          Xem chi tiết
        </Button>
      </CardContent>
    </Card>
  )
}

// =============================================================================
// LOADING SKELETON
// =============================================================================

function InvoiceListSkeleton({ isMobile }: { isMobile: boolean }) {
  if (isMobile) {
    return (
      <div className="space-y-3">
        {[...Array(5)].map((_, i) => (
          <Skeleton key={i} className="h-56 rounded-lg" />
        ))}
      </div>
    )
  }

  return (
    <Card>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Số hóa đơn</TableHead>
            <TableHead>Đợt</TableHead>
            <TableHead>Trạng thái</TableHead>
            <TableHead className="text-right">Số tiền</TableHead>
            <TableHead className="text-right">Còn lại</TableHead>
            <TableHead>Tiến độ</TableHead>
            <TableHead>Hạn thanh toán</TableHead>
            <TableHead className="w-[50px]"></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {[...Array(10)].map((_, i) => (
            <TableRow key={i}>
              {[...Array(8)].map((_, j) => (
                <TableCell key={j}>
                  <Skeleton className="h-4 w-full" />
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  )
}

export default InvoiceListClient
