// src/app/(dashboard)/finance/fees/_components/FeeListClient.tsx
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Progress } from "@/components/ui/progress"
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
  Plus,
  Search,
  MoreHorizontal,
  Eye,
  Percent,
  XCircle,
  RefreshCw,
  Filter,
  X,
} from "lucide-react"
import { useFees } from "@/hooks/finance/useFees"
import { toFeeListViewModel, type FeeListItemViewModel } from "@/hooks/finance/useFeeViewModel"
import { AmountDisplay, FeeStatusBadge, FeeCard } from "@/components/finance"
import {
  FEE_TYPE_LABELS,
  FEE_STATUS_LABELS,
  type FeeType,
  type FeeStatus,
} from "@/types/finance.types"
import { cn } from "@/lib/utils"
import { useMediaQuery } from "@/hooks/useMediaQuery"
import { FeeCalculateDialog } from "./FeeCalculateDialog"

// =============================================================================
// FILTER OPTIONS
// =============================================================================

const FEE_STATUS_OPTIONS: { value: FeeStatus | "all"; label: string }[] = [
  { value: "all", label: "Tất cả trạng thái" },
  { value: "pending", label: "Chờ tính phí" },
  { value: "calculated", label: "Đã tính phí" },
  { value: "invoiced", label: "Đã xuất hóa đơn" },
  { value: "partial", label: "Thanh toán một phần" },
  { value: "paid", label: "Đã thanh toán" },
  { value: "overdue", label: "Quá hạn" },
  { value: "waived", label: "Đã miễn giảm" },
  { value: "cancelled", label: "Đã hủy" },
]

const FEE_TYPE_OPTIONS: { value: FeeType | "all"; label: string }[] = [
  { value: "all", label: "Tất cả loại phí" },
  { value: "tuition", label: "Học phí" },
  { value: "application", label: "Lệ phí hồ sơ" },
  { value: "enrollment", label: "Phí nhập học" },
  { value: "insurance", label: "Bảo hiểm" },
  { value: "dormitory", label: "Ký túc xá" },
  { value: "other", label: "Khác" },
]

// =============================================================================
// TYPES
// =============================================================================

interface FeeFilters {
  status?: FeeStatus
  fee_type?: FeeType
  profile_id?: number
  search?: string
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

/**
 * FeeListClient - Client component for Fee list page
 *
 * Features:
 * - Filterable and searchable fee list
 * - Responsive: Table on desktop, Cards on mobile
 * - Quick actions: View, Waive, Cancel, Recalculate
 */
export function FeeListClient() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const isMobile = useMediaQuery("(max-width: 768px)")

  // Parse URL params
  const initialFilters: FeeFilters = {
    status: (searchParams.get("status") as FeeStatus) || undefined,
    fee_type: (searchParams.get("fee_type") as FeeType) || undefined,
    profile_id: searchParams.get("profile_id")
      ? parseInt(searchParams.get("profile_id")!)
      : undefined,
  }

  // Calculate dialog state (from URL param ?action=calculate)
  const [calculateDialogOpen, setCalculateDialogOpen] = React.useState(
    searchParams.get("action") === "calculate"
  )

  // Local state
  const [filters, setFilters] = React.useState<FeeFilters>(initialFilters)
  const [searchQuery, setSearchQuery] = React.useState("")
  const [page, setPage] = React.useState(1)

  // Fetch fees
  const { data, isLoading, error } = useFees({
    page,
    page_size: 20,
    status: filters.status,
    fee_type: filters.fee_type,
    profile_id: filters.profile_id,
  })

  // Transform to view models
  // eslint-disable-next-line react-hooks/preserve-manual-memoization -- toFeeListViewModel is pure
  const feeViewModels = React.useMemo(() => {
    if (!data?.items) return []
    return toFeeListViewModel(data.items)
  }, [data?.items])

  // Filter by search query (client-side)
  const filteredFees = React.useMemo(() => {
    if (!searchQuery) return feeViewModels
    const query = searchQuery.toLowerCase()
    return feeViewModels.filter(
      (fee) =>
        fee.fee_type_label.toLowerCase().includes(query) ||
        fee.academic_year.includes(query)
    )
  }, [feeViewModels, searchQuery])

  // Update URL when filters change
  const updateFilters = React.useCallback(
    (newFilters: Partial<FeeFilters>) => {
      const updated = { ...filters, ...newFilters }
      setFilters(updated)

      // Update URL
      const params = new URLSearchParams()
      if (updated.status) params.set("status", updated.status)
      if (updated.fee_type) params.set("fee_type", updated.fee_type)
      if (updated.profile_id) params.set("profile_id", updated.profile_id.toString())

      const queryString = params.toString()
      router.push(`/finance/fees${queryString ? `?${queryString}` : ""}`)
    },
    [filters, router]
  )

