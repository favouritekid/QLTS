// src/app/(dashboard)/admissions/_components/AdmissionsClient.tsx
/**
 * AdmissionsClient — danh sách hồ sơ tuyển sinh ("Operations desk" v2).
 *
 * Redesign thuần presentation: metric rail · filter bar (search + Năm + popover
 * Bộ lọc + Sắp xếp + chips) · status tabs gạch chân · roster bảng + card mobile
 * (status chấm, progress ngưỡng, monogram, avatar chip) · density Thoáng/Gọn
 * (localStorage). GIỮ NGUYÊN data layer: useAdmissionsFilter (URL+localStorage),
 * TanStack table (sort + selection), SSR initialData, prefetch, bulk + permission.
 */

"use client"

import { useState, useMemo, useCallback, useEffect } from "react"
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
import { ClipboardCheck } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Skeleton } from "@/components/ui/skeleton"
import { PageContainer } from "@/components/layouts/PageContainer"
import { EmptyState, ErrorEmptyState } from "@/components/common/EmptyState"
import { Pagination } from "@/components/common/table/Pagination"
import { cn } from "@/lib/utils"
import { formatDate } from "@/lib/utils/admission-helpers"
import { hasAction } from "@/lib/admission/permissions"

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
  ADMISSION_STATUS_TABS as STATUS_TABS,
} from "@/hooks/admissions/filterDefaults"
import { admissionsApi } from "@/lib/api/admissions"
import { handleApiError, type ApiErrorResponse } from "@/lib/error-handler"
import type { AdmissionListParams, AdmissionProfileResponse, AdmissionsPage } from "@/lib/zod/admissions"

import { getColumns } from "./columns"
import { AdmissionsBulkActionsBar } from "./AdmissionsBulkActionsBar"
import { BulkRejectDialog } from "./dialogs/BulkRejectDialog"
import { BulkAssignDialog } from "./dialogs/BulkAssignDialog"
import { AdmissionsMetricRail, type MetricItem } from "./AdmissionsMetricRail"
import { AdmissionsFilterBar } from "./AdmissionsFilterBar"
import { AdmissionsStatusTabs } from "./AdmissionsStatusTabs"
import { Monogram, StatusDot, ProgressBar, EligibilityToken, RowActionsMenu } from "./roster-parts"

const CURRENT_YEAR = CURRENT_ADMISSIONS_YEAR
const DENSITY_STORAGE_KEY = "admissions:density"

type Density = "comfortable" | "compact"

