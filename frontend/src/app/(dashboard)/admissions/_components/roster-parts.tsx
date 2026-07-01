// src/app/(dashboard)/admissions/_components/roster-parts.tsx
/**
 * Shared presentational parts cho roster hồ sơ (bảng desktop + card mobile).
 * Thuần trình bày — không logic nghiệp vụ. Màu chấm status lấy từ
 * `status-config` (single source). Class màu là literal static (Tailwind JIT).
 */

"use client"

import Link from "next/link"
import { CheckCircle2, ClipboardCheck, Eye, MoreHorizontal, XCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"
import { ADMISSION_STATUS_CONFIG, getStatusDotColor } from "@/lib/status-config"
import { hasAction } from "@/lib/admission/permissions"
import { formatVND } from "@/lib/zod/finance"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

export function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return "?"
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

export function Monogram({ name, className }: { name: string; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex size-9 shrink-0 items-center justify-center rounded-xl bg-muted font-display text-xs font-semibold text-foreground/70",
        className,
      )}
    >
      {getInitials(name)}
    </span>
  )
}

export function StatusDot({ status }: { status: string }) {
  const label = ADMISSION_STATUS_CONFIG[status]?.label ?? status
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <span className={cn("size-2 shrink-0 rounded-full", getStatusDotColor(status))} />
      <span className="text-sm text-foreground">{label}</span>
    </span>
  )
}

const ELIGIBILITY_META: Record<string, { label: string; dot: string; text: string }> = {
  eligible: { label: "Đủ điều kiện", dot: "bg-success-500", text: "text-success-700" },
  ineligible: { label: "Không đủ ĐK", dot: "bg-error-500", text: "text-error-700" },
  pending: { label: "Đang xét", dot: "bg-gray-400", text: "text-muted-foreground" },
}

export function EligibilityToken({ status }: { status: string }) {
  const m =
    ELIGIBILITY_META[status] ?? { label: status, dot: "bg-gray-400", text: "text-muted-foreground" }
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap text-sm", m.text)}>
      <span className={cn("size-1.5 shrink-0 rounded-full", m.dot)} />
      {m.label}
    </span>
  )
}

// Học phí HK1 (Admission List v2). Chấm màu map TĨNH từ `tuition_hk1_status`
// (BE emit — thin client, FE chỉ map màu). status "none"/undefined = hồ sơ chưa
// có học phí HK1 → "—".
const HK1_DOT: Record<string, string> = {
  paid: "bg-success-500",
  partial: "bg-amber-500",
  unpaid: "bg-gray-400",
  overdue: "bg-error-500",
}

export function TuitionHk1({
  paid,
  remaining,
  status,
}: {
  paid: number | null | undefined
  remaining: number | null | undefined
  status: string | null | undefined
}) {
  if (!status || status === "none") {
    return <span className="text-sm text-muted-foreground">—</span>
  }
  const dot = HK1_DOT[status] ?? "bg-gray-400"
  return (
    <div className="flex items-center gap-2 whitespace-nowrap">
      <span className={cn("size-1.5 shrink-0 rounded-full", dot)} aria-hidden="true" />
      <div className="text-xs leading-tight tabular-nums">
        <div className="text-foreground">Đã đóng {formatVND(paid ?? 0)}</div>
        <div className={cn(status === "overdue" ? "text-error-700" : "text-muted-foreground")}>
          Còn lại {formatVND(remaining ?? 0)}
        </div>
      </div>
    </div>
  )
}

export function ProgressBar({ value, className }: { value: number; className?: string }) {
  const v = Math.max(0, Math.min(100, Math.round(value ?? 0)))
  // Đổi màu theo ngưỡng hoàn thiện: thấp = cảnh báo, đủ = thành công.
  const color = v >= 100 ? "bg-success-500" : v < 40 ? "bg-amber-500" : "bg-primary"
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${v}%` }} />
      </div>
      <span className="w-9 shrink-0 text-right text-xs tabular-nums text-muted-foreground">{v}%</span>
    </div>
  )
}

function AvatarChip({ name, title, muted }: { name: string; title: string; muted?: boolean }) {
  return (
    <span
      title={title}
      className={cn(
        "flex size-7 items-center justify-center rounded-full text-2xs font-semibold ring-2 ring-card",
        muted ? "bg-muted/60 text-muted-foreground" : "bg-muted text-foreground/70",
      )}
    >
      {getInitials(name)}
    </span>
  )
}

export function Assignees({
  officer,
  reviewer,
}: {
  officer: string | null | undefined
  reviewer: string | null | undefined
}) {
  if (!officer && !reviewer) return <span className="text-sm text-muted-foreground">—</span>
  return (
    <div className="flex items-center gap-1.5">
      {officer && <AvatarChip name={officer} title={`Phụ trách: ${officer}`} />}
      {reviewer && <AvatarChip name={reviewer} title={`Người duyệt: ${reviewer}`} muted />}
    </div>
  )
}

export function RowActionsMenu({
  profile,
  onClaim,
  onApprove,
  onReject,
}: {
  profile: AdmissionProfileResponse
  onClaim?: (profile: AdmissionProfileResponse) => void
  onApprove?: (profile: AdmissionProfileResponse) => void
  onReject?: (profile: AdmissionProfileResponse) => void
}) {
  // Quyền hành động do BE quyết (available_actions) — thin client, không gate
  // bằng status string ở FE.
  const canApprove = !!onApprove && hasAction(profile, "approve")
  const canReject = !!onReject && hasAction(profile, "reject")
  const canClaim = !!onClaim && hasAction(profile, "claim")
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-10 touch-manipulation md:size-8"
          aria-label="Thao tác"
          onClick={(e) => e.stopPropagation()}
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
        <DropdownMenuItem asChild>
          <Link href={`/admissions/${profile.id}`}>
            <Eye className="mr-2 size-4" />
            Xem chi tiết
          </Link>
        </DropdownMenuItem>
        {(canApprove || canReject || canClaim) && <DropdownMenuSeparator />}
        {canApprove && (
          <DropdownMenuItem className="text-success-700" onClick={() => onApprove?.(profile)}>
            <CheckCircle2 className="mr-2 size-4" />
            Phê duyệt
          </DropdownMenuItem>
        )}
        {canReject && (
          <DropdownMenuItem className="text-error-700" onClick={() => onReject?.(profile)}>
            <XCircle className="mr-2 size-4" />
            Từ chối
          </DropdownMenuItem>
        )}
        {canClaim && (
          <DropdownMenuItem className="text-primary" onClick={() => onClaim?.(profile)}>
            <ClipboardCheck className="mr-2 size-4" />
            Nhận duyệt
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
