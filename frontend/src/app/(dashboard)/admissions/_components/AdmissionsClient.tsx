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
 * - URL sync + localStorage persistence (via useAdmissionsFilter)
 * - Next page prefetch for instant pagination
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
import { useQueryClient } from "@tanstack/react-query"
import { AxiosError } from "axios"
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
import { toast } from "sonner"

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
  useAdmissionsFilter,
  useAdmissionPrograms,
  admissionsKeys,
  useBulkApproveAdmissions,
  useBulkRejectAdmissions,
  useBulkAssignAdmissions,
  useExportAdmissions,
} from "@/hooks/admissions"
import {
  areAdmissionsListParamsEqual,
  CURRENT_ADMISSIONS_YEAR,
} from "@/hooks/admissions/filterDefaults"
import { admissionsApi } from "@/lib/api/admissions"
import { handleApiError, type ApiErrorResponse } from "@/lib/error-handler"
import type { AdmissionListParams, AdmissionProfileResponse, AdmissionsPage } from "@/lib/zod/admissions"
import { getColumns, STATUS_CONFIG, ELIGIBILITY_CONFIG } from "./columns"
import { AdmissionsBulkActionsBar } from "./AdmissionsBulkActionsBar"
import { BulkRejectDialog } from "./dialogs/BulkRejectDialog"
import { BulkAssignDialog } from "./dialogs/BulkAssignDialog"

// =============================================================================
// CONSTANTS
// =============================================================================

const CURRENT_YEAR = CURRENT_ADMISSIONS_YEAR

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

/** Tab definitions - group statuses for quick filtering.
 *
 * `approved` vs `confirmed`: the applicant still has to tap the magic link
 * before enrollment — keeping the two tabs separate lets officers spot
 * profiles that are stuck waiting on the applicant without hunting through
 * a mixed "Đã duyệt" bucket. `overridden` stays with `approved` because it's
 * still an admin-driven state awaiting enroll.
 */
