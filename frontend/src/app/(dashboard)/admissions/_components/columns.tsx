// src/app/(dashboard)/admissions/_components/columns.tsx
/**
 * TanStack Table column definitions — Admissions roster (redesign v2).
 *
 * Giữ semantics bảng (sort + rowSelection + a11y) nhưng render cell theo
 * roster mới: danh tính 2 dòng + monogram, status chấm, progress ngưỡng,
 * eligibility token, gộp Phụ trách + Người duyệt thành 1 cột avatar chip.
 * Các phần trình bày dùng chung ở `roster-parts` (chia sẻ với card mobile).
 */

"use client"

import { createColumnHelper, type Column, type ColumnDef } from "@tanstack/react-table"
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronRight } from "lucide-react"
import Link from "next/link"

import { Checkbox } from "@/components/ui/checkbox"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { formatDate } from "@/lib/utils/admission-helpers"
import {
  Assignees,
  EligibilityToken,
  Monogram,
  ProgressBar,
  RowActionsMenu,
  StatusDot,
} from "./roster-parts"

type Density = "comfortable" | "compact"

const columnHelper = createColumnHelper<AdmissionProfileResponse>()

interface ColumnOptions {
  onClaim?: (profile: AdmissionProfileResponse) => void
  onApprove?: (profile: AdmissionProfileResponse) => void
  onReject?: (profile: AdmissionProfileResponse) => void
  density?: Density
}

/** Header nút sắp xếp (icon đổi theo trạng thái sort) — dùng chung cho các cột sortable. */
function SortableHeader<TValue>({
  column,
  label,
}: {
  column: Column<AdmissionProfileResponse, TValue>
  label: string
}) {
  const sorted = column.getIsSorted()
  const Icon = sorted === "asc" ? ArrowUp : sorted === "desc" ? ArrowDown : ArrowUpDown
  return (
    <button
      type="button"
      onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
      className="inline-flex items-center gap-1 hover:text-foreground"
    >
      {label}
      <Icon className="size-3.5" />
    </button>
  )
}

export function getColumns(options?: ColumnOptions): ColumnDef<AdmissionProfileResponse, unknown>[] {
  const compact = options?.density === "compact"

  return [
    // Selection
    columnHelper.display({
      id: "select",
      header: ({ table }) => (
        <Checkbox
          checked={
            table.getIsAllPageRowsSelected() ||
            (table.getIsSomePageRowsSelected() && "indeterminate")
          }
          onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
          aria-label="Chọn tất cả"
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(!!value)}
          aria-label="Chọn hàng"
          onClick={(e) => e.stopPropagation()}
        />
      ),
      enableSorting: false,
      enableHiding: false,
      size: 40,
    }) as ColumnDef<AdmissionProfileResponse, unknown>,

    // Identity (sortable by name)
    columnHelper.accessor((row) => row.lead?.full_name ?? `Lead #${row.lead_id}`, {
      id: "full_name",
      header: ({ column }) => <SortableHeader column={column} label="Hồ sơ" />,
      cell: ({ row }) => {
        const p = row.original
        const name = p.lead?.full_name ?? `Lead #${p.lead_id}`
        return (
          <div className="flex items-center gap-3">
            <Monogram name={name} />
            <div className="min-w-0">
              {/* Real <Link> (href) để reviewer Ctrl/giữa-chuột mở hồ sơ ra tab mới;
                  stopPropagation để không kích hoạt thêm router.push của cả hàng. */}
              <Link
                href={`/admissions/${p.id}`}
                onClick={(e) => e.stopPropagation()}
                className="block truncate font-display font-semibold text-foreground hover:underline"
              >
                {name}
              </Link>
              {!compact && (
                <div className="truncate text-xs tabular-nums text-muted-foreground">
                  #{p.id} · {p.program_name ?? "—"}
                </div>
              )}
            </div>
          </div>
        )
      },
      size: 240,
    }) as ColumnDef<AdmissionProfileResponse, unknown>,

    // Status
    columnHelper.accessor("status", {
      header: "Trạng thái",
      cell: ({ getValue }) => <StatusDot status={getValue()} />,
      enableSorting: false,
      size: 130,
    }) as ColumnDef<AdmissionProfileResponse, unknown>,

    // Progress
    columnHelper.accessor("completion_percent", {
      header: "Tiến độ",
      cell: ({ getValue }) => <ProgressBar value={getValue()} className="min-w-[120px]" />,
      enableSorting: false,
      size: 150,
    }) as ColumnDef<AdmissionProfileResponse, unknown>,

    // Eligibility
    columnHelper.accessor("eligibility_status", {
      header: "Điều kiện",
      cell: ({ getValue }) => <EligibilityToken status={getValue()} />,
      enableSorting: false,
      size: 120,
    }) as ColumnDef<AdmissionProfileResponse, unknown>,

    // Assignees (officer + reviewer — luôn hiện cả hai, mọi density)
    columnHelper.accessor("assigned_officer_name", {
      id: "assignees",
      header: "Phụ trách",
      cell: ({ row }) => (
        <Assignees
          officer={row.original.assigned_officer_name}
          reviewer={row.original.assigned_reviewer_name}
        />
      ),
      enableSorting: false,
      size: 110,
    }) as ColumnDef<AdmissionProfileResponse, unknown>,

    // Created date (sortable)
    columnHelper.accessor("created_at", {
      header: ({ column }) => <SortableHeader column={column} label="Ngày tạo" />,
      cell: ({ getValue }) => (
        <span className="whitespace-nowrap text-sm tabular-nums text-muted-foreground">
          {formatDate(getValue())}
        </span>
      ),
      size: 110,
    }) as ColumnDef<AdmissionProfileResponse, unknown>,

    // Actions (chevron hover + menu)
    columnHelper.display({
      id: "actions",
      header: () => <span className="sr-only">Thao tác</span>,
      cell: ({ row }) => (
        <div className="flex items-center justify-end gap-0.5">
          <ChevronRight className="size-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
          <RowActionsMenu
            profile={row.original}
            onClaim={options?.onClaim}
            onApprove={options?.onApprove}
            onReject={options?.onReject}
          />
        </div>
      ),
      enableSorting: false,
      size: 64,
    }) as ColumnDef<AdmissionProfileResponse, unknown>,
  ]
}
