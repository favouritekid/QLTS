// src/app/(dashboard)/admissions/_components/AdmissionsFilterBar.tsx
/**
 * Filter bar cho trang danh sách hồ sơ.
 *
 * Bố cục (chốt Q4/Q5):
 * - Ngoài: Search (command input) · Năm (dropdown) · "Bộ lọc" (popover) · Sắp xếp (dropdown).
 * - Trong popover "Bộ lọc": Trạng thái (multi) · Ngành/Trình độ/Học phí (native select,
 *   tránh overlay lồng trong Popover) · Khoảng ngày (CalendarComponent, giữ như cũ).
 * - Active chips: gỡ từng lọc đang bật + "Xóa tất cả".
 *
 * Thuần trình bày — mọi thay đổi đẩy qua handler thật của useAdmissionsFilter.
 */

"use client"

import { useEffect, useMemo, useState } from "react"
import { format } from "date-fns"
import { vi } from "date-fns/locale"
import { ArrowUpDown, Check, ChevronDown, Search, SlidersHorizontal, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import { Calendar as CalendarComponent } from "@/components/ui/calendar"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"
import { ADMISSION_STATUS_CONFIG, getStatusDotColor } from "@/lib/status-config"
import { CURRENT_ADMISSIONS_YEAR } from "@/hooks/admissions/filterDefaults"
import { useAuth } from "@/hooks/useAuth"
import { useAdminUsersList } from "@/hooks/useAdminUsers"
import { useOrganizationUnits } from "@/hooks/useOrganization"
import {
  isAdmin as checkIsAdmin,
  canFilterByOfficer as checkCanFilterByOfficer,
} from "@/lib/utils/permissions"

// Workflow order; LABELS đến từ ADMISSION_STATUS_CONFIG (single source) nên nhãn
// checkbox không bao giờ lệch nhãn chip lọc (statusLabel cũng đọc cùng config).
const STATUS_ORDER: readonly string[] = [
  "draft",
  "submitted",
  "resubmitted",
  "reviewing",
  "approved",
  "admitted",
  "waitlisted",
  "result_published",
  "rejected",
  "revision_requested",
  "confirmed",
  "overridden",
  "enrolled",
  "withdrawn",
]
// Append bất kỳ status có trong config nhưng thiếu trong thứ tự tường minh, để
// status mới của backend vẫn lọc được thay vì bị bỏ sót âm thầm.
const STATUS_OPTIONS: { value: string; label: string }[] = [
  ...STATUS_ORDER,
  ...Object.keys(ADMISSION_STATUS_CONFIG).filter((s) => !STATUS_ORDER.includes(s)),
].map((value) => ({ value, label: statusLabel(value) }))

const PAYMENT_OPTIONS: readonly { value: string; label: string }[] = [
  { value: "paid", label: "Đã thanh toán" },
  { value: "unpaid", label: "Chưa thanh toán" },
  { value: "partial", label: "Thanh toán một phần" },
  { value: "no_fee", label: "Chưa có học phí" },
  { value: "overdue", label: "Quá hạn" },
]

const SORT_OPTIONS: readonly { by: string; order: "asc" | "desc"; label: string }[] = [
  { by: "created_at", order: "desc", label: "Mới nhất" },
  { by: "created_at", order: "asc", label: "Cũ nhất" },
  { by: "full_name", order: "asc", label: "Tên A → Z" },
  { by: "full_name", order: "desc", label: "Tên Z → A" },
  { by: "remaining_hk1", order: "desc", label: "Còn lại nhiều nhất" },
  { by: "remaining_hk1", order: "asc", label: "Còn lại ít nhất" },
]

/** Toggle a value in a string[] (copy of LeadFilterPanel helper). */
function toggleId(arr: string[], value: string): string[] {
  return arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value]
}

const NATIVE_SELECT_CLASS =
  "h-10 w-full rounded-md border border-border bg-card px-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring md:h-9"

function parseDate(str: string): Date | undefined {
  if (!str) return undefined
  return new Date(str + "T12:00:00")
}

function fmtShort(str: string): string {
  if (!str) return "…"
  return str.slice(8, 10) + "/" + str.slice(5, 7)
}

function statusLabel(status: string): string {
  return ADMISSION_STATUS_CONFIG[status]?.label ?? status
}

