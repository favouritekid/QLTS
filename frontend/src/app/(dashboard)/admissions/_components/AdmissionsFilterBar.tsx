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
]

const SORT_OPTIONS: readonly { by: string; order: "asc" | "desc"; label: string }[] = [
  { by: "created_at", order: "desc", label: "Mới nhất" },
  { by: "created_at", order: "asc", label: "Cũ nhất" },
  { by: "full_name", order: "asc", label: "Tên A → Z" },
  { by: "full_name", order: "desc", label: "Tên Z → A" },
]

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
    onReset,
  } = props

  const toggleStatus = (value: string) =>
    onStatusChange(
      statusFilters.includes(value) ? statusFilters.filter((s) => s !== value) : [...statusFilters, value],
    )

  // Đếm theo NHÓM lọc đang bật (Trạng thái = 1 nhóm, không phải số status).
  const filterCount =
    (statusFilters.length > 0 ? 1 : 0) +
    (majorFilter ? 1 : 0) +
    (degreeLevelFilter ? 1 : 0) +
    (paymentStatusFilter ? 1 : 0) +
    (dateFrom || dateTo ? 1 : 0)

  const majorName = majorPrograms?.find((p) => String(p.id) === majorFilter)?.name ?? majorFilter

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