/** Enter/Space kích hoạt row, bỏ qua khi focus ở element interactive bên trong. */
function activateRow(e: React.KeyboardEvent, fn: () => void) {
  if (e.key !== "Enter" && e.key !== " ") return
  const target = e.target as HTMLElement
  const inner = target.closest("button, a, input, [role='checkbox']")
  if (inner && inner !== e.currentTarget) return
  e.preventDefault()
  fn()
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
  const router = useRouter()

  // ── Filter state (URL sync + localStorage) ────────────────────────────
  const { state, handlers, hasActiveFilters, apiFilters, countFilters } = useAdmissionsFilter()

  // ── View state (local) ────────────────────────────────────────────────
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const [rejectDialogOpen, setRejectDialogOpen] = useState(false)
  const [assignDialogOpen, setAssignDialogOpen] = useState(false)
  const [rowRejectTarget, setRowRejectTarget] = useState<AdmissionProfileResponse | null>(null)

  // Density: default 'comfortable' (SSR-safe), đọc localStorage SAU mount
  // để tránh hydration mismatch.
  const [density, setDensity] = useState<Density>("comfortable")
  useEffect(() => {
    const stored = window.localStorage.getItem(DENSITY_STORAGE_KEY)
    if (stored === "compact" || stored === "comfortable") setDensity(stored)
  }, [])
  const handleDensityChange = useCallback((value: Density) => {
    setDensity(value)
    try {
      window.localStorage.setItem(DENSITY_STORAGE_KEY, value)
    } catch {
      // ignore storage errors
    }
  }, [])
  const compact = density === "compact"

  // Derive TanStack sorting from hook state
  const tableSorting: SortingState = useMemo(() => {
    if (state.sortBy === "created_at" && state.sortOrder === "desc") return []
    return [{ id: state.sortBy, desc: state.sortOrder === "desc" }]
  }, [state.sortBy, state.sortOrder])

  const handleSortingChange = useCallback(
    (updaterOrValue: SortingState | ((prev: SortingState) => SortingState)) => {
      const newSorting = typeof updaterOrValue === "function" ? updaterOrValue(tableSorting) : updaterOrValue
      if (newSorting.length > 0) {
        handlers.handleSortChange(newSorting[0].id, newSorting[0].desc ? "desc" : "asc")
      } else {
        handlers.handleSortChange("created_at", "desc")
      }
    },
    [tableSorting, handlers],
  )

  // ── Reference data ────────────────────────────────────────────────────
  const { data: majorPrograms } = useAdmissionPrograms()
  const { data: academicYears } = useAcademicYears()
  const { data: degreeLevels } = useDegreeLevelsPublic()

  const yearOptions = useMemo(() => {
    if (academicYears && academicYears.length > 0) return academicYears
    return [CURRENT_YEAR + 1, CURRENT_YEAR, CURRENT_YEAR - 1]
  }, [academicYears])

  // ── Data queries ──────────────────────────────────────────────────────
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

  // Đổi bộ lọc/tab/trang → xóa selection để không "rò rỉ" lựa chọn vô hình sang
  // view khác (apiFilters đổi tham chiếu khi bất kỳ filter/page/sort đổi).
  useEffect(() => {
    setRowSelection({})
  }, [apiFilters])

  // ── Claim handler ─────────────────────────────────────────────────────
  const handleClaimFromList = useCallback(
    async (profile: AdmissionProfileResponse) => {
      if (profile.version == null) return
      try {
        await admissionsApi.claimAdmissionProfile(profile.id, { version: profile.version })
        toast.success("Đã nhận duyệt hồ sơ")
        queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() })
      } catch (error) {
        handleApiError(error as AxiosError<ApiErrorResponse>, { context: "nhận duyệt hồ sơ" })
      }
    },
    [queryClient],
  )

  const openProfile = useCallback(
    (id: number) => router.push(`/admissions/${id}`),
    [router],
  )

  // ── Single-row approve/reject (row menu) — gated by hasAction ──────────
  const handleRowApprove = useCallback(
    async (profile: AdmissionProfileResponse) => {
      try {
        await bulkApprove.mutateAsync({
          items: [{ profile_id: profile.id, version: profile.version ?? 1 }],
        })
      } catch (error) {
        // Hook đã toast theo result 2xx; catch này phủ path ném (network/HTTP lỗi).
        handleApiError(error as AxiosError<ApiErrorResponse>, { context: "phê duyệt hồ sơ" })
      }
    },
    [bulkApprove],
  )

  // Reject cần lý do → mở dialog cho đúng 1 hồ sơ.
  const requestRowReject = useCallback((profile: AdmissionProfileResponse) => {
    setRowRejectTarget(profile)
  }, [])

  const handleRowReject = useCallback(
    async (reason: string) => {
      if (!rowRejectTarget) return
      await bulkReject.mutateAsync({
        items: [{ profile_id: rowRejectTarget.id, version: rowRejectTarget.version ?? 1 }],
        reason,
      })
      setRowRejectTarget(null)
    },
    [rowRejectTarget, bulkReject],
  )

  // ── Table instance ────────────────────────────────────────────────────
  const columns = useMemo(
    () =>
      getColumns({
        onClaim: handleClaimFromList,
        onApprove: handleRowApprove,
        onReject: requestRowReject,
        density,
      }),
    [handleClaimFromList, handleRowApprove, requestRowReject, density],
  )

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
    // `data` ở deps: re-derive khi refetch nền đổi profiles/available_actions → tránh
    // bulkPermissions stale (table identity ổn định nên không tự recompute).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [table, rowSelection, data])

  const selectedIds = useMemo(() => selectedProfiles.map((p) => p.id), [selectedProfiles])

  // Backend-driven bulk permissions: chỉ lộ action khi MỌI dòng chọn đều cho phép.
  const bulkPermissions = useMemo(() => {
    if (selectedProfiles.length === 0) {
      return { canApprove: false, canReject: false, canAssign: false }
    }
    const every = (action: string) => selectedProfiles.every((p) => hasAction(p, action))
    return {
      canApprove: every("approve"),
      canReject: every("reject"),
      canAssign: every("assign_officer"),
    }
  }, [selectedProfiles])

  const clearSelection = useCallback(() => setRowSelection({}), [])

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

  // ── Metric rail items (từ useAdmissionStats) ──────────────────────────
  const metricItems: MetricItem[] = useMemo(() => {
    if (!stats) return []
    const fmt = (n: number) => n.toLocaleString("vi-VN")
    return [
      { key: "total", label: "Tổng hồ sơ", value: fmt(stats.total_profiles ?? 0), dot: "bg-primary" },
      { key: "pending", label: "Chờ duyệt", value: fmt(stats.submitted_count ?? 0), dot: "bg-info-500" },
      { key: "approved", label: "Đã duyệt", value: fmt(stats.approved_count ?? 0), dot: "bg-success-500" },
      { key: "enrolled", label: "Đã nhập học", value: fmt(stats.enrolled_count ?? 0), dot: "bg-blue-500" },
      { key: "conversion", label: "Tỷ lệ chuyển đổi", value: `${stats.conversion_rate ?? 0}%`, dot: "bg-emerald-500", trend: true },
      { key: "completion", label: "TB hoàn thiện", value: `${stats.avg_completion ?? 0}%`, dot: "bg-amber-500" },
    ]
  }, [stats])

  // ── Bulk actions ──────────────────────────────────────────────────────
  const handleBulkApprove = useCallback(async () => {
    if (selectedProfiles.length === 0) return
    await bulkApprove.mutateAsync({
      items: selectedProfiles.map((p) => ({ profile_id: p.id, version: p.version ?? 1 })),
    })
    clearSelection()
  }, [selectedProfiles, bulkApprove, clearSelection])

  const handleBulkReject = useCallback(
    async (reason: string) => {
      if (selectedProfiles.length === 0) return
      await bulkReject.mutateAsync({
        items: selectedProfiles.map((p) => ({ profile_id: p.id, version: p.version ?? 1 })),
        reason,
      })
      clearSelection()
      setRejectDialogOpen(false)
    },
    [selectedProfiles, bulkReject, clearSelection],
  )

  const handleBulkAssign = useCallback(
    async (officerId: number) => {
      if (selectedIds.length === 0) return
      await bulkAssign.mutateAsync({ profile_ids: selectedIds, officer_id: officerId })
      clearSelection()
      setAssignDialogOpen(false)
    },
    [selectedIds, bulkAssign, clearSelection],
  )

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

  const allVisibleSelected =
    table.getIsAllPageRowsSelected() || (table.getIsSomePageRowsSelected() && "indeterminate")

  return (
    <PageContainer maxWidth="xl">
      <div className="space-y-5">
        {/* Header */}
        <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex size-11 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <ClipboardCheck className="size-6" aria-hidden="true" />
            </div>
            <div>
              <h1 className="font-display text-xl font-bold tracking-tight md:text-2xl">Hồ sơ tuyển sinh</h1>
              <p className="text-sm text-muted-foreground">
                Quản lý và theo dõi hồ sơ tuyển sinh
                {totalCount > 0 && (
                  <>
                    {" · "}
                    <span className="font-medium tabular-nums text-foreground">{totalCount}</span> hồ sơ
                  </>
                )}
              </p>
            </div>
          </div>

          <div className="inline-flex self-start rounded-full border border-border bg-card p-0.5 sm:self-auto">
            {(["comfortable", "compact"] as const).map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => handleDensityChange(d)}
                aria-pressed={density === d}
                className={cn(
                  "rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                  density === d ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {d === "comfortable" ? "Thoáng" : "Gọn"}
              </button>
            ))}
          </div>
        </header>

        {/* Metric rail */}
        {metricItems.length > 0 && <AdmissionsMetricRail items={metricItems} />}

        {/* Filter bar */}
        <AdmissionsFilterBar
          search={state.search}
          onSearchChange={handlers.handleSearchChange}
          academicYear={state.academicYear}
          yearOptions={yearOptions}
          onYearChange={handlers.handleYearChange}
          statusFilters={state.statusFilters}
          onStatusChange={handlers.handleStatusChange}
          majorFilter={state.majorFilter}
          majorPrograms={majorPrograms}
          onMajorChange={handlers.handleMajorChange}
          degreeLevelFilter={state.degreeLevelFilter}
          degreeLevels={degreeLevels}
          onDegreeLevelChange={handlers.handleDegreeLevelChange}
          paymentStatusFilter={state.paymentStatusFilter}
          onPaymentStatusChange={handlers.handlePaymentStatusChange}
          dateFrom={state.dateFrom}
          dateTo={state.dateTo}
          onDateFromChange={handlers.handleDateFromChange}
          onDateToChange={handlers.handleDateToChange}
          sortBy={state.sortBy}
          sortOrder={state.sortOrder}
          onSortChange={handlers.handleSortChange}
          onReset={handlers.resetFilters}
        />

        {/* Status tabs */}
        <AdmissionsStatusTabs
          tabs={STATUS_TABS}
          activeTab={state.activeTab}
          counts={tabCounts}
          onTabClick={handlers.handleTabClick}
        />

        {/* Content */}
        {isLoading ? (
          <LoadingState />
        ) : isError ? (
          <div className="rounded-2xl border border-border bg-card">
            <ErrorEmptyState message="Không thể tải danh sách hồ sơ. Vui lòng thử lại." />
          </div>
        ) : profiles.length === 0 ? (
          <div className="rounded-2xl border border-border bg-card">
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
          </div>
        ) : (
          <>
            {/* Desktop: roster table */}
            <div
              className={cn(
                "hidden overflow-hidden rounded-2xl border border-border bg-card shadow-xs md:block",
                isFetching && "opacity-60",
              )}
            >
              <table className="w-full text-sm">
                <thead>
                  {table.getHeaderGroups().map((headerGroup) => (
                    <tr
                      key={headerGroup.id}
                      className="border-b border-border bg-muted/30 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground"
                    >
                      {headerGroup.headers.map((header) => (
                        <th key={header.id} className="px-3 py-3 font-medium">
                          {header.isPlaceholder
                            ? null
                            : flexRender(header.column.columnDef.header, header.getContext())}
                        </th>
                      ))}
                    </tr>
                  ))}
                </thead>
                <tbody>
                  {table.getRowModel().rows.map((row) => {
                    const profileId = row.original.id
                    const sel = row.getIsSelected()
                    return (
                      <tr
                        key={row.id}
                        data-state={sel && "selected"}
                        role="link"
                        tabIndex={0}
                        aria-label={`Hồ sơ ${row.original.lead?.full_name ?? `Lead #${row.original.lead_id}`}`}
                        onClick={() => openProfile(profileId)}
                        onKeyDown={(e) => activateRow(e, () => openProfile(profileId))}
                        className={cn(
                          "group cursor-pointer border-b border-l-2 border-border/60 border-l-transparent outline-none transition-colors last:border-b-0 hover:bg-muted/40 hover:border-l-primary focus-visible:bg-muted/40",
                          sel && "border-l-primary bg-primary/5",
                        )}
                      >
                        {row.getVisibleCells().map((cell) => (
                          <td key={cell.id} className={cn("px-3 align-middle", compact ? "py-2" : "py-3")}>
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        ))}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobile: roster tiles */}
            <div className={cn("space-y-2 md:hidden", isFetching && "opacity-60")}>
              <div className="flex items-center gap-2 px-1 py-1">
                <Checkbox
                  checked={allVisibleSelected}
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
                  onSelect={(checked) => table.getRow(String(profile.id)).toggleSelected(checked)}
                  onClaim={handleClaimFromList}
                  onApprove={handleRowApprove}
                  onReject={requestRowReject}
                  onOpen={() => openProfile(profile.id)}
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
                className="border-t pt-4"
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

      {/* Single-row reject (mở từ row menu) — tái dùng dialog có lý do */}
      <BulkRejectDialog
        open={!!rowRejectTarget}
        onOpenChange={(open) => {
          if (!open) setRowRejectTarget(null)
        }}
        selectedCount={1}
        onConfirm={handleRowReject}
        isLoading={bulkReject.isPending}
      />
    </PageContainer>
  )
}

// =============================================================================
// LOADING STATE
// =============================================================================

function LoadingState() {
  return (
    <div className="space-y-3">
      <div className="hidden rounded-2xl border border-border bg-card p-4 md:block">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 py-2.5">
            <Skeleton className="size-9 shrink-0 rounded-xl" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-3.5 w-40" />
              <Skeleton className="h-3 w-24" />
            </div>
            <Skeleton className="hidden h-2 w-28 sm:block" />
            <Skeleton className="hidden h-5 w-20 rounded-full lg:block" />
          </div>
        ))}
      </div>
      <div className="space-y-2 md:hidden">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="rounded-2xl border border-border bg-card p-4">
            <div className="flex items-center gap-3">
              <Skeleton className="size-9 shrink-0 rounded-xl" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-24" />
              </div>
            </div>
            <Skeleton className="mt-3 h-2 w-full" />
          </div>
        ))}
      </div>
    </div>
  )
}