export interface AdmissionsFilterBarProps {
  search: string
  onSearchChange: (value: string) => void
  academicYear: number | undefined
  yearOptions: number[]
  onYearChange: (year: number | undefined) => void
  statusFilters: string[]
  onStatusChange: (statuses: string[]) => void
  majorFilter: string
  majorPrograms: { id: number; name: string }[] | undefined
  onMajorChange: (majorId: string) => void
  degreeLevelFilter: string
  degreeLevels: { code: string; name: string }[] | undefined
  onDegreeLevelChange: (level: string) => void
  paymentStatusFilter: string
  onPaymentStatusChange: (status: string) => void
  dateFrom: string
  dateTo: string
  onDateFromChange: (date: string) => void
  onDateToChange: (date: string) => void
  sortBy: string
  sortOrder: "asc" | "desc"
  onSortChange: (sortBy: string, sortOrder: "asc" | "desc") => void
  // Coordination filters (admin/manager) — Admission List v2
  officerFilters: string[]
  onOfficerChange: (officerIds: string[]) => void
  unitId: string
  onUnitIdChange: (unitId: string) => void
  reviewerFilters: string[]
  onReviewerChange: (reviewerIds: string[]) => void
  unassigned: boolean
  onUnassignedChange: (unassigned: boolean) => void
  onReset: () => void
}