  // Clear all filters
  const clearFilters = React.useCallback(() => {
    setFilters({})
    setSearchQuery("")
    router.push("/finance/fees")
  }, [router])

  // Navigation handlers
  const handleView = (fee: FeeListItemViewModel) => {
    router.push(`/finance/fees/${fee.id}`)
  }

  const handleWaive = (fee: FeeListItemViewModel) => {
    router.push(`/finance/fees/${fee.id}?action=waive`)
  }

  const handleCancel = (fee: FeeListItemViewModel) => {
    router.push(`/finance/fees/${fee.id}?action=cancel`)
  }

  const handleRecalculate = (fee: FeeListItemViewModel) => {
    router.push(`/finance/fees/${fee.id}?action=recalculate`)
  }

  // Handle calculate dialog close - remove action from URL
  const handleCalculateDialogChange = React.useCallback(
    (open: boolean) => {
      setCalculateDialogOpen(open)
      if (!open) {
        // Remove action param from URL when closing
        const params = new URLSearchParams(searchParams.toString())
        params.delete("action")
        const queryString = params.toString()
        router.replace(`/finance/fees${queryString ? `?${queryString}` : ""}`)
      }
    },
    [router, searchParams]
  )

  // Check if any filters are active
  const hasActiveFilters = filters.status || filters.fee_type || filters.profile_id

