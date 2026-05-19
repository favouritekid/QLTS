"use client"

/**
 * PrioritySnapshotCard — combined KV + UT + TOTAL snapshot per Phase E wireframe.
 *
 * Q9 #07 Phase E wireframe (2026-05-19) — Step 4 "Trình độ & Ưu tiên":
 *
 *   ┌───────────────────────────────────────────────────────────────┐
 *   │ 🏆 Điểm cộng ưu tiên (tạm tính)                                │
 *   │ [KV1 +0,75đ]  +  [UT04 +1,00đ]  =  [TỔNG: +1,75đ]              │
 *   │  khu vực        đối tượng                                       │
 *   │                                  (sẽ chốt khi nộp hồ sơ)        │
 *   │                                                                 │
 *   │ Cách tính KV ▸ Lịch sử học các trường THPT (3 năm cấp 3)        │
 *   │ Quy tắc      ▸ Trường học lâu nhất                              │
 *   │ UT áp dụng   ▸ UT04 (chọn diện CAO NHẤT trong 2 diện verified)  │
 *   │                                                                 │
 *   │ ▾ Chi tiết tính toán (cán bộ kiểm tra)                          │
 *   └───────────────────────────────────────────────────────────────┘
 *
 * Frozen state:
 *   ✅ Đã chốt khi nộp hồ sơ lúc 09:15 19/05/2026
 *   ℹ️ Không thể thay đổi — chỉ admin có thể override (có audit log)
 *
 * UT semantics (TT 05/2021 "chỉ hưởng một diện cao nhất"):
 * - potential = MAX rate assuming ALL codes verified (candidate-facing optimism)
 * - verified  = MAX rate restricted to status='verified' (engine T6 actual)
 */
import { ReactNode } from "react"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  AlertCircle,
  Award,
  CheckCircle2,
  Clock,
  Info,
  Loader2,
  Lock,
  UserCog,
} from "lucide-react"
import {
  KV_BADGE,
  PATHWAY_LABEL_VI,
  RULE_LABEL_VI,
  localizeReason,
} from "./kv-labels"
import type { UtBreakdown } from "@/lib/api/priority-kv"

export interface PrioritySnapshotCardProps {
  // ─── KV (existing Phase D) ───
  kv?: string | null
  pathway?: string | null
  ruleApplied?: string | null
  reason?: string | null
  breakdown?: Record<string, unknown> | null
  requiresManual?: boolean
  areaBonus?: number | null

  // ─── UT (Phase E wireframe) ───
  objectBonusPotential?: number | null
  objectBonusVerified?: number | null
  utBreakdown?: UtBreakdown | null

  // ─── Combined total ───
  totalBonusPotential?: number | null

  // ─── State ───
  frozen?: boolean
  loading?: boolean
  emptyStateHint?: ReactNode

  // ─── Audit footer (universal — Phase E wireframe) ───
  frozenAt?: string | null
  resolvedBy?: string | null

  // ─── Manual override audit (E.2) ───
  manualOverrideReason?: string | null
  manualOverrideBy?: string | null
  manualOverrideAt?: string | null
}

/**
 * Format bonus → Vietnamese display string với explicit sign + 'đ' suffix.
 * 0.75 → '+0,75đ'; 0 → '0đ'; null → '—'
 */
export function formatBonus(value: number | null | undefined): string {
  if (value == null) return "—"
  if (value === 0) return "0đ"
  const formatted = value.toFixed(2).replace(".", ",")
  return value > 0 ? `+${formatted}đ` : `${formatted}đ`
}

/** '04' → 'UT04'. */
function formatUtCode(subCode: string | null | undefined): string {
  if (!subCode) return "UT??"
  return `UT${subCode.padStart(2, "0")}`
}

function VerificationStatusBadge({
  verifiedCount,
  submittedCount,
}: {
  verifiedCount: number
  submittedCount: number
}) {
  if (submittedCount === 0) return null
  if (verifiedCount === submittedCount) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-emerald-700">
        <CheckCircle2 className="h-3 w-3" /> Tất cả diện đã xác minh
      </span>
    )
  }
  if (verifiedCount === 0) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-amber-700">
        <Clock className="h-3 w-3" /> {submittedCount} diện chờ xác minh
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs text-amber-700">
      <Clock className="h-3 w-3" /> {verifiedCount}/{submittedCount} diện đã xác minh
    </span>
  )
}

function SummaryRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[7rem_auto] gap-2 text-sm">
      <span className="text-xs text-muted-foreground uppercase tracking-wide">
        {label}
      </span>
      <span className="text-foreground">▸ {value}</span>
    </div>
  )
}

