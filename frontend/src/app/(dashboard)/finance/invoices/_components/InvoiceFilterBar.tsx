// src/app/(dashboard)/finance/invoices/_components/InvoiceFilterBar.tsx
/**
 * Filter bar cho workspace "Thu học phí" (phỏng AdmissionsFilterBar).
 *
 * Bố cục: Search (tên HS / mã HS / số HĐ) · Loại phí · Năm · HK · Ngành · Trình
 * độ · TVV · Đơn vị · Hạn · Sắp xếp · "Xóa tất cả bộ lọc" · chips active. Thuần
 * trình bày — đẩy qua handler thật của useInvoicesFilter.
 */

"use client"

import type { ReactNode } from "react"
import { ArrowUpDown, Check, ChevronDown, Search, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"
import {
  FEE_TYPE_LABELS,
  type FeeType,
  type InvoiceWorkspaceFilters,
} from "@/types/finance.types"

export interface MajorFilterOption {
  id: number
  name: string
  degree_level: string
}

export interface OfficerFilterOption {
  id: number
  name: string
}

export interface UnitFilterOption {
  id: number
  name: string
  level: number
}

const DUE_WINDOW_OPTIONS: readonly {
  value: NonNullable<InvoiceWorkspaceFilters["due_window"]> | ""
  label: string
}[] = [
  { value: "", label: "Mọi hạn" },
  { value: "due_soon_7d", label: "Đến hạn ≤7 ngày" },
  { value: "overdue", label: "Quá hạn" },
]

const FEE_TYPE_OPTIONS: readonly { value: FeeType; label: string }[] = (
  Object.entries(FEE_TYPE_LABELS) as [FeeType, string][]
).map(([value, label]) => ({ value, label }))

const SORT_OPTIONS: readonly { by: string; order: "asc" | "desc"; label: string }[] = [
  { by: "priority", order: "asc", label: "Ưu tiên xử lý" },
  { by: "due_date", order: "asc", label: "Hạn gần nhất" },
  { by: "due_date", order: "desc", label: "Hạn xa nhất" },
  { by: "amount", order: "desc", label: "Số tiền cao → thấp" },
  { by: "amount", order: "asc", label: "Số tiền thấp → cao" },
  { by: "remaining", order: "desc", label: "Còn lại nhiều → ít" },
  { by: "remaining", order: "asc", label: "Còn lại ít → nhiều" },
  { by: "paid", order: "desc", label: "Đã đóng nhiều → ít" },
  { by: "created_at", order: "desc", label: "Mới nhất" },
]

function feeTypeLabel(feeType: string): string {
  return FEE_TYPE_LABELS[feeType as FeeType] ?? feeType
}

/** One selectable row of a {@link FilterDropdown}. */
interface FilterDropdownOption {
  key: string | number
  label: string
  active: boolean
  onSelect: () => void
  /** Hierarchy indentation in px (unit tree). Omitted = flat. */
  indentPx?: number
}

/**
 * Single-select dropdown filter (trigger button + "all" reset row + options
 * with a Check on the active one). Replaces 7 near-identical inline blocks.
 */
function FilterDropdown({
  ariaLabel,
  triggerLabel,
  triggerClassName,
  contentClassName,
  truncateTrigger = false,
  allLabel,
  allActive,
  onSelectAll,
  options,
  truncateItems = false,
}: {
  ariaLabel: string
  triggerLabel: ReactNode
  triggerClassName?: string
  contentClassName: string
  truncateTrigger?: boolean
  allLabel: string
  allActive: boolean
  onSelectAll: () => void
  options: readonly FilterDropdownOption[]
  truncateItems?: boolean
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          className={cn("h-10 gap-1.5", triggerClassName)}
          aria-label={ariaLabel}
        >
          {truncateTrigger ? <span className="truncate">{triggerLabel}</span> : triggerLabel}
          <ChevronDown
            className={cn("size-4 text-muted-foreground", truncateTrigger && "shrink-0")}
            aria-hidden="true"
          />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className={contentClassName}>
        <DropdownMenuItem className="justify-between" onClick={onSelectAll}>
          {allLabel}
          {allActive && <Check className="size-4" />}
        </DropdownMenuItem>
        {options.map((o) => (
          <DropdownMenuItem
            key={o.key}
            className={cn("justify-between", truncateItems && "gap-2")}
            onClick={o.onSelect}
          >
            {truncateItems ? (
              <span
                className="truncate"
                style={o.indentPx ? { paddingLeft: o.indentPx } : undefined}
              >
                {o.label}
              </span>
            ) : (
              o.label
            )}
            {o.active && (
              <Check className={cn("size-4", truncateItems && "shrink-0")} />
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export interface InvoiceFilterBarProps {
  search: string
  onSearchChange: (value: string) => void
  feeType: string
  onFeeTypeChange: (feeType: string) => void
  sortBy: string
  sortOrder: "asc" | "desc"
  onSortChange: (sortBy: string, sortOrder: "asc" | "desc") => void
  hasActiveFilters: boolean
  onReset: () => void
  // Workspace filters (ngành/trình độ/năm-HK/TVV/đơn vị/hạn). majorOptions =
  // danh sách ngành; trình độ derive từ distinct degree_level của majorOptions.
  workspaceFilters: InvoiceWorkspaceFilters
  setWorkspaceFilter: <K extends keyof InvoiceWorkspaceFilters>(
    key: K,
    value: InvoiceWorkspaceFilters[K],
  ) => void
  majorOptions: readonly MajorFilterOption[]
  academicYearOptions: readonly number[]
  semesterOptions: readonly number[]
  officerOptions: readonly OfficerFilterOption[]
  unitOptions: readonly UnitFilterOption[]
}

export function InvoiceFilterBar({
  search,
  onSearchChange,
  feeType,
  onFeeTypeChange,
  sortBy,
  sortOrder,
  onSortChange,
  hasActiveFilters,
  onReset,
  workspaceFilters,
  setWorkspaceFilter,
  majorOptions,
  academicYearOptions,
  semesterOptions,
  officerOptions,
  unitOptions,
}: InvoiceFilterBarProps) {
  const selectedMajor = majorOptions.find((m) => m.id === workspaceFilters.major_id)
  const selectedOfficer = officerOptions.find((o) => o.id === workspaceFilters.officer_id)
  const selectedUnit = unitOptions.find((u) => u.id === workspaceFilters.unit_id)
  // Trình độ: distinct degree_level từ danh sách ngành (gửi TEXT name xuống BE).
  const degreeOptions = Array.from(
    new Set(majorOptions.map((m) => m.degree_level).filter(Boolean)),
  )
  const dueWindow = workspaceFilters.due_window ?? ""

  type Chip = { key: string; label: string; onRemove: () => void }
  const chips: Chip[] = []
  if (feeType) {
    chips.push({ key: "fee_type", label: `Loại: ${feeTypeLabel(feeType)}`, onRemove: () => onFeeTypeChange("") })
  }
  if (workspaceFilters.academic_year) {
    chips.push({
      key: "academic_year",
      label: `Năm: ${workspaceFilters.academic_year}`,
      onRemove: () => setWorkspaceFilter("academic_year", undefined),
    })
  }
  if (workspaceFilters.semester_no) {
    chips.push({
      key: "semester_no",
      label: `HK: ${workspaceFilters.semester_no}`,
      onRemove: () => setWorkspaceFilter("semester_no", undefined),
    })
  }
  if (selectedMajor) {
    chips.push({
      key: "major",
      label: `Ngành: ${selectedMajor.name}`,
      onRemove: () => setWorkspaceFilter("major_id", undefined),
    })
  }
  if (workspaceFilters.degree_level) {
    chips.push({
      key: "degree",
      label: `Trình độ: ${workspaceFilters.degree_level}`,
      onRemove: () => setWorkspaceFilter("degree_level", undefined),
    })
  }
  // TVV/Đơn vị chips render from the RAW filter value (not the options lookup)
  // with a #id fallback label — so a selected officer/unit that drops out of
  // the options list (deactivated, refetch, >500 cap) stays VISIBLE and
  // clearable instead of silently filtering with no chip.
  if (workspaceFilters.officer_id) {
    chips.push({
      key: "officer",
      label: `TVV: ${selectedOfficer?.name ?? `#${workspaceFilters.officer_id}`}`,
      onRemove: () => setWorkspaceFilter("officer_id", undefined),
    })
  }
  if (workspaceFilters.unit_id) {
    chips.push({
      key: "unit",
      label: `Đơn vị: ${selectedUnit?.name ?? `#${workspaceFilters.unit_id}`}`,
      onRemove: () => setWorkspaceFilter("unit_id", undefined),
    })
  }
  if (workspaceFilters.due_window) {
    const lbl = DUE_WINDOW_OPTIONS.find((o) => o.value === workspaceFilters.due_window)?.label
    chips.push({
      key: "due",
      label: `Hạn: ${lbl ?? workspaceFilters.due_window}`,
      onRemove: () => setWorkspaceFilter("due_window", undefined),
    })
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        {/* Search */}
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Tìm theo tên học sinh, mã HS, số hóa đơn…"
            aria-label="Tìm kiếm hóa đơn"
            name="invoices-search"
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
          {/* Loại phí */}
          <FilterDropdown
            ariaLabel="Lọc theo loại phí"
            triggerLabel={feeType ? feeTypeLabel(feeType) : "Tất cả loại phí"}
            contentClassName="w-48"
            allLabel="Tất cả loại phí"
            allActive={!feeType}
            onSelectAll={() => onFeeTypeChange("")}
            options={FEE_TYPE_OPTIONS.map((o) => ({
              key: o.value,
              label: o.label,
              active: feeType === o.value,
              onSelect: () => onFeeTypeChange(o.value),
            }))}
          />

          {/* Năm học */}
          <FilterDropdown
            ariaLabel="Lọc theo năm học"
            triggerLabel={workspaceFilters.academic_year ?? "Mọi năm"}
            contentClassName="max-h-80 w-36 overflow-y-auto"
            allLabel="Mọi năm"
            allActive={workspaceFilters.academic_year === undefined}
            onSelectAll={() => setWorkspaceFilter("academic_year", undefined)}
            options={academicYearOptions.map((year) => ({
              key: year,
              label: String(year),
              active: workspaceFilters.academic_year === year,
              onSelect: () => setWorkspaceFilter("academic_year", year),
            }))}
          />

          {/* Học kỳ */}
          <FilterDropdown
            ariaLabel="Lọc theo học kỳ"
            triggerLabel={workspaceFilters.semester_no ? `HK${workspaceFilters.semester_no}` : "Mọi HK"}
            contentClassName="w-32"
            allLabel="Mọi HK"
            allActive={workspaceFilters.semester_no === undefined}
            onSelectAll={() => setWorkspaceFilter("semester_no", undefined)}
            options={semesterOptions.map((semester) => ({
              key: semester,
              label: `HK${semester}`,
              active: workspaceFilters.semester_no === semester,
              onSelect: () => setWorkspaceFilter("semester_no", semester),
            }))}
          />

          {/* Ngành */}
          <FilterDropdown
            ariaLabel="Lọc theo ngành"
            triggerLabel={selectedMajor ? selectedMajor.name : "Tất cả ngành"}
            triggerClassName="max-w-[14rem]"
            truncateTrigger
            contentClassName="max-h-80 w-64 overflow-y-auto"
            allLabel="Tất cả ngành"
            allActive={workspaceFilters.major_id === undefined}
            onSelectAll={() => setWorkspaceFilter("major_id", undefined)}
            options={majorOptions.map((m) => ({
              key: m.id,
              label: m.name,
              active: workspaceFilters.major_id === m.id,
              onSelect: () => setWorkspaceFilter("major_id", m.id),
            }))}
            truncateItems
          />

          {/* Trình độ */}
          {degreeOptions.length > 0 && (
            <FilterDropdown
              ariaLabel="Lọc theo trình độ"
              triggerLabel={workspaceFilters.degree_level ?? "Mọi trình độ"}
              contentClassName="w-48"
              allLabel="Mọi trình độ"
              allActive={!workspaceFilters.degree_level}
              onSelectAll={() => setWorkspaceFilter("degree_level", undefined)}
              options={degreeOptions.map((d) => ({
                key: d,
                label: d,
                active: workspaceFilters.degree_level === d,
                onSelect: () => setWorkspaceFilter("degree_level", d),
              }))}
            />
          )}

          {/* Tư vấn viên */}
          <FilterDropdown
            ariaLabel="Lọc theo tư vấn viên"
            triggerLabel={
              selectedOfficer
                ? selectedOfficer.name
                : workspaceFilters.officer_id
                  ? `TVV #${workspaceFilters.officer_id}`
                  : "Tất cả TVV"
            }
            triggerClassName="max-w-[12rem]"
            truncateTrigger
            contentClassName="max-h-80 w-56 overflow-y-auto"
            allLabel="Tất cả TVV"
            allActive={workspaceFilters.officer_id === undefined}
            onSelectAll={() => setWorkspaceFilter("officer_id", undefined)}
            options={officerOptions.map((officer) => ({
              key: officer.id,
              label: officer.name,
              active: workspaceFilters.officer_id === officer.id,
              onSelect: () => setWorkspaceFilter("officer_id", officer.id),
            }))}
            truncateItems
          />

          {/* Đơn vị */}
          <FilterDropdown
            ariaLabel="Lọc theo đơn vị"
            triggerLabel={
              selectedUnit
                ? selectedUnit.name
                : workspaceFilters.unit_id
                  ? `Đơn vị #${workspaceFilters.unit_id}`
                  : "Tất cả đơn vị"
            }
            triggerClassName="max-w-[13rem]"
            truncateTrigger
            contentClassName="max-h-80 w-64 overflow-y-auto"
            allLabel="Tất cả đơn vị"
            allActive={workspaceFilters.unit_id === undefined}
            onSelectAll={() => setWorkspaceFilter("unit_id", undefined)}
            options={unitOptions.map((unit) => ({
              key: unit.id,
              label: unit.name,
              active: workspaceFilters.unit_id === unit.id,
              onSelect: () => setWorkspaceFilter("unit_id", unit.id),
              indentPx: unit.level * 12,
            }))}
            truncateItems
          />

          {/* Hạn thanh toán */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" className="h-10 gap-1.5" aria-label="Lọc theo hạn thanh toán">
                {DUE_WINDOW_OPTIONS.find((o) => o.value === dueWindow)?.label ?? "Mọi hạn"}
                <ChevronDown className="size-4 text-muted-foreground" aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              {DUE_WINDOW_OPTIONS.map((o) => (
                <DropdownMenuItem
                  key={o.value || "all"}
                  className="justify-between"
                  onClick={() =>
                    setWorkspaceFilter("due_window", o.value === "" ? undefined : o.value)
                  }
                >
                  {o.label}
                  {dueWindow === o.value && <Check className="size-4" />}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Sort */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" className="h-10 gap-1.5" aria-label="Sắp xếp danh sách">
                <ArrowUpDown className="size-4" aria-hidden="true" />
                <span className="hidden sm:inline">Sắp xếp</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              {SORT_OPTIONS.map((opt) => {
                const active = sortBy === opt.by && sortOrder === opt.order
                return (
                  <DropdownMenuItem
                    key={opt.label}
                    className="justify-between"
                    onClick={() => onSortChange(opt.by, opt.order)}
                  >
                    {opt.label}
                    {active && <Check className="size-4" />}
                  </DropdownMenuItem>
                )
              })}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Active chips + clear-all */}
      {(chips.length > 0 || hasActiveFilters) && (
        <div className="flex flex-wrap items-center gap-2">
          {chips.map((c) => (
            <span
              key={c.key}
              className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card py-1 pl-2.5 pr-1 text-xs font-medium shadow-xs"
            >
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
          {hasActiveFilters && (
            <button
              type="button"
              onClick={onReset}
              className="text-xs font-medium text-muted-foreground hover:text-foreground"
            >
              Xóa tất cả bộ lọc
            </button>
          )}
        </div>
      )}
    </div>
  )
}
