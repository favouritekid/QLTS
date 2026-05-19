"use client"

/**
 * KvBreakdownCard — display Khu vực ưu tiên (KV) snapshot.
 *
 * Q9 #07 Phase E.1 extraction: reusable card lifted từ `PriorityTab.tsx`
 * snapshot section. Use in:
 * - `PriorityTab` (candidate-facing live preview / frozen snapshot)
 * - `PriorityOverrideDialog` (Phase E.2 — confirm BEFORE/AFTER diff khi officer
 *   override KV thủ công)
 * - `KvBreakdownAuditCard` officer review (Phase E read-only audit display)
 *
 * Display states:
 * 1. `loading` → spinner "Đang tính..."
 * 2. `kv` set → badge + pathway + rule + breakdown disclosure
 * 3. `kv` null → empty-state hint (parent provides via `emptyStateHint` slot)
 * 4. `frozen` → "đã chốt" lock icon + primary border; otherwise "tạm tính"
 * 5. Manual override metadata (`manualOverrideBy/At/Reason`) → trailing audit
 *    line shown only khi rule_applied='manual_override'
 *
 * BE schema source: `priority_service.resolve_kv_for_profile()` return shape +
 * `admission_profile.priority_resolution_snapshot` JSONB keys.
 */
import { ReactNode } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Award, AlertCircle, CheckCircle2, Loader2, Lock, UserCog } from "lucide-react"
import {
  KV_BADGE,
  PATHWAY_LABEL_VI,
  RULE_LABEL_VI,
  localizeReason,
} from "./kv-labels"

export interface KvBreakdownCardProps {
  /** Resolved KV code ('KV1' | 'KV2-NT' | 'KV2' | 'KV3') or null when unresolved. */
  kv?: string | null

  /** Pathway enum (BE resolve_kv_for_profile). */
  pathway?: string | null

  /** Rule applied (vd 'longest_duration', 'manual_override'). */
  ruleApplied?: string | null

  /** Failure reason when kv null — mapped through REASON_VI. */
  reason?: string | null

  /** Breakdown JSONB for audit pull (officer-facing JSON disclosure). */
  breakdown?: Record<string, unknown> | null

  /** Engine signal that manual override is required (M1 ambiguous etc). */
  requiresManual?: boolean

  /** True khi snapshot đã chốt (post-T1 submit). Affects icon + border. */
  frozen?: boolean

  /** Loading spinner state — used for live-preview debounce. */
  loading?: boolean

  /**
   * Empty-state hint — parent supplies context-specific guidance
   * (vd "khai trình độ văn hóa" hoặc "khai lịch sử học").
   * Rendered inside the no-KV info box.
   */
  emptyStateHint?: ReactNode

  // --- Manual override audit (E.2 — populated when rule_applied='manual_override') ---
  /** Reason text từ officer/admin (min 20 chars). */
  manualOverrideReason?: string | null

  /** Officer/admin display name (denormalized — BE supplies in snapshot or response). */
  manualOverrideBy?: string | null

  /** ISO datetime when override happened. */
  manualOverrideAt?: string | null
}

export function KvBreakdownCard({
  kv,
  pathway,
  ruleApplied,
  reason,
  breakdown,
  requiresManual,
  frozen = false,
  loading = false,
  emptyStateHint,
  manualOverrideReason,
  manualOverrideBy,
  manualOverrideAt,
}: KvBreakdownCardProps) {
  const kvBadge = kv ? KV_BADGE[kv] : null
  const isManualOverride = ruleApplied === "manual_override"

  return (
    <Card
      className={`border-2 shadow-sm ${
        frozen
          ? "border-primary/40 bg-primary/5"
          : kvBadge
            ? "border-emerald-200"
            : "border-muted"
      }`}
      data-testid="kv-breakdown-card"
    >
      <CardHeader className="pb-2">
        <CardTitle className="text-lg font-semibold flex items-center gap-2 text-foreground">
          {frozen ? (
            <Lock className="h-5 w-5 text-primary" />
          ) : (
            <Award className="h-5 w-5 text-emerald-600" />
          )}
          {frozen ? "Khu vực ưu tiên (đã chốt)" : "Khu vực ưu tiên (tạm tính)"}
        </CardTitle>
        <CardDescription className="text-sm">
          {frozen
            ? "Đã khóa khi nộp hồ sơ — không thể thay đổi (chỉ admin override được)."
            : "Hệ thống tính theo thời gian thực dựa vào thông tin bạn khai. KV chính thức sẽ được chốt khi nộp hồ sơ."}
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-2 space-y-3">
        {/* Loading state */}
        {loading && !kvBadge && !frozen && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="kv-breakdown-loading">
            <Loader2 className="h-4 w-4 animate-spin" />
            Đang tính...
          </div>
        )}

        {/* Has KV resolved */}
        {kvBadge && (
          <div className="flex items-center gap-3" data-testid="kv-breakdown-badge">
            <span className={`inline-flex items-center px-4 py-2 rounded-md text-base font-bold border ${kvBadge.color}`}>
              {kvBadge.label}
            </span>
            {!frozen && <span className="text-xs text-muted-foreground">(sẽ chốt khi nộp hồ sơ)</span>}
            {frozen && (
              <span className="text-xs text-primary flex items-center gap-1">
                <CheckCircle2 className="h-3 w-3" /> Đã chốt
              </span>
            )}
          </div>
        )}

        {/* No KV yet — explain why */}
        {!loading && !kvBadge && (
          <div className="rounded-lg border border-dashed p-3 bg-muted/30 text-sm flex gap-2" data-testid="kv-breakdown-empty">
            <AlertCircle className="h-4 w-4 shrink-0 text-muted-foreground mt-0.5" />
            <div>
              <p className="font-medium text-muted-foreground">Chưa đủ thông tin để tính KV</p>
              {reason && (
                <p className="text-xs text-muted-foreground mt-1">
                  Lý do: {localizeReason(reason)}
                </p>
              )}
              {emptyStateHint && (
                <div className="text-xs text-muted-foreground mt-1">{emptyStateHint}</div>
              )}
              {requiresManual && (
                <p className="text-xs text-warning-700 mt-1">
                  → Cần cán bộ xem xét/ấn định thủ công.
                </p>
              )}
            </div>
          </div>
        )}

        {/* Details: pathway + rule */}
        {(pathway || ruleApplied) && kvBadge && (
          <div className="grid grid-cols-2 gap-3 text-sm pt-2 border-t" data-testid="kv-breakdown-details">
            {pathway && (
              <div>
                <span className="text-xs text-muted-foreground block">Cách tính</span>
                <span className="text-sm">{PATHWAY_LABEL_VI[pathway] ?? pathway}</span>
              </div>
            )}
            {ruleApplied && (
              <div>
                <span className="text-xs text-muted-foreground block">Quy tắc</span>
                <span className="text-sm">{RULE_LABEL_VI[ruleApplied] ?? ruleApplied}</span>
              </div>
            )}
          </div>
        )}

        {/* Manual override audit trail (E.2 — populated when ruleApplied='manual_override') */}
        {isManualOverride && (manualOverrideReason || manualOverrideBy || manualOverrideAt) && (
          <div className="text-xs border-t pt-2 mt-2 flex gap-2 items-start" data-testid="kv-breakdown-override">
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

        {/* Officer/audit JSONB breakdown disclosure */}
        {breakdown && kvBadge && (
          <details className="text-xs border rounded p-2 bg-muted/30" data-testid="kv-breakdown-json">
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
              Xem chi tiết tính toán (cán bộ kiểm tra)
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