const STATUS_TABS = [
  { key: "all", label: "Tất cả", statuses: [] as string[] },
  { key: "draft", label: "Nháp", statuses: ["draft"] },
  { key: "pending", label: "Chờ duyệt", statuses: ["submitted", "resubmitted"] },
  { key: "approved", label: "Đã duyệt", statuses: ["approved", "overridden"] },
  { key: "confirmed", label: "Đã xác nhận", statuses: ["confirmed"] },
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
// DATE HELPERS
// =============================================================================

/** Parse yyyy-MM-dd string to Date (noon to avoid timezone issues) */
function parseDate(str: string): Date | undefined {
  if (!str) return undefined
  return new Date(str + "T12:00:00")
}

/** Format Date to dd/MM display string */
function formatShortDate(str: string): string {
  if (!str) return "…"
  // str is "yyyy-MM-dd"
  return str.slice(8, 10) + "/" + str.slice(5, 7)
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

interface AdmissionsClientProps {
  initialData?: AdmissionsPage
  initialQueryParams?: AdmissionListParams
}

export function AdmissionsClient({ initialData, initialQueryParams }: AdmissionsClientProps) {
  const queryClient = useQueryClient()

  // ── Filter state (URL sync + localStorage) ────────────────────────────
  const { state, handlers, hasActiveFilters, apiFilters, countFilters } = useAdmissionsFilter()

  // ── Table state (local only — not persisted) ──────────────────────────
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const [rejectDialogOpen, setRejectDialogOpen] = useState(false)
  const [assignDialogOpen, setAssignDialogOpen] = useState(false)

  // Derive TanStack sorting from hook state
  const tableSorting: SortingState = useMemo(() => {
    if (state.sortBy === "created_at" && state.sortOrder === "desc") return []
    return [{ id: state.sortBy, desc: state.sortOrder === "desc" }]
  }, [state.sortBy, state.sortOrder])

  const handleSortingChange = useCallback(
    (updaterOrValue: SortingState | ((prev: SortingState) => SortingState)) => {
      const newSorting =
        typeof updaterOrValue === "function" ? updaterOrValue(tableSorting) : updaterOrValue
      if (newSorting.length > 0) {
        handlers.handleSortChange(newSorting[0].id, newSorting[0].desc ? "desc" : "asc")
      } else {
        handlers.handleSortChange("created_at", "desc")
      }
    },
    [tableSorting, handlers],
  )

  // ── Reference data queries ────────────────────────────────────────────
  const { data: majorPrograms } = useAdmissionPrograms()
  const { data: academicYears } = useAcademicYears()
  const { data: degreeLevels } = useDegreeLevelsPublic()

  const yearOptions = useMemo(() => {
    if (academicYears && academicYears.length > 0) return academicYears
    return [CURRENT_YEAR + 1, CURRENT_YEAR, CURRENT_YEAR - 1]
  }, [academicYears])

  // ── Data queries ──────────────────────────────────────────────────────
  // Only attach SSR data while the current query still matches the server query.
  // After localStorage hydration or user edits, a new query must fetch its own data.
  const safeInitialData = areAdmissionsListParamsEqual(apiFilters, initialQueryParams) ? initialData : undefined
  const { data, isLoading, isError, isFetching } = useListAdmissions(apiFilters, { initialData: safeInitialData })
  const { data: statusCounts } = useAdmissionStatusCounts(countFilters)
  const { data: stats } = useAdmissionStats(state.academicYear)

  // Mutations
  const bulkApprove = useBulkApproveAdmissions()
  const bulkReject = useBulkRejectAdmissions()
  const bulkAssign = useBulkAssignAdmissions()
  const exportCsv = useExportAdmissions()

  const profiles = data?.profiles ?? []
  const totalCount = data?.total_count ?? 0

  // ── Prefetch next page ────────────────────────────────────────────────
  useEffect(() => {
    if (data) {
      const totalPages = Math.ceil(totalCount / state.pageSize)
      if (state.page < totalPages) {
        queryClient.prefetchQuery({
          queryKey: admissionsKeys.list({ ...apiFilters, page: state.page + 1 } as Record<string, unknown>),
          queryFn: () => admissionsApi.listAdmissions({ ...apiFilters, page: state.page + 1 }),
          staleTime: 30_000,
        })
      }
    }
  }, [state.page, state.pageSize, totalCount, apiFilters, queryClient, data])

  // ── Claim handler (list view) ────────────────────────────────────────
  const handleClaimFromList = useCallback(async (profile: AdmissionProfileResponse) => {
    if (profile.version == null) return
    try {
      await admissionsApi.claimAdmissionProfile(profile.id, { version: profile.version })
      toast.success("Đã nhận duyệt hồ sơ")
      queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() })
    } catch (error) {
      handleApiError(error as AxiosError<ApiErrorResponse>, { context: "nhận duyệt hồ sơ" })
    }
  }, [queryClient])

  // ── Table instance ────────────────────────────────────────────────────
  const columns = useMemo(() => getColumns({
    onClaim: handleClaimFromList,
  }), [handleClaimFromList])

  const table = useReactTable({
    data: profiles,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    onSortingChange: handleSortingChange,
    onRowSelectionChange: setRowSelection,
    enableRowSelection: true,
    state: { sorting: tableSorting, rowSelection },
    getRowId: (row) => String(row.id),
  })

  const selectedProfiles = useMemo(() => {
    return table.getSelectedRowModel().rows.map((row) => row.original)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [table, rowSelection])

  const selectedIds = useMemo(() => {
    return selectedProfiles.map((p) => p.id)
  }, [selectedProfiles])

  // Backend-driven bulk permissions: a bulk action is exposed only when EVERY
  // selected row grants it. One profile without `approve` collapses the whole
  // selection — avoids triggering a 404 on the first ineligible item.
  const bulkPermissions = useMemo(() => {
    if (selectedProfiles.length === 0) {
      return { canApprove: false, canReject: false, canAssign: false }
    }
    const every = (action: string) =>
      selectedProfiles.every((p) => p.available_actions?.includes(action) ?? false)
    return {
      canApprove: every("approve"),
      canReject: every("reject"),
      canAssign: every("assign_officer"),
    }
  }, [selectedProfiles])

  const clearSelection = useCallback(() => {
    setRowSelection({})
  }, [])

  // ── Status toggle handler (dropdown multi-select) ─────────────────────
  const handleStatusToggle = useCallback((status: string) => {
    const newStatuses = state.statusFilters.includes(status)
      ? state.statusFilters.filter((s) => s !== status)
      : [...state.statusFilters, status]
    handlers.handleStatusChange(newStatuses)
  }, [state.statusFilters, handlers])

  // ── Tab counts ────────────────────────────────────────────────────────
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

  // ── Bulk actions ──────────────────────────────────────────────────────
  const handleBulkApprove = useCallback(async () => {
    if (selectedProfiles.length === 0) return
    await bulkApprove.mutateAsync({
      items: selectedProfiles.map((p) => ({ profile_id: p.id, version: p.version ?? 1 })),
    })
    clearSelection()
  }, [selectedProfiles, bulkApprove, clearSelection])

  const handleBulkReject = useCallback(async (reason: string) => {
    if (selectedProfiles.length === 0) return
    await bulkReject.mutateAsync({
      items: selectedProfiles.map((p) => ({ profile_id: p.id, version: p.version ?? 1 })),
      reason,
    })
    clearSelection()
    setRejectDialogOpen(false)
  }, [selectedProfiles, bulkReject, clearSelection])

  const handleBulkAssign = useCallback(async (officerId: number) => {
    if (selectedIds.length === 0) return
    await bulkAssign.mutateAsync({ profile_ids: selectedIds, officer_id: officerId })
    clearSelection()
    setAssignDialogOpen(false)
  }, [selectedIds, bulkAssign, clearSelection])

  const handleExport = useCallback(() => {
    exportCsv.mutate({
      status: state.statusFilters.length > 0 ? state.statusFilters.join(",") : undefined,
      search: state.search || undefined,
      major_id: state.majorFilter || undefined,
      academic_year: state.academicYear || undefined,
      degree_level: state.degreeLevelFilter || undefined,
      payment_status: state.paymentStatusFilter || undefined,
      date_from: state.dateFrom || undefined,
      date_to: state.dateTo || undefined,
    })
  }, [exportCsv, state])

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
              value={state.search}
              onChange={(e) => handlers.handleSearchChange(e.target.value)}
              className="pl-10"
            />
            {state.search && (
              <Button
                variant="ghost"
                size="sm"
                className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 p-0"
                onClick={() => handlers.handleSearchChange("")}
                aria-label="Xóa tìm kiếm"
              >
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>

          {/* Academic Year */}
          <Select
            value={state.academicYear !== undefined ? String(state.academicYear) : "all"}
            onValueChange={(val) => handlers.handleYearChange(val === "all" ? undefined : Number(val))}
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
            value={state.majorFilter || "all"}
            onValueChange={(val) => handlers.handleMajorChange(val === "all" ? "" : val)}
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
                {state.statusFilters.length > 0 && (
                  <Badge variant="secondary" className="ml-1 h-5 px-1.5">
                    {state.statusFilters.length}
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
                  checked={state.statusFilters.includes(option.value)}
                  onCheckedChange={() => handleStatusToggle(option.value)}
                >
                  {option.label}
                </DropdownMenuCheckboxItem>
              ))}
              {state.statusFilters.length > 0 && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => handlers.handleStatusChange([])}>
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
            value={state.degreeLevelFilter || "all"}
            onValueChange={(val) => handlers.handleDegreeLevelChange(val === "all" ? "" : val)}
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
            value={state.paymentStatusFilter || "all"}
            onValueChange={(val) => handlers.handlePaymentStatusChange(val === "all" ? "" : val)}
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
                {state.dateFrom || state.dateTo ? (
                  <span className="text-xs">
                    {formatShortDate(state.dateFrom)} -{" "}
                    {formatShortDate(state.dateTo)}
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
                    selected={parseDate(state.dateFrom)}
                    onSelect={(date) =>
                      handlers.handleDateFromChange(date ? format(date, "yyyy-MM-dd") : "")
                    }
                    locale={vi}
                  />
                </div>
                <div className="p-2 border-t sm:border-t-0 sm:border-l">
                  <p className="text-xs font-medium mb-2 text-muted-foreground">Đến ngày</p>
                  <CalendarComponent
                    mode="single"
                    selected={parseDate(state.dateTo)}
                    onSelect={(date) =>
                      handlers.handleDateToChange(date ? format(date, "yyyy-MM-dd") : "")
                    }
                    locale={vi}
                  />
                </div>
              </div>
              {(state.dateFrom || state.dateTo) && (
                <div className="p-2 border-t">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="w-full"
                    onClick={() => {
                      handlers.handleDateFromChange("")
                      handlers.handleDateToChange("")
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
            <Button variant="ghost" size="sm" onClick={handlers.resetFilters} className="gap-1">
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
          const isActive = state.activeTab === tab.key
          return (
            <button
              key={tab.key}
              role="tab"
              aria-selected={isActive}
              onClick={() => handlers.handleTabClick(tab.key)}
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
                    <Button variant="outline" onClick={handlers.resetFilters}>
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
            {totalCount > state.pageSize && (
              <Pagination
                page={state.page}
                pageSize={state.pageSize}
                total={totalCount}
                onPageChange={handlers.setPage}
                isLoading={isFetching}
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
        canApprove={bulkPermissions.canApprove}
        canReject={bulkPermissions.canReject}
        canAssign={bulkPermissions.canAssign}
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