  if (error) {
    return (
      <div className="h-full flex flex-col p-4 sm:p-6">
        <Card className="border-destructive">
          <CardContent className="p-6 text-center">
            <p className="text-destructive font-medium">Không thể tải danh sách phí</p>
            <p className="text-sm text-muted-foreground mt-1">
              Vui lòng thử lại sau
            </p>
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
          <h1 className="text-2xl font-bold tracking-tight">Quản lý học phí</h1>
          <p className="text-muted-foreground">
            {data?.total ?? 0} khoản phí
            {hasActiveFilters && " (đã lọc)"}
          </p>
        </div>
        <Button onClick={() => setCalculateDialogOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Tính phí mới
        </Button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Tìm kiếm..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>

        {/* Status filter */}
        <Select
          value={filters.status ?? "all"}
          onValueChange={(value) =>
            updateFilters({ status: value === "all" ? undefined : (value as FeeStatus) })
          }
        >
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="Trạng thái" />
          </SelectTrigger>
          <SelectContent>
            {FEE_STATUS_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Type filter */}
        <Select
          value={filters.fee_type ?? "all"}
          onValueChange={(value) =>
            updateFilters({ fee_type: value === "all" ? undefined : (value as FeeType) })
          }
        >
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="Loại phí" />
          </SelectTrigger>
          <SelectContent>
            {FEE_TYPE_OPTIONS.map((opt) => (
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

      {/* Profile filter badge */}
      {filters.profile_id && (
        <div className="flex items-center gap-2 text-sm">
          <Filter className="h-4 w-4 text-muted-foreground" />
          <span className="text-muted-foreground">Lọc theo hồ sơ:</span>
          <span className="font-medium">#{filters.profile_id}</span>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2"
            onClick={() => updateFilters({ profile_id: undefined })}
          >
            <X className="h-3 w-3" />
          </Button>
        </div>
      )}

      {/* Content */}
      {isLoading ? (
        <FeeListSkeleton isMobile={isMobile} />
      ) : filteredFees.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <p className="text-muted-foreground">Không có khoản phí nào</p>
            {hasActiveFilters && (
              <Button variant="link" onClick={clearFilters} className="mt-2">
                Xóa bộ lọc để xem tất cả
              </Button>
            )}
          </CardContent>
        </Card>
      ) : isMobile ? (
        <FeeCardList
          fees={filteredFees}
          onView={handleView}
          onWaive={handleWaive}
          onCancel={handleCancel}
          onRecalculate={handleRecalculate}
        />
      ) : (
        <FeeTable
          fees={filteredFees}
          onView={handleView}
          onWaive={handleWaive}
          onCancel={handleCancel}
          onRecalculate={handleRecalculate}
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

      {/* Calculate Fee Dialog */}
      <FeeCalculateDialog
        open={calculateDialogOpen}
        onOpenChange={handleCalculateDialogChange}
        defaultProfileId={filters.profile_id}
      />
    </div>
  )
}

// =============================================================================
// TABLE VIEW (Desktop)
// =============================================================================

interface FeeTableProps {
  fees: FeeListItemViewModel[]
  onView: (fee: FeeListItemViewModel) => void
  onWaive: (fee: FeeListItemViewModel) => void
  onCancel: (fee: FeeListItemViewModel) => void
  onRecalculate: (fee: FeeListItemViewModel) => void
}

function FeeTable({ fees, onView, onWaive, onCancel, onRecalculate }: FeeTableProps) {
  return (
    <Card>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Loại phí</TableHead>
            <TableHead>Năm học</TableHead>
            <TableHead>Trạng thái</TableHead>
            <TableHead className="text-right">Tổng cộng</TableHead>
            <TableHead className="text-right">Còn lại</TableHead>
            <TableHead>Tiến độ</TableHead>
            <TableHead>Hạn thanh toán</TableHead>
            <TableHead className="w-[50px]"></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {fees.map((fee) => (
            <TableRow
              key={fee.id}
              className="cursor-pointer hover:bg-muted/50"
              onClick={() => onView(fee)}
            >
              <TableCell className="font-medium">
                {fee.fee_type_label}
              </TableCell>
              <TableCell>{fee.academic_year}</TableCell>
              <TableCell>
                <FeeStatusBadge status={fee.status as FeeStatus} size="sm" />
              </TableCell>
              <TableCell className="text-right">
                <AmountDisplay amount={fee.final_amount_formatted} showCurrency={false} />
              </TableCell>
              <TableCell className="text-right">
                <AmountDisplay
                  amount={fee.remaining_amount_formatted}
                  showCurrency={false}
                  className={cn(
                    parseFloat(fee.remaining_amount_formatted.replace(/[^\d.-]/g, "")) > 0 &&
                      "text-warning-600"
                  )}
                />
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <Progress value={fee.payment_progress} className="w-16 h-2" />
                  <span className="text-xs text-muted-foreground w-8">
                    {fee.payment_progress}%
                  </span>
                </div>
              </TableCell>
              <TableCell>
                {fee.due_date_formatted ? (
                  <span className={cn(fee.is_overdue && "text-destructive font-medium")}>
                    {fee.due_date_formatted}
                  </span>
                ) : (
                  <span className="text-muted-foreground">-</span>
                )}
              </TableCell>
              <TableCell onClick={(e) => e.stopPropagation()}>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-8 w-8">
                      <MoreHorizontal className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => onView(fee)}>
                      <Eye className="h-4 w-4 mr-2" />
                      Xem chi tiết
                    </DropdownMenuItem>
                    {fee.can_waive && (
                      <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onClick={() => onWaive(fee)}>
                          <Percent className="h-4 w-4 mr-2" />
                          Miễn giảm
                        </DropdownMenuItem>
                      </>
                    )}
                    {fee.can_recalculate && (
                      <DropdownMenuItem onClick={() => onRecalculate(fee)}>
                        <RefreshCw className="h-4 w-4 mr-2" />
                        Tính lại
                      </DropdownMenuItem>
                    )}
                    {fee.can_cancel && (
                      <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          onClick={() => onCancel(fee)}
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

interface FeeCardListProps {
  fees: FeeListItemViewModel[]
  onView: (fee: FeeListItemViewModel) => void
  onWaive: (fee: FeeListItemViewModel) => void
  onCancel: (fee: FeeListItemViewModel) => void
  onRecalculate: (fee: FeeListItemViewModel) => void
}

function FeeCardList({
  fees,
  onView,
  onWaive,
  onCancel,
  onRecalculate,
}: FeeCardListProps) {
  return (
    <div className="space-y-3">
      {fees.map((fee) => (
        <FeeCard
          key={fee.id}
          fee={fee}
          onView={onView}
          onWaive={onWaive}
          onCancel={onCancel}
          onRecalculate={onRecalculate}
        />
      ))}
    </div>
  )
}

// =============================================================================
// LOADING SKELETON
// =============================================================================

function FeeListSkeleton({ isMobile }: { isMobile: boolean }) {
  if (isMobile) {
    return (
      <div className="space-y-3">
        {[...Array(5)].map((_, i) => (
          <Skeleton key={i} className="h-48 rounded-lg" />
        ))}
      </div>
    )
  }

  return (
    <Card>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Loại phí</TableHead>
            <TableHead>Năm học</TableHead>
            <TableHead>Trạng thái</TableHead>
            <TableHead className="text-right">Tổng cộng</TableHead>
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

export default FeeListClient