// =============================================================================
// MOBILE CARD
// =============================================================================

interface AdmissionCardProps {
  profile: AdmissionProfileResponse
  isSelected: boolean
  onSelect: (checked: boolean) => void
  onClaim: (profile: AdmissionProfileResponse) => void
  onApprove: (profile: AdmissionProfileResponse) => void
  onReject: (profile: AdmissionProfileResponse) => void
  onOpen: () => void
}

function AdmissionCard({ profile, isSelected, onSelect, onClaim, onApprove, onReject, onOpen }: AdmissionCardProps) {
  const name = profile.lead?.full_name ?? `Lead #${profile.lead_id}`
  return (
    <article
      role="link"
      tabIndex={0}
      aria-label={`Hồ sơ ${name}`}
      onClick={onOpen}
      onKeyDown={(e) => activateRow(e, onOpen)}
      className={cn(
        "rounded-2xl border bg-card p-4 shadow-xs outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
        isSelected ? "border-primary/40 bg-primary/5" : "border-border",
      )}
    >
      <div className="flex items-start gap-3">
        <Checkbox
          checked={isSelected}
          onCheckedChange={(value) => onSelect(!!value)}
          onClick={(e) => e.stopPropagation()}
          aria-label={`Chọn ${name}`}
          className="mt-0.5"
        />
        <Monogram name={name} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <Link
                href={`/admissions/${profile.id}`}
                onClick={(e) => e.stopPropagation()}
                className="block truncate font-display font-semibold text-foreground hover:underline"
              >
                {name}
              </Link>
              <div className="truncate text-xs tabular-nums text-muted-foreground">
                #{profile.id} · {profile.program_name ?? "—"}
              </div>
            </div>
            <StatusDot status={profile.status} />
          </div>

          <div className="mt-3">
            <ProgressBar value={profile.completion_percent} />
          </div>

          <div className="mt-3 flex items-center justify-between gap-2">
            <span className="text-xs tabular-nums text-muted-foreground">{formatDate(profile.created_at)}</span>
            <div className="flex items-center gap-2">
              <EligibilityToken status={profile.eligibility_status} />
              <RowActionsMenu profile={profile} onClaim={onClaim} onApprove={onApprove} onReject={onReject} />
            </div>
          </div>
        </div>
      </div>
    </article>
  )
}

export default AdmissionsClient
