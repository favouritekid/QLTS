// src/app/(dashboard)/admissions/_components/columns.tsx
/**
 * TanStack Table Column Definitions for Admissions DataTable
 *
 * Features:
 * - Selection column with checkbox
 * - Sortable columns (name, status, date)
 * - Progress bar for completion percentage
 * - Status badges
 * - Action dropdown
 */

"use client"

import { createColumnHelper, type ColumnDef } from "@tanstack/react-table"
import { format } from "date-fns"
import { vi } from "date-fns/locale"
import { ArrowUpDown, MoreHorizontal, Eye, CheckCircle, XCircle } from "lucide-react"
import Link from "next/link"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Progress } from "@/components/ui/progress"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

// =============================================================================
// STATUS CONFIGURATION
// =============================================================================

export const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  draft: { label: "Nháp", color: "bg-muted text-muted-foreground" },
  submitted: { label: "Chờ duyệt", color: "bg-warning-100 text-warning-700" },
  resubmitted: { label: "Nộp lại", color: "bg-warning-100 text-warning-700" },
  approved: { label: "Đã duyệt", color: "bg-success-100 text-success-700" },
  rejected: { label: "Từ chối", color: "bg-error-100 text-error-700" },
  confirmed: { label: "Đã xác nhận", color: "bg-success-100 text-success-700" },
  enrolled: { label: "Đã nhập học", color: "bg-info-100 text-info-700" },
}

export const ELIGIBILITY_CONFIG: Record<string, { label: string; color: string }> = {
  eligible: { label: "Đủ điều kiện", color: "bg-success-100 text-success-700" },
  ineligible: { label: "Không đủ ĐK", color: "bg-error-100 text-error-700" },
  pending: { label: "Đang xét", color: "bg-muted text-muted-foreground" },
}

// =============================================================================
// COLUMN HELPER
// =============================================================================

const columnHelper = createColumnHelper<AdmissionProfileResponse>()

// =============================================================================
// COLUMN DEFINITIONS
// =============================================================================

interface ColumnOptions {
  onApprove?: (profile: AdmissionProfileResponse) => void
  onReject?: (profile: AdmissionProfileResponse) => void
  canApprove?: boolean
  canReject?: boolean
}

export function getColumns(options?: ColumnOptions): ColumnDef<AdmissionProfileResponse, unknown>[] {
  return [
    // Selection column
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

    // Full Name column
    columnHelper.accessor(
      (row) => row.lead?.full_name ?? `Lead #${row.lead_id}`,
      {
        id: "full_name",
        header: ({ column }) => (
          <Button
            variant="ghost"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
            className="-ml-3 h-8"
          >
            Họ tên
            <ArrowUpDown className="ml-2 h-4 w-4" />
          </Button>
        ),
        cell: ({ row }) => {
          const profile = row.original
          const name = profile.lead?.full_name ?? `Lead #${profile.lead_id}`
          return (
            <Link
              href={`/admissions/${profile.id}`}
              className="font-medium hover:underline"
            >
              {name}
            </Link>
          )
        },
        size: 200,
      }
    ) as ColumnDef<AdmissionProfileResponse, unknown>,

    // Status column
    columnHelper.accessor("status", {
      header: "Trạng thái",
      cell: ({ getValue }) => {
        const status = getValue()
        const config = STATUS_CONFIG[status] ?? { label: status, color: "bg-muted" }
        return (
          <Badge className={config.color}>
            {config.label}
          </Badge>
        )
      },
      size: 120,
    }) as ColumnDef<AdmissionProfileResponse, unknown>,

    // Completion column
    columnHelper.accessor("completion_percent", {
      header: "Tiến độ",
      cell: ({ getValue }) => {
        const percent = getValue()
        return (
          <div className="flex items-center gap-2 min-w-[100px]">
            <Progress value={percent} className="h-2 flex-1" />
            <span className="text-xs text-muted-foreground w-8">
              {percent}%
            </span>
          </div>
        )
      },
      size: 140,
    }) as ColumnDef<AdmissionProfileResponse, unknown>,

    // Eligibility column
    columnHelper.accessor("eligibility_status", {
      header: "Đủ điều kiện",
      cell: ({ getValue }) => {
        const status = getValue()
        const config = ELIGIBILITY_CONFIG[status] ?? { label: status, color: "bg-muted" }
        return (
          <Badge variant="outline" className={config.color}>
            {config.label}
          </Badge>
        )
      },
      size: 120,
    }) as ColumnDef<AdmissionProfileResponse, unknown>,

    // Program column
    columnHelper.accessor(
      (row) => row.lead?.offering?.program?.name ?? "-",
      {
        id: "program",
        header: "Chương trình",
        cell: ({ getValue }) => {
          const program = getValue() as string
          return (
            <span className="text-sm truncate max-w-[150px] block">
              {program}
            </span>
          )
        },
        size: 150,
      }
    ) as ColumnDef<AdmissionProfileResponse, unknown>,

    // Created date column
    columnHelper.accessor("created_at", {
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="-ml-3 h-8"
        >
          Ngày tạo
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ getValue }) => {
        const date = getValue()
        return date ? (
          <span className="text-sm text-muted-foreground">
            {format(new Date(date), "dd/MM/yyyy", { locale: vi })}
          </span>
        ) : "-"
      },
      size: 110,
    }) as ColumnDef<AdmissionProfileResponse, unknown>,

    // Actions column
    columnHelper.display({
      id: "actions",
      header: () => <span className="sr-only">Thao tác</span>,
      cell: ({ row }) => {
        const profile = row.original
        const canApprove = options?.canApprove &&
          (profile.status === "submitted" || profile.status === "resubmitted")
        const canReject = options?.canReject &&
          (profile.status === "submitted" || profile.status === "resubmitted")

        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="h-8 w-8 p-0">
                <span className="sr-only">Mở menu</span>
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem asChild>
                <Link href={`/admissions/${profile.id}`}>
                  <Eye className="mr-2 h-4 w-4" />
                  Xem chi tiết
                </Link>
              </DropdownMenuItem>

              {(canApprove || canReject) && <DropdownMenuSeparator />}

              {canApprove && (
                <DropdownMenuItem
                  onClick={() => options?.onApprove?.(profile)}
                  className="text-success-600"
                >
                  <CheckCircle className="mr-2 h-4 w-4" />
                  Phê duyệt
                </DropdownMenuItem>
              )}

              {canReject && (
                <DropdownMenuItem
                  onClick={() => options?.onReject?.(profile)}
                  className="text-error-600"
                >
                  <XCircle className="mr-2 h-4 w-4" />
                  Từ chối
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )
      },
      size: 60,
    }) as ColumnDef<AdmissionProfileResponse, unknown>,
  ]
}
