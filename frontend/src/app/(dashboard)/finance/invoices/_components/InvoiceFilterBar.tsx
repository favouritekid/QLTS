// src/app/(dashboard)/finance/invoices/_components/InvoiceFilterBar.tsx
/**
 * Filter bar cho workspace "Thu học phí" (phỏng AdmissionsFilterBar).
 *
 * Bố cục: Search (tên HS / mã HS / số HĐ) · Loại phí (dropdown) · Sắp xếp
 * (dropdown) · "Xóa tất cả bộ lọc" · chips active. Thuần trình bày — đẩy qua
 * handler thật của useInvoicesFilter.
 */

"use client"

import { ArrowUpDown, Check, ChevronDown, Search, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { FEE_TYPE_LABELS, type FeeType } from "@/types/finance.types"

const FEE_TYPE_OPTIONS: readonly { value: FeeType; label: string }[] = (
  Object.entries(FEE_TYPE_LABELS) as [FeeType, string][]
).map(([value, label]) => ({ value, label }))

const SORT_OPTIONS: readonly { by: string; order: "asc" | "desc"; label: string }[] = [
  { by: "priority", order: "asc", label: "Ưu tiên xử lý" },
  { by: "due_date", order: "asc", label: "Hạn gần nhất" },
  { by: "due_date", order: "desc", label: "Hạn xa nhất" },
  { by: "amount", order: "desc", label: "Số tiền cao → thấp" },
  { by: "amount", order: "asc", label: "Số tiền thấp → cao" },
  { by: "created_at", order: "desc", label: "Mới nhất" },
]

function feeTypeLabel(feeType: string): string {
  return FEE_TYPE_LABELS[feeType as FeeType] ?? feeType
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
}: InvoiceFilterBarProps) {
  type Chip = { key: string; label: string; onRemove: () => void }
  const chips: Chip[] = []
  if (feeType) {
    chips.push({ key: "fee_type", label: `Loại: ${feeTypeLabel(feeType)}`, onRemove: () => onFeeTypeChange("") })
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
          {/* Fee type */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" className="h-10 gap-1.5" aria-label="Lọc theo loại phí">
                {feeType ? feeTypeLabel(feeType) : "Tất cả loại phí"}
                <ChevronDown className="size-4 text-muted-foreground" aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              <DropdownMenuItem className="justify-between" onClick={() => onFeeTypeChange("")}>
                Tất cả loại phí
                {!feeType && <Check className="size-4" />}
              </DropdownMenuItem>
              {FEE_TYPE_OPTIONS.map((o) => (
                <DropdownMenuItem
                  key={o.value}
                  className="justify-between"
                  onClick={() => onFeeTypeChange(o.value)}
                >
                  {o.label}
                  {feeType === o.value && <Check className="size-4" />}
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