export function PrioritySnapshotCard({
  kv,
  pathway,
  ruleApplied,
  reason,
  breakdown,
  requiresManual,
  objectBonusPotential,
  objectBonusVerified,
  utBreakdown,
  totalBonusPotential,
  frozen = false,
  loading = false,
  emptyStateHint,
  frozenAt,
  resolvedBy,
  manualOverrideReason,
  manualOverrideBy,
  manualOverrideAt,
}: PrioritySnapshotCardProps) {
  const kvBadge = kv ? KV_BADGE[kv] : null
  const isManualOverride = ruleApplied === "manual_override"
  const hasUt = !!utBreakdown?.codes_submitted?.length
  const submittedCount = utBreakdown?.codes_submitted?.length ?? 0
  const verifiedCount = utBreakdown?.verified_codes?.length ?? 0

  const appliedUtCode = utBreakdown?.applied_code_potential
  const appliedUtRateStr = utBreakdown?.applied_rate_potential
  const appliedUtRate = appliedUtRateStr ? Number(appliedUtRateStr) : null

  const hasTotal = totalBonusPotential != null
  const showTotalBadge = hasTotal && hasUt // chỉ show "= TỔNG" khi có ít nhất 2 component
  const hasOverrideAudit =
    isManualOverride &&
    (manualOverrideReason || manualOverrideBy || manualOverrideAt)

  return (
    <Card
      className={`border-2 shadow-sm ${
        frozen
          ? "border-primary/40 bg-primary/5"
          : kvBadge
            ? "border-emerald-200"
            : "border-muted"
      }`}
      data-testid="priority-snapshot-card"
    >
      <CardHeader className="pb-2">
        <CardTitle className="text-lg font-semibold flex items-center gap-2 text-foreground">
          {frozen ? (
            <Lock className="h-5 w-5 text-primary" />
          ) : (
            <Award className="h-5 w-5 text-emerald-600" />
          )}
          {frozen
            ? "Điểm cộng ưu tiên (đã chốt)"
            : "Điểm cộng ưu tiên (tạm tính)"}
        </CardTitle>
        {!frozen && (
          <CardDescription className="text-sm">
            Hệ thống tính theo thời gian thực dựa vào thông tin bạn khai. Điểm
            chính thức sẽ chốt khi nộp hồ sơ.
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="pt-2 space-y-3">
        {/* ─── Loading ─── */}
        {loading && !kvBadge && !frozen && (
          <div
            className="flex items-center gap-2 text-sm text-muted-foreground"
            data-testid="priority-snapshot-loading"
          >
            <Loader2 className="h-4 w-4 animate-spin" />
            Đang tính...
          </div>
        )}

        {/* ─── Combined badge row: [KV] + [UT] = [TỔNG] ─── */}
        {kvBadge && (
          <div data-testid="priority-snapshot-badges">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex flex-col items-center gap-0.5">
                <span
                  className={`inline-flex items-center px-3 py-1.5 rounded-md text-sm font-bold border ${kvBadge.color}`}
                  data-testid="priority-snapshot-kv-badge"
                >
                  {kvBadge.label}
                </span>
                <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  khu vực
                </span>
              </div>

              {hasUt && appliedUtCode && (
                <>
                  <span className="text-muted-foreground font-medium pb-4">
                    +
                  </span>
                  <div className="flex flex-col items-center gap-0.5">
                    <span
                      className="inline-flex items-center px-3 py-1.5 rounded-md text-sm font-bold border bg-purple-100 text-purple-800 border-purple-300"
                      data-testid="priority-snapshot-ut-badge"
                    >
                      {formatUtCode(appliedUtCode)} {formatBonus(appliedUtRate)}
                    </span>
                    <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      đối tượng
                    </span>
                  </div>
                </>
              )}

              {showTotalBadge && (
                <>
                  <span className="text-muted-foreground font-medium pb-4">
                    =
                  </span>
                  <div className="flex flex-col items-center gap-0.5">
                    <span
                      className="inline-flex items-center px-3 py-1.5 rounded-md text-sm font-bold border bg-primary/10 text-primary border-primary/40"
                      data-testid="priority-snapshot-total-badge"
                    >
                      TỔNG: {formatBonus(totalBonusPotential)}
                    </span>
                    <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      tổng cộng
                    </span>
                  </div>
                </>
              )}

              {!frozen && (
                <span className="text-xs text-muted-foreground ml-auto pb-4">
                  (sẽ chốt khi nộp hồ sơ)
                </span>
              )}
            </div>

            {/* UT verification status badge */}
            {hasUt && (
              <div
                className="mt-1.5"
                data-testid="priority-snapshot-ut-status"
              >
                <VerificationStatusBadge
                  verifiedCount={verifiedCount}
                  submittedCount={submittedCount}
                />
              </div>
            )}
          </div>
        )}

        {/* ─── No KV yet — empty state ─── */}
        {!loading && !kvBadge && (
          <div
            className="rounded-lg border border-dashed p-3 bg-muted/30 text-sm flex gap-2"
            data-testid="priority-snapshot-empty"
          >
            <AlertCircle className="h-4 w-4 shrink-0 text-muted-foreground mt-0.5" />
            <div>
              <p className="font-medium text-muted-foreground">
                Chưa đủ thông tin để tính điểm ưu tiên
              </p>
              {reason && (
                <p className="text-xs text-muted-foreground mt-1">
                  Lý do: {localizeReason(reason)}
                </p>
              )}
              {emptyStateHint && (
                <div className="text-xs text-muted-foreground mt-1">
                  {emptyStateHint}
                </div>
              )}
              {requiresManual && (
                <p className="text-xs text-warning-700 mt-1">
                  → Cần cán bộ xem xét/ấn định thủ công.
                </p>
              )}
            </div>
          </div>
        )}

        {/* ─── Inline summary rows (always visible per wireframe) ─── */}
        {kvBadge && (pathway || ruleApplied || hasUt) && (
          <div
            className="border-t pt-2 space-y-1"
            data-testid="priority-snapshot-summary"
          >
            {pathway && (
              <SummaryRow
                label="Cách tính KV"
                value={PATHWAY_LABEL_VI[pathway] ?? pathway}
              />
            )}
            {ruleApplied && (
              <SummaryRow
                label="Quy tắc"
                value={RULE_LABEL_VI[ruleApplied] ?? ruleApplied}
              />
            )}
            {hasUt && appliedUtCode && (
              <SummaryRow
                label="UT áp dụng"
                value={
                  <>
                    {formatUtCode(appliedUtCode)} ({formatBonus(appliedUtRate)})
                    {submittedCount > 1 && (
                      <span className="text-xs text-muted-foreground ml-1">
                        — chọn diện CAO NHẤT trong {submittedCount} diện
                      </span>
                    )}
                    {objectBonusVerified != null &&
                      objectBonusVerified !== objectBonusPotential && (
                        <span className="text-xs text-amber-700 ml-1">
                          (thực tế sau xác minh:{" "}
                          {formatBonus(objectBonusVerified)})
                        </span>
                      )}
                  </>
                }
              />
            )}
          </div>
        )}

        {/* ─── Frozen footer (universal — Phase E wireframe) ─── */}
        {frozen && (frozenAt || resolvedBy) && (
          <div
            className="text-xs border-t pt-2 mt-2 space-y-1"
            data-testid="priority-snapshot-frozen-footer"
          >
            <div className="flex gap-2 items-start text-foreground">
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-600 mt-0.5" />
              <p>
                Đã chốt khi nộp hồ sơ
                {frozenAt
                  ? ` lúc ${new Date(frozenAt).toLocaleString("vi-VN")}`
                  : ""}
                {resolvedBy ? ` bởi ${resolvedBy}` : ""}
              </p>
            </div>
            <div className="flex gap-2 items-start text-muted-foreground">
              <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <p>
                Không thể thay đổi — chỉ admin có thể override (có audit log)
              </p>
            </div>
          </div>
        )}

        {/* ─── Manual override audit (E.2 — when ruleApplied='manual_override') ─── */}
        {hasOverrideAudit && (
          <div
            className="text-xs border-t pt-2 mt-2 flex gap-2 items-start"
            data-testid="priority-snapshot-override"
          >
            <UserCog className="h-3.5 w-3.5 shrink-0 text-amber-700 mt-0.5" />
            <div className="space-y-0.5">
              <p className="font-medium text-amber-800">
                Cán bộ ấn định thủ công
                {manualOverrideBy ? ` bởi ${manualOverrideBy}` : ""}
                {manualOverrideAt
                  ? ` lúc ${new Date(manualOverrideAt).toLocaleString("vi-VN")}`
                  : ""}
              </p>
              {manualOverrideReason && (
                <p className="text-muted-foreground italic">
                  Lý do: {manualOverrideReason}
                </p>
              )}
            </div>
          </div>
        )}

        {/* ─── Officer/audit JSONB breakdown disclosure ─── */}
        {breakdown && kvBadge && (
          <details
            className="text-xs border rounded p-2 bg-muted/30"
            data-testid="priority-snapshot-json"
          >
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
              Chi tiết tính toán (cán bộ kiểm tra)
            </summary>
            <pre className="mt-2 overflow-auto text-[10px]">
              {JSON.stringify(breakdown, null, 2)}
            </pre>
          </details>
        )}
      </CardContent>
    </Card>
  )
}
