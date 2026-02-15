// src/app/(dashboard)/admissions/_components/AdmissionsClient.tsx
/**
 * AdmissionsClient - Main client component for admissions list
 *
 * Features:
 * - TanStack Table with sorting and selection
 * - Advanced filters: status, major, academic year, degree level, payment status, date range
 * - Status tabs with count badges
 * - Stats cards (totals, conversion rate, avg completion)
 * - Mobile card view
 * - Bulk actions (approve, reject, assign, export)
 */

"use client"

import { useState, useMemo, useCallback, useEffect, memo } from "react"
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type SortingState,
  type RowSelectionState,
} from "@tanstack/react-table"
import { format } from "date-fns"
import { vi } from "date-fns/locale"
import {
  ClipboardCheck,
  Search,
  X,
  Calendar,
  Filter,
  MoreVertical,
  FileText,
  Users,
  CheckCircle2,
  GraduationCap,
  TrendingUp,
  BarChart3,
} from "lucide-react"
import Link from "next/link"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import {
  BaseCard,
  CardHeader as BaseCardHeader,
  CardBody,
  CardMeta,
  CardTime,
  CardActions,
} from "@/components/ui/base-card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Calendar as CalendarComponent } from "@/components/ui/calendar"
import { PageContainer } from "@/components/layouts/PageContainer"
import { EmptyState, ErrorEmptyState } from "@/components/common/EmptyState"
import { Pagination } from "@/components/common/table/Pagination"
import { cn } from "@/lib/utils"

import {
  useListAdmissions,
  useAcademicYears,
  useDegreeLevelsPublic,
  useAdmissionStatusCounts,
  useAdmissionStats,
  useBulkApproveAdmissions,
  useBulkRejectAdmissions,
  useBulkAssignAdmissions,
  useExportAdmissions,
} from "@/hooks/admissions"
import { useMajorPrograms } from "@/hooks/admissions/useProgramData"
import type { AdmissionProfileResponse, AdmissionListParams, AdmissionsPage } from "@/lib/zod/admissions"
import { getColumns, STATUS_CONFIG, ELIGIBILITY_CONFIG } from "./columns"
import { AdmissionsBulkActionsBar } from "./AdmissionsBulkActionsBar"
import { BulkRejectDialog } from "./dialogs/BulkRejectDialog"
import { BulkAssignDialog } from "./dialogs/BulkAssignDialog"

// =============================================================================
// CONSTANTS
// =============================================================================

const DEFAULT_PAGE_SIZE = 20
const CURRENT_YEAR = new Date().getFullYear()

const STATUS_OPTIONS = [
  { value: "draft", label: "Nháp" },
  { value: "submitted", label: "Chờ duyệt" },
  { value: "resubmitted", label: "Đã nộp lại" },
  { value: "approved", label: "Đã duyệt" },
  { value: "rejected", label: "Từ chối" },
  { value: "confirmed", label: "Đã xác nhận" },
  { value: "overridden", label: "Đã override" },
  { value: "enrolled", label: "Đã nhập học" },
]

const PAYMENT_STATUS_OPTIONS = [
  { value: "paid", label: "Đã thanh toán" },
  { value: "unpaid", label: "Chưa thanh toán" },
  { value: "partial", label: "Thanh toán một phần" },
  { value: "no_fee", label: "Chưa có học phí" },
]

/** Tab definitions - group statuses for quick filtering */
const STATUS_TABS = [
  { key: "all", label: "Tất cả", statuses: [] as string[] },
  { key: "draft", label: "Nháp", statuses: ["draft"] },
  { key: "pending", label: "Chờ duyệt", statuses: ["submitted", "resubmitted"] },
  { key: "approved", label: "Đã duyệt", statuses: ["approved", "confirmed", "overridden"] },
  { key: "enrolled", label: "Đã nhập học", statuses: ["enrolled"] },
  { key: "rejected", label: "Từ chối", statuses: ["rejected"] },
] as const