export function AdmissionsFilterBar(props: AdmissionsFilterBarProps) {
  const {
    search,
    onSearchChange,
    academicYear,
    yearOptions,
    onYearChange,
    statusFilters,
    onStatusChange,
    majorFilter,
    majorPrograms,
    onMajorChange,
    degreeLevelFilter,
    degreeLevels,
    onDegreeLevelChange,
    paymentStatusFilter,
    onPaymentStatusChange,
    dateFrom,
    dateTo,
    onDateFromChange,
    onDateToChange,
    sortBy,
    sortOrder,
    onSortChange,
    officerFilters,
    onOfficerChange,
    unitId,
    onUnitIdChange,
    reviewerFilters,
    onReviewerChange,
    unassigned,
    onUnassignedChange,
    onReset,
  } = props

  // ── Coordination filter data (admin/manager) — fetched internally like
  //    LeadFilterPanel so chip labels resolve here. UX-only role gates; backend
  //    enforces real scope via _resolve_coordination_filters.
  const { user } = useAuth()
  const [isMounted, setIsMounted] = useState(false)
  useEffect(() => setIsMounted(true), [])
  const isAdminFlag = isMounted && checkIsAdmin(user)
  const canFilterByOfficerFlag = isMounted && checkCanFilterByOfficer(user)
  const showAssignmentGroup = canFilterByOfficerFlag || isAdminFlag

  const [officerSearch, setOfficerSearch] = useState("")
  const [debouncedOfficerSearch, setDebouncedOfficerSearch] = useState("")
  useEffect(() => {
    const t = setTimeout(() => setDebouncedOfficerSearch(officerSearch), 300)
    return () => clearTimeout(t)
  }, [officerSearch])
  const { data: officersData } = useAdminUsersList(
    {
      page: 1,
      page_size: 100,
      status: "active",
      role: "officer",
      // Manager chỉ lọc trong đơn vị mình (BE cũng AND own-unit) → chỉ liệt kê
      // officer cùng đơn vị, tránh chọn officer khác unit ra 0 dòng khó hiểu.
      // Admin (không unit) thấy toàn bộ.
      ...(!isAdminFlag && user?.unit_id ? { unit_id: user.unit_id } : {}),
      ...(debouncedOfficerSearch && { search: debouncedOfficerSearch }),
    },
    { enabled: canFilterByOfficerFlag },
  )
  const officers = officersData?.users || []
  const officersTotalCount = officersData?.total_count ?? 0
  const officersTruncated = officersTotalCount > officers.length

  const [reviewerSearch, setReviewerSearch] = useState("")
  const [debouncedReviewerSearch, setDebouncedReviewerSearch] = useState("")
  useEffect(() => {
    const t = setTimeout(() => setDebouncedReviewerSearch(reviewerSearch), 300)
    return () => clearTimeout(t)
  }, [reviewerSearch])
  // Reviewers = manager + admin (admin can also be assigned_reviewer_id).
  const { data: reviewersData } = useAdminUsersList(
    {
      page: 1,
      page_size: 100,
      status: "active",
      role: "manager,admin",
      ...(debouncedReviewerSearch && { search: debouncedReviewerSearch }),
    },
    { enabled: canFilterByOfficerFlag },
  )
  const reviewers = reviewersData?.users || []
  const reviewersTotalCount = reviewersData?.total_count ?? 0
  const reviewersTruncated = reviewersTotalCount > reviewers.length

  const { data: organizationUnits = [] } = useOrganizationUnits()
  const flatUnits = useMemo(() => {
    const result: { id: number; name: string; depth: number }[] = []
    function walk(units: typeof organizationUnits, depth: number) {
      for (const unit of units) {
        result.push({ id: unit.id, name: unit.name, depth })
        if (unit.children?.length) walk(unit.children, depth + 1)
      }
    }
    walk(organizationUnits, 0)
    return result
  }, [organizationUnits])

  const toggleStatus = (value: string) =>
    onStatusChange(
      statusFilters.includes(value) ? statusFilters.filter((s) => s !== value) : [...statusFilters, value],
    )

  // Đếm theo NHÓM lọc đang bật (Trạng thái = 1 nhóm, không phải số status).
  const assignmentActive =
    (officerFilters.length > 0 ? 1 : 0) +
    (reviewerFilters.length > 0 ? 1 : 0) +
    (unitId ? 1 : 0) +
    (unassigned ? 1 : 0)
  const filterCount =
    (statusFilters.length > 0 ? 1 : 0) +
    (majorFilter ? 1 : 0) +
    (degreeLevelFilter ? 1 : 0) +
    (paymentStatusFilter ? 1 : 0) +
    (dateFrom || dateTo ? 1 : 0) +
    assignmentActive

  const majorName = majorPrograms?.find((p) => String(p.id) === majorFilter)?.name ?? majorFilter
  const officerNameOf = (id: string) =>
    officers.find((o) => o.id.toString() === id)?.full_name ?? `#${id}`
  const reviewerNameOf = (id: string) =>
    reviewers.find((o) => o.id.toString() === id)?.full_name ?? `#${id}`
  const unitName = flatUnits.find((u) => u.id.toString() === unitId)?.name ?? unitId

  // Active chips: gồm cả Năm (khi ≠ năm mặc định) + các lọc trong popover.
  type Chip = { key: string; label: string; dot?: string; onRemove: () => void }
  const chips: Chip[] = []
  if (academicYear != null && academicYear !== CURRENT_ADMISSIONS_YEAR) {
    chips.push({ key: "year", label: `Năm ${academicYear}`, onRemove: () => onYearChange(CURRENT_ADMISSIONS_YEAR) })
  }
  statusFilters.forEach((s) =>
    chips.push({ key: `status-${s}`, label: statusLabel(s), dot: getStatusDotColor(s), onRemove: () => toggleStatus(s) }),
  )
  if (majorFilter) chips.push({ key: "major", label: `Ngành: ${majorName}`, onRemove: () => onMajorChange("") })
  if (degreeLevelFilter)
    chips.push({ key: "degree", label: degreeLevelFilter, onRemove: () => onDegreeLevelChange("") })
  if (paymentStatusFilter)
    chips.push({
      key: "payment",
      label: PAYMENT_OPTIONS.find((o) => o.value === paymentStatusFilter)?.label ?? paymentStatusFilter,
      onRemove: () => onPaymentStatusChange(""),
    })
  if (dateFrom || dateTo)
    chips.push({
      key: "date",
      label: `${fmtShort(dateFrom)} – ${fmtShort(dateTo)}`,
      onRemove: () => {
        onDateFromChange("")
        onDateToChange("")
      },
    })
  officerFilters.forEach((id) =>
    chips.push({
      key: `officer-${id}`,
      label: `Cán bộ: ${officerNameOf(id)}`,
      onRemove: () => onOfficerChange(officerFilters.filter((o) => o !== id)),
    }),
  )
  if (unassigned)
    chips.push({ key: "unassigned", label: "Chưa giao", onRemove: () => onUnassignedChange(false) })
  if (unitId)
    chips.push({ key: "unit", label: `Đơn vị: ${unitName}`, onRemove: () => onUnitIdChange("") })
  reviewerFilters.forEach((id) =>
    chips.push({
      key: `reviewer-${id}`,
      label: `Người duyệt: ${reviewerNameOf(id)}`,
      onRemove: () => onReviewerChange(reviewerFilters.filter((r) => r !== id)),
    }),
  )

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        {/* Search (command input) */}
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Tìm theo tên, email, CCCD…"
            aria-label="Tìm kiếm hồ sơ tuyển sinh"
            name="admissions-search"
            autoComplete="off"
            spellCheck={false}
            className="h-10 pl-9 pr-9"
          />
          {search && (
            <button
              type="button"
              onClick={() => onSearchChange("")}
              aria-label="Xóa tìm kiếm"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Year */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" className="h-10 gap-1.5">
                {academicYear != null ? `Năm ${academicYear}` : "Tất cả năm"}
                <ChevronDown className="size-4 text-muted-foreground" aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40">
              <DropdownMenuItem className="justify-between" onClick={() => onYearChange(undefined)}>
                Tất cả năm
                {academicYear == null && <Check className="size-4" />}
              </DropdownMenuItem>
              {yearOptions.map((y) => (
                <DropdownMenuItem key={y} className="justify-between" onClick={() => onYearChange(y)}>
                  {y}
                  {academicYear === y && <Check className="size-4" />}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Filter popover */}
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" className="h-10 gap-1.5" aria-label="Bộ lọc nâng cao">
                <SlidersHorizontal className="size-4" aria-hidden="true" />
                Bộ lọc
                {filterCount > 0 && (
                  <span className="ml-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1 text-2xs font-semibold tabular-nums text-primary-foreground">
                    {filterCount}
                  </span>
                )}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-[min(340px,calc(100vw-2rem))] p-0">
              <div className="max-h-[60vh] overflow-y-auto">
                {/* Trạng thái */}
                <div className="border-b border-border p-3">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Trạng thái</p>
                  <div className="grid grid-cols-1 gap-0.5">
                    {STATUS_OPTIONS.map((o) => (
                      <label key={o.value} className="flex min-h-10 cursor-pointer items-center gap-2 rounded-md px-2 py-2 hover:bg-muted">
                        <Checkbox
                          checked={statusFilters.includes(o.value)}
                          onCheckedChange={() => toggleStatus(o.value)}
                          aria-label={o.label}
                        />
                        <span className={cn("size-1.5 shrink-0 rounded-full", getStatusDotColor(o.value))} />
                        <span className="text-sm">{o.label}</span>
                      </label>
                    ))}
                  </div>
                </div>

                {/* Ngành / Trình độ / Học phí — native select để tránh overlay lồng */}
                <div className="space-y-3 border-b border-border p-3">
                  <div>
                    <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">Ngành</label>
                    <select
                      className={NATIVE_SELECT_CLASS}
                      value={majorFilter}
                      onChange={(e) => onMajorChange(e.target.value)}
                      aria-label="Lọc theo ngành học"
                    >
                      <option value="">Tất cả ngành</option>
                      {majorPrograms?.map((p) => (
                        <option key={p.id} value={String(p.id)}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">Trình độ</label>
                    {/* value = NAME ("Cao đẳng"), không phải code: BE match theo MajorProgram.degree_level TEXT. */}
                    <select
                      className={NATIVE_SELECT_CLASS}
                      value={degreeLevelFilter}
                      onChange={(e) => onDegreeLevelChange(e.target.value)}
                      aria-label="Lọc theo trình độ đào tạo"
                    >
                      <option value="">Tất cả trình độ</option>
                      {degreeLevels?.map((level) => (
                        <option key={level.code} value={level.name}>
                          {level.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">Học phí</label>
                    <select
                      className={NATIVE_SELECT_CLASS}
                      value={paymentStatusFilter}
                      onChange={(e) => onPaymentStatusChange(e.target.value)}
                      aria-label="Lọc theo trạng thái học phí"
                    >
                      <option value="">Tất cả học phí</option>
                      {PAYMENT_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Phân công (admin/manager) — fetch nội bộ; backend enforce scope */}
                {showAssignmentGroup && (
                  <div className="space-y-3 border-b border-border p-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Phân công</p>

                    {canFilterByOfficerFlag && (
                      <div className="space-y-2">
                        <label className="block text-xs font-medium text-muted-foreground">Cán bộ phụ trách</label>
                        <Input
                          placeholder="Tìm cán bộ…"
                          value={officerSearch}
                          onChange={(e) => setOfficerSearch(e.target.value)}
                          className="h-9"
                        />
                        <div className="max-h-40 space-y-1.5 overflow-y-auto">
                          {officers.map((officer) => (
                            <label key={officer.id} className="flex min-h-9 cursor-pointer items-center gap-2 text-sm">
                              <Checkbox
                                checked={officerFilters.includes(officer.id.toString())}
                                onCheckedChange={() => onOfficerChange(toggleId(officerFilters, officer.id.toString()))}
                                aria-label={officer.full_name ?? undefined}
                              />
                              <span className="truncate">{officer.full_name}</span>
                            </label>
                          ))}
                          {officers.length === 0 && (
                            <p className="text-muted-foreground text-xs">Không có cán bộ phù hợp.</p>
                          )}
                        </div>
                        {officersTruncated && (
                          <p className="text-muted-foreground text-xs">
                            Hiển thị {officers.length}/{officersTotalCount} — nhập tên để tìm thêm
                          </p>
                        )}
                        <label className="flex min-h-9 cursor-pointer items-center gap-2 text-sm">
                          <Checkbox
                            checked={unassigned}
                            onCheckedChange={(v) => onUnassignedChange(!!v)}
                            aria-label="Chưa giao"
                          />
                          <span>Chưa giao (không có cán bộ)</span>
                        </label>
                      </div>
                    )}

                    {canFilterByOfficerFlag && (
                      <div className="space-y-2">
                        <label className="block text-xs font-medium text-muted-foreground">Người duyệt</label>
                        <Input
                          placeholder="Tìm người duyệt…"
                          value={reviewerSearch}
                          onChange={(e) => setReviewerSearch(e.target.value)}
                          className="h-9"
                        />
                        <div className="max-h-40 space-y-1.5 overflow-y-auto">
                          {reviewers.map((r) => (
                            <label key={r.id} className="flex min-h-9 cursor-pointer items-center gap-2 text-sm">
                              <Checkbox
                                checked={reviewerFilters.includes(r.id.toString())}
                                onCheckedChange={() => onReviewerChange(toggleId(reviewerFilters, r.id.toString()))}
                                aria-label={r.full_name ?? undefined}
                              />
                              <span className="truncate">{r.full_name}</span>
                            </label>
                          ))}
                          {reviewers.length === 0 && (
                            <p className="text-muted-foreground text-xs">Không có người duyệt phù hợp.</p>
                          )}
                        </div>
                        {reviewersTruncated && (
                          <p className="text-muted-foreground text-xs">
                            Hiển thị {reviewers.length}/{reviewersTotalCount} — nhập tên để tìm thêm
                          </p>
                        )}
                      </div>
                    )}

                    {isAdminFlag && (
                      <div className="space-y-2">
                        <label className="block text-xs font-medium text-muted-foreground">Đơn vị</label>
                        <div className="max-h-40 space-y-0.5 overflow-y-auto">
                          {flatUnits.map((unit) => (
                            <button
                              key={unit.id}
                              type="button"
                              className={cn(
                                "w-full rounded px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted",
                                unitId === unit.id.toString() && "bg-muted font-medium",
                              )}
                              style={unit.depth > 0 ? { paddingLeft: `${8 + unit.depth * 12}px` } : undefined}
                              onClick={() => onUnitIdChange(unitId === unit.id.toString() ? "" : unit.id.toString())}
                            >
                              {unit.name}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Khoảng ngày tạo — giữ CalendarComponent */}
                <div className="p-3">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Khoảng ngày tạo</p>
                  <div className="space-y-3">
                    <div>
                      <p className="mb-1 text-xs text-muted-foreground">Từ ngày</p>
                      <CalendarComponent
                        mode="single"
                        selected={parseDate(dateFrom)}
                        onSelect={(date) => onDateFromChange(date ? format(date, "yyyy-MM-dd") : "")}
                        locale={vi}
                      />
                    </div>
                    <div>
                      <p className="mb-1 text-xs text-muted-foreground">Đến ngày</p>
                      <CalendarComponent
                        mode="single"
                        selected={parseDate(dateTo)}
                        onSelect={(date) => onDateToChange(date ? format(date, "yyyy-MM-dd") : "")}
                        locale={vi}
                      />
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-between border-t border-border p-3">
                <Button variant="ghost" size="sm" onClick={onReset}>
                  Xóa lọc
                </Button>
                {filterCount > 0 && (
                  <span className="text-xs tabular-nums text-muted-foreground">{filterCount} điều kiện</span>
                )}
              </div>
            </PopoverContent>
          </Popover>

          {/* Sort */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" className="h-10 gap-1.5">
                <ArrowUpDown className="size-4" aria-hidden="true" />
                <span className="hidden sm:inline">Sắp xếp</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              {SORT_OPTIONS.map((opt) => {
                const active = sortBy === opt.by && sortOrder === opt.order
                return (
                  <DropdownMenuItem key={opt.label} className="justify-between" onClick={() => onSortChange(opt.by, opt.order)}>
                    {opt.label}
                    {active && <Check className="size-4" />}
                  </DropdownMenuItem>
                )
              })}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Active chips */}
      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {chips.map((c) => (
            <span
              key={c.key}
              className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card py-1 pl-2.5 pr-1 text-xs font-medium shadow-xs"
            >
              {c.dot && <span className={cn("size-1.5 shrink-0 rounded-full", c.dot)} />}
              {c.label}
              <button
                type="button"
                onClick={c.onRemove}
                aria-label={`Bỏ lọc ${c.label}`}
                className="ml-0.5 rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
          <button type="button" onClick={onReset} className="text-xs font-medium text-muted-foreground hover:text-foreground">
            Xóa tất cả
          </button>
        </div>
      )}
    </div>
  )
}