// =============================================================================
// STAT CARD COMPONENT
// =============================================================================

interface StatCardProps {
  label: string
  value: number | string
  icon: React.ReactNode
  className?: string
}

const StatCard = memo(function StatCard({ label, value, icon, className }: StatCardProps) {
  return (
    <Card className={cn("p-4", className)}>
      <div className="flex items-center gap-3">
        <div className="flex-shrink-0 rounded-lg bg-muted p-2">
          {icon}
        </div>
        <div className="min-w-0">
          <p className="text-2xl font-bold tracking-tight">{value}</p>
          <p className="text-xs text-muted-foreground truncate">{label}</p>
        </div>
      </div>
    </Card>
  )
})

// =============================================================================
// MAIN COMPONENT
// =============================================================================

interface AdmissionsClientProps {
  initialData?: AdmissionsPage
}

export function AdmissionsClient({ initialData }: AdmissionsClientProps) {
  // Filter state
  const [search, setSearch] = useState("")
  const [debouncedSearch, setDebouncedSearch] = useState("")
  const [selectedStatuses, setSelectedStatuses] = useState<string[]>([])
  const [selectedMajorId, setSelectedMajorId] = useState<string | undefined>()
  const [selectedYear, setSelectedYear] = useState<number | undefined>(CURRENT_YEAR)
  const [selectedDegreeLevel, setSelectedDegreeLevel] = useState<string | undefined>()
  const [selectedPaymentStatus, setSelectedPaymentStatus] = useState<string | undefined>()
  const [dateFrom, setDateFrom] = useState<Date | undefined>()
  const [dateTo, setDateTo] = useState<Date | undefined>()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)

  // Tab state
  const [activeTab, setActiveTab] = useState<string>("all")

  // Table state
  const [sorting, setSorting] = useState<SortingState>([])
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})

  // Dialog state
  const [rejectDialogOpen, setRejectDialogOpen] = useState(false)
  const [assignDialogOpen, setAssignDialogOpen] = useState(false)

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search)
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  // Reference data queries
  const { data: majorPrograms } = useMajorPrograms()
  const { data: academicYears } = useAcademicYears()
  const { data: degreeLevels } = useDegreeLevelsPublic()

  // Year options: from API or fallback
  const yearOptions = useMemo(() => {
    if (academicYears && academicYears.length > 0) return academicYears
    return [CURRENT_YEAR + 1, CURRENT_YEAR, CURRENT_YEAR - 1]
  }, [academicYears])

  // Build filters
  const filters: AdmissionListParams = useMemo(() => ({
    page,
    page_size: pageSize,
    status: selectedStatuses.length > 0 ? selectedStatuses.join(",") : undefined,
    search: debouncedSearch || undefined,
    major_id: selectedMajorId || undefined,
    academic_year: selectedYear,
    degree_level: selectedDegreeLevel,
    payment_status: selectedPaymentStatus,
    date_from: dateFrom ? format(dateFrom, "yyyy-MM-dd") : undefined,
    date_to: dateTo ? format(dateTo, "yyyy-MM-dd") : undefined,
    sort_by: sorting[0]?.id as AdmissionListParams["sort_by"],
    order: sorting[0]?.desc ? "desc" : "asc",
  }), [page, pageSize, selectedStatuses, debouncedSearch, selectedMajorId, selectedYear, selectedDegreeLevel, selectedPaymentStatus, dateFrom, dateTo, sorting])

  // Filters without status/page for status-counts query (separate queryKey)
  const countFilters = useMemo(() => ({
    search: debouncedSearch || undefined,
    major_id: selectedMajorId || undefined,
    academic_year: selectedYear,
    degree_level: selectedDegreeLevel,
    payment_status: selectedPaymentStatus,
    date_from: dateFrom ? format(dateFrom, "yyyy-MM-dd") : undefined,
    date_to: dateTo ? format(dateTo, "yyyy-MM-dd") : undefined,
  }), [debouncedSearch, selectedMajorId, selectedYear, selectedDegreeLevel, selectedPaymentStatus, dateFrom, dateTo])

  // Queries
  const { data, isLoading, isError, isFetching } = useListAdmissions(filters, { initialData })
  const { data: statusCounts } = useAdmissionStatusCounts(countFilters)
  const { data: stats } = useAdmissionStats(selectedYear)

  // Mutations
  const bulkApprove = useBulkApproveAdmissions()
  const bulkReject = useBulkRejectAdmissions()
  const bulkAssign = useBulkAssignAdmissions()
  const exportCsv = useExportAdmissions()

  const profiles = data?.profiles ?? []
  const totalCount = data?.total_count ?? 0

  // Column definitions
  const columns = useMemo(() => getColumns(), [])

  // Table instance
  const table = useReactTable({
    data: profiles,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    enableRowSelection: true,
    state: { sorting, rowSelection },
    getRowId: (row) => String(row.id),
  })

  const selectedProfiles = useMemo(() => {
    return table.getSelectedRowModel().rows.map((row) => row.original)
  }, [table, rowSelection])

  const selectedIds = useMemo(() => {
    return selectedProfiles.map((p) => p.id)
  }, [selectedProfiles])

  const clearSelection = useCallback(() => {
    setRowSelection({})
  }, [])

  const handleFilterChange = useCallback(() => {
    setPage(1)
  }, [])

  // Handle status filter change (dropdown multi-select)
  const handleStatusToggle = useCallback((status: string) => {
    setSelectedStatuses((prev) => {
      return prev.includes(status)
        ? prev.filter((s) => s !== status)
        : [...prev, status]
    })
    setActiveTab("all") // Reset tab when manually selecting statuses
    handleFilterChange()
  }, [handleFilterChange])

  // Handle tab click
  const handleTabClick = useCallback((tabKey: string) => {
    setActiveTab(tabKey)
    const tab = STATUS_TABS.find((t) => t.key === tabKey)
    setSelectedStatuses(tab?.statuses ? [...tab.statuses] : [])
    setPage(1)
  }, [])

  // Precompute tab counts to avoid re-creating function reference on every statusCounts update
  const tabCounts = useMemo(() => {
    if (!statusCounts?.counts) return undefined
    const result: Record<string, number> = { all: statusCounts.total }
    for (const tab of STATUS_TABS) {
      if (tab.key !== "all") {
        result[tab.key] = tab.statuses.reduce((sum, s) => sum + (statusCounts.counts[s] ?? 0), 0)
      }
    }
    return result
  }, [statusCounts])

  // Clear all filters
  const clearFilters = useCallback(() => {
    setSearch("")
    setDebouncedSearch("")
    setSelectedStatuses([])
    setSelectedMajorId(undefined)
    setSelectedYear(CURRENT_YEAR) // Reset to current year, not undefined
    setSelectedDegreeLevel(undefined)
    setSelectedPaymentStatus(undefined)
    setDateFrom(undefined)
    setDateTo(undefined)
    setActiveTab("all")
    setPage(1)
  }, [])

  // Bulk actions
  const handleBulkApprove = useCallback(async () => {
    if (selectedIds.length === 0) return
    await bulkApprove.mutateAsync({ profile_ids: selectedIds })
    clearSelection()
  }, [selectedIds, bulkApprove, clearSelection])

  const handleBulkReject = useCallback(async (reason: string) => {
    if (selectedIds.length === 0) return
    await bulkReject.mutateAsync({ profile_ids: selectedIds, reason })
    clearSelection()
    setRejectDialogOpen(false)
  }, [selectedIds, bulkReject, clearSelection])

  const handleBulkAssign = useCallback(async (officerId: number) => {
    if (selectedIds.length === 0) return
    await bulkAssign.mutateAsync({ profile_ids: selectedIds, officer_id: officerId })
    clearSelection()
    setAssignDialogOpen(false)
  }, [selectedIds, bulkAssign, clearSelection])

  const handleExport = useCallback(() => {
    exportCsv.mutate({
      status: selectedStatuses.length > 0 ? selectedStatuses.join(",") : undefined,
      search: debouncedSearch || undefined,
      date_from: dateFrom ? format(dateFrom, "yyyy-MM-dd") : undefined,
      date_to: dateTo ? format(dateTo, "yyyy-MM-dd") : undefined,
    })
  }, [exportCsv, selectedStatuses, debouncedSearch, dateFrom, dateTo])

  // Check if any filters are active (beyond default year)
  const hasActiveFilters = selectedStatuses.length > 0 || debouncedSearch || dateFrom || dateTo
    || selectedMajorId || selectedDegreeLevel || selectedPaymentStatus
    || (selectedYear !== undefined && selectedYear !== CURRENT_YEAR)

  const isAnyLoading = bulkApprove.isPending || bulkReject.isPending || bulkAssign.isPending || exportCsv.isPending

  return (
    <PageContainer maxWidth="xl">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-3">
          <ClipboardCheck className="h-7 w-7 md:h-8 md:w-8 text-primary" aria-hidden="true" />
          <div>
            <h1 className="text-xl md:text-2xl font-bold font-display">Hồ sơ tuyển sinh</h1>
            <p className="text-sm text-muted-foreground">
              Quản lý và theo dõi hồ sơ tuyển sinh
              {totalCount > 0 && ` (${totalCount} hồ sơ)`}
            </p>
          </div>
        </div>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mt-4">
          <StatCard
            label="Tổng hồ sơ"
            value={stats.total_profiles ?? 0}
            icon={<FileText className="h-4 w-4 text-muted-foreground" />}
          />
          <StatCard
            label="Chờ duyệt"
            value={stats.submitted_count ?? 0}
            icon={<Users className="h-4 w-4 text-info-600" />}
          />
          <StatCard
            label="Đã duyệt"
            value={stats.approved_count ?? 0}
            icon={<CheckCircle2 className="h-4 w-4 text-success-600" />}
          />
          <StatCard
            label="Đã nhập học"
            value={stats.enrolled_count ?? 0}
            icon={<GraduationCap className="h-4 w-4 text-blue-600" />}
          />
          <StatCard
            label="Tỷ lệ chuyển đổi"
            value={`${stats.conversion_rate ?? 0}%`}
            icon={<TrendingUp className="h-4 w-4 text-emerald-600" />}
          />
          <StatCard
            label="TB hoàn thiện"
            value={`${stats.avg_completion ?? 0}%`}
            icon={<BarChart3 className="h-4 w-4 text-amber-600" />}
          />
        </div>
      )}

      {/* Toolbar */}
      <div className="flex flex-col gap-3 mt-4">
        {/* Row 1: Search + Primary Filters */}
        <div className="flex flex-col sm:flex-row gap-3">
          {/* Search */}
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <Input
              placeholder="Tìm kiếm theo tên, email, CCCD..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-10"
            />
            {search && (
              <Button
                variant="ghost"
                size="sm"
                className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 p-0"
                onClick={() => setSearch("")}
                aria-label="Xóa tìm kiếm"
              >
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>

          {/* Academic Year */}
          <Select
            value={selectedYear !== undefined ? String(selectedYear) : "all"}
            onValueChange={(val) => {
              setSelectedYear(val === "all" ? undefined : Number(val))
              handleFilterChange()
            }}
          >
            <SelectTrigger className="w-full sm:w-[140px]">
              <SelectValue placeholder="Năm học" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tất cả năm</SelectItem>
              {yearOptions.map((year) => (
                <SelectItem key={year} value={String(year)}>
                  {year}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Major Program */}
          <Select
            value={selectedMajorId ?? "all"}
            onValueChange={(val) => {
              setSelectedMajorId(val === "all" ? undefined : val)
              handleFilterChange()
            }}
          >
            <SelectTrigger className="w-full sm:w-[180px]">
              <SelectValue placeholder="Ngành" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tất cả ngành</SelectItem>
              {majorPrograms?.map((program: { id: number; name: string }) => (
                <SelectItem key={program.id} value={String(program.id)}>
                  {program.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Status Filter (dropdown multi-select) */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" className="w-full sm:w-auto gap-2">
                <Filter className="h-4 w-4" aria-hidden="true" />
                Trạng thái
                {selectedStatuses.length > 0 && (
                  <Badge variant="secondary" className="ml-1 h-5 px-1.5">
                    {selectedStatuses.length}
                  </Badge>
                )}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              <DropdownMenuLabel>Lọc theo trạng thái</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {STATUS_OPTIONS.map((option) => (
                <DropdownMenuCheckboxItem
                  key={option.value}
                  checked={selectedStatuses.includes(option.value)}
                  onCheckedChange={() => handleStatusToggle(option.value)}
                >
                  {option.label}
                </DropdownMenuCheckboxItem>
              ))}
              {selectedStatuses.length > 0 && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => { setSelectedStatuses([]); setActiveTab("all") }}>
                    Xóa bộ lọc
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {/* Row 2: Secondary Filters */}
        <div className="flex flex-col sm:flex-row gap-3">
          {/* Degree Level */}
          <Select
            value={selectedDegreeLevel ?? "all"}
            onValueChange={(val) => {
              setSelectedDegreeLevel(val === "all" ? undefined : val)
              handleFilterChange()
            }}
          >
            <SelectTrigger className="w-full sm:w-[160px]">
              <SelectValue placeholder="Trình độ" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tất cả trình độ</SelectItem>
              {degreeLevels?.map((level) => (
                <SelectItem key={level.code} value={level.code}>
                  {level.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Payment Status */}
          <Select
            value={selectedPaymentStatus ?? "all"}
            onValueChange={(val) => {
              setSelectedPaymentStatus(val === "all" ? undefined : val)
              handleFilterChange()
            }}
          >
            <SelectTrigger className="w-full sm:w-[180px]">
              <SelectValue placeholder="Học phí" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tất cả học phí</SelectItem>
              {PAYMENT_STATUS_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Date Range Filter */}
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" className="w-full sm:w-auto gap-2">
                <Calendar className="h-4 w-4" aria-hidden="true" />
                {dateFrom || dateTo ? (
                  <span className="text-xs">
                    {dateFrom ? format(dateFrom, "dd/MM") : "…"} -{" "}
                    {dateTo ? format(dateTo, "dd/MM") : "…"}
                  </span>
                ) : (
                  "Ngày tạo"
                )}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="end">
              <div className="flex flex-col sm:flex-row">
                <div className="p-2">
                  <p className="text-xs font-medium mb-2 text-muted-foreground">Từ ngày</p>
                  <CalendarComponent
                    mode="single"
                    selected={dateFrom}
                    onSelect={(date) => {
                      setDateFrom(date)
                      handleFilterChange()
                    }}
                    locale={vi}
                  />
                </div>
                <div className="p-2 border-t sm:border-t-0 sm:border-l">
                  <p className="text-xs font-medium mb-2 text-muted-foreground">Đến ngày</p>
                  <CalendarComponent
                    mode="single"
                    selected={dateTo}
                    onSelect={(date) => {
                      setDateTo(date)
                      handleFilterChange()
                    }}
                    locale={vi}
                  />
                </div>
              </div>
              {(dateFrom || dateTo) && (
                <div className="p-2 border-t">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="w-full"
                    onClick={() => {
                      setDateFrom(undefined)
                      setDateTo(undefined)
                      handleFilterChange()
                    }}
                  >
                    Xóa bộ lọc ngày
                  </Button>
                </div>
              )}
            </PopoverContent>
          </Popover>

          {/* Clear all filters */}
          {hasActiveFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters} className="gap-1">
              <X className="h-4 w-4" />
              Xóa bộ lọc
            </Button>
          )}
        </div>
      </div>

      {/* Status Tabs */}
      <div className="flex items-center gap-1 mt-4 overflow-x-auto pb-1" role="tablist">
        {STATUS_TABS.map((tab) => {
          const count = tabCounts?.[tab.key]
          const isActive = activeTab === tab.key
          return (
            <button
              key={tab.key}
              role="tab"
              aria-selected={isActive}
              onClick={() => handleTabClick(tab.key)}
              className={cn(
                "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium whitespace-nowrap transition-colors",
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              {tab.label}
              {count !== undefined && (
                <span className={cn(
                  "inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full text-xs font-medium",
                  isActive
                    ? "bg-primary-foreground/20 text-primary-foreground"
                    : "bg-muted text-muted-foreground"
                )}>
                  {count}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Content */}
      <div className="mt-4">
        {/* Loading state */}
        {isLoading && (
          <div className="space-y-3">
            <div className="hidden md:block rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    {Array.from({ length: 7 }).map((_, i) => (
                      <TableHead key={i}>
                        <Skeleton className="h-4 w-20" />
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Array.from({ length: 5 }).map((_, i) => (
                    <TableRow key={i}>
                      {Array.from({ length: 7 }).map((_, j) => (
                        <TableCell key={j}>
                          <Skeleton className="h-4 w-full" />
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="md:hidden grid gap-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <Card key={i}>
                  <CardHeader className="pb-2">
                    <Skeleton className="h-5 w-32" />
                    <Skeleton className="h-4 w-24" />
                  </CardHeader>
                  <CardContent>
                    <Skeleton className="h-4 w-full mb-2" />
                    <Skeleton className="h-2 w-3/4" />
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        )}

        {/* Error state */}
        {isError && (
          <Card>
            <CardContent className="p-0">
              <ErrorEmptyState message="Không thể tải danh sách hồ sơ. Vui lòng thử lại." />
            </CardContent>
          </Card>
        )}

        {/* Empty state */}
        {!isLoading && !isError && profiles.length === 0 && (
          <Card>
            <CardContent className="p-0">
              <EmptyState
                icon={<ClipboardCheck className="h-12 w-12" />}
                title={hasActiveFilters ? "Không tìm thấy kết quả" : "Chưa có hồ sơ nào"}
                description={
                  hasActiveFilters
                    ? "Thử thay đổi bộ lọc để xem kết quả khác"
                    : "Để tạo hồ sơ mới, vào trang chi tiết Lead và nhấn 'Tạo hồ sơ tuyển sinh'"
                }
                action={
                  hasActiveFilters && (
                    <Button variant="outline" onClick={clearFilters}>
                      Xóa bộ lọc
                    </Button>
                  )
                }
              />
            </CardContent>
          </Card>
        )}

        {/* Data */}
        {!isLoading && !isError && profiles.length > 0 && (
          <>
            {/* Desktop: Table View */}
            <div className={cn("hidden md:block rounded-md border", isFetching && "opacity-60")}>
              <Table>
                <TableHeader>
                  {table.getHeaderGroups().map((headerGroup) => (
                    <TableRow key={headerGroup.id}>
                      {headerGroup.headers.map((header) => (
                        <TableHead key={header.id}>
                          {header.isPlaceholder
                            ? null
                            : flexRender(header.column.columnDef.header, header.getContext())}
                        </TableHead>
                      ))}
                    </TableRow>
                  ))}
                </TableHeader>
                <TableBody>
                  {table.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      data-state={row.getIsSelected() && "selected"}
                      className="cursor-pointer"
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}>
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            {/* Mobile: Card View */}
            <div className={cn("md:hidden space-y-2", isFetching && "opacity-60")}>
              <div className="flex items-center gap-2 px-1 py-2">
                <Checkbox
                  checked={
                    table.getIsAllPageRowsSelected() ||
                    (table.getIsSomePageRowsSelected() && "indeterminate")
                  }
                  onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
                  aria-label="Chọn tất cả"
                />
                <span className="text-sm text-muted-foreground">Chọn tất cả</span>
              </div>

              {profiles.map((profile) => (
                <AdmissionCard
                  key={profile.id}
                  profile={profile}
                  isSelected={rowSelection[String(profile.id)] ?? false}
                  onSelect={(checked) => {
                    setRowSelection((prev) => ({
                      ...prev,
                      [String(profile.id)]: checked,
                    }))
                  }}
                />
              ))}
            </div>

            {/* Pagination */}
            {totalCount > pageSize && (
              <Pagination
                page={page}
                pageSize={pageSize}
                total={totalCount}
                onPageChange={setPage}
                onPageSizeChange={(size) => {
                  setPageSize(size)
                  setPage(1)
                }}
                isLoading={isFetching}
                showPageSizeSelector
                showTotal
                className="border-t mt-4"
              />
            )}
          </>
        )}
      </div>

      {/* Bulk Actions Bar */}
      <AdmissionsBulkActionsBar
        selectedCount={selectedIds.length}
        onClearSelection={clearSelection}
        onBulkApprove={handleBulkApprove}
        onBulkReject={() => setRejectDialogOpen(true)}
        onBulkAssign={() => setAssignDialogOpen(true)}
        onExport={handleExport}
        isLoading={isAnyLoading}
      />

      {/* Dialogs */}
      <BulkRejectDialog
        open={rejectDialogOpen}
        onOpenChange={setRejectDialogOpen}
        selectedCount={selectedIds.length}
        onConfirm={handleBulkReject}
        isLoading={bulkReject.isPending}
      />

      <BulkAssignDialog
        open={assignDialogOpen}
        onOpenChange={setAssignDialogOpen}
        selectedCount={selectedIds.length}
        onConfirm={handleBulkAssign}
        isLoading={bulkAssign.isPending}
      />
    </PageContainer>
  )
}

// =============================================================================
// MOBILE CARD COMPONENT - Using BaseCard System
// =============================================================================

interface AdmissionCardProps {
  profile: AdmissionProfileResponse
  isSelected: boolean
  onSelect: (checked: boolean) => void
}

function AdmissionCard({ profile, isSelected, onSelect }: AdmissionCardProps) {
  const statusConfig = STATUS_CONFIG[profile.status] ?? { label: profile.status, color: "bg-muted" }
  const eligibilityConfig = ELIGIBILITY_CONFIG[profile.eligibility_status] ?? { label: "-", color: "bg-muted" }

  return (
    <BaseCard
      selected={isSelected}
      onSelect={onSelect}
      showCheckbox
    >
      {/* Header: Name + Status Badge */}
      <BaseCardHeader
        title={
          <Link
            href={`/admissions/${profile.id}`}
            className="hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {profile.lead?.full_name ?? `Lead #${profile.lead_id}`}
          </Link>
        }
        subtitle={`Hồ sơ #${profile.id}`}
        badge={<Badge className={statusConfig.color}>{statusConfig.label}</Badge>}
      />

      {/* Body: Progress bar */}
      <CardBody>
        <div className="flex items-center gap-2">
          <Progress value={profile.completion_percent} className="h-2 flex-1" />
          <span className="text-xs text-muted-foreground w-8">
            {profile.completion_percent}%
          </span>
        </div>
      </CardBody>

      {/* Meta: Date + Eligibility */}
      <CardMeta>
        <CardTime date={profile.created_at} format="date" showIcon />
        <Badge variant="outline" className={cn("text-xs", eligibilityConfig.color)}>
          {eligibilityConfig.label}
        </Badge>
      </CardMeta>

      {/* Actions */}
      <CardActions>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="Thao tác">
              <MoreVertical className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem asChild>
              <Link href={`/admissions/${profile.id}`}>
                Xem chi tiết
              </Link>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </CardActions>
    </BaseCard>
  )
}

export default AdmissionsClient
