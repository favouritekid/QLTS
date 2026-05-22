/**
 * Q9 #07 Phase E.4 — § 4 Summary panel.
 *
 * Per adjustment #5 (PR-3 audit cycle 2026-05-20): KHÔNG render
 * [Lưu thay đổi] / [Tiếp tục →] buttons — global AdmissionActions already
 * provides these. Panel chỉ hiển thị tóm tắt + audit disclosure.
 *
 * Sections:
 *   - Tổng tạm tính: KV bonus + UT verified bonus + pending notes
 *   - Audit log disclosure (mount existing PriorityAuditTimeline)
 *   - Căn cứ pháp lý disclosure (static — TT 05/2021)
 */
"use client"

import { useState } from "react"
import { ChevronDown, ChevronUp, FileText, History } from "lucide-react"
import { Button } from "@/components/ui/button"
import { PriorityAuditTimeline } from "./PriorityAuditTimeline"
import { getEvidence } from "@/lib/utils/priority-evidence-helpers"
import type { PreviewPriorityKvResponse } from "@/lib/api/priority-kv"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

export interface PrioritySummaryPanelProps {
  profile: AdmissionProfileResponse
  /** Live preview (post §1 edit) — fallback snapshot if null. */
  preview: PreviewPriorityKvResponse | null
}

/** Resolved summary display fields — exported shape cho unit tests. */
export interface SummaryDisplay {
  kv: string | null
  areaBonus: number
  verifiedBucket: { code: string; rate: number } | null
}

/**
 * Pure helper — exported cho regression tests.
 *
 * Precedence (mirror PriorityHeaderBanner P1 contract):
 *   - draft + preview present → preview only; KHÔNG fallback snapshot stale
 *   - post-submit hoặc no preview → snapshot authoritative
 *
 * `verifiedBucket` reads preview.ut_breakdown.applied_code_verified +
 * preview.object_bonus_verified live engine result; fallback snapshot
 * ut_verified_bucket chỉ post-submit hoặc preview unavailable.
 */
export function resolveSummaryDisplay(
  profile: Pick<
    AdmissionProfileResponse,
    "status" | "priority_resolution_snapshot"
  >,
  preview: PreviewPriorityKvResponse | null,
): SummaryDisplay {
  const snapshot = profile.priority_resolution_snapshot ?? {}
  const isPostDraft = profile.status !== "draft"

  // Post-submit: snapshot AUTHORITATIVE (frozen contract); preview ignored.
  // Draft: preview live wins; snapshot defensive fallback when preview null.
  const kv = (() => {
    if (isPostDraft) return snapshot.kv_resolved ?? null
    if (preview) return preview.kv_resolved ?? null
    return snapshot.kv_resolved ?? null
  })()

  const areaBonus = (() => {
    if (isPostDraft) {
      const breakdown = snapshot.breakdown
      if (breakdown && typeof breakdown === "object" && "area_bonus" in breakdown) {
        const v = (breakdown as Record<string, unknown>).area_bonus
        return typeof v === "number" ? v : 0
      }
      return 0
    }
    if (typeof preview?.area_bonus === "number") return preview.area_bonus
    if (!preview) {
      const breakdown = snapshot.breakdown
      if (breakdown && typeof breakdown === "object" && "area_bonus" in breakdown) {
        const v = (breakdown as Record<string, unknown>).area_bonus
        return typeof v === "number" ? v : 0
      }
    }
    return 0
  })()

  const verifiedBucket = (() => {
    if (isPostDraft) {
      const bucket = snapshot.ut_verified_bucket
      if (bucket && typeof bucket === "object") {
        const b = bucket as {
          applied_code?: string | null
          applied_rate?: number | null
        }
        if (b.applied_code && typeof b.applied_rate === "number") {
          return { code: b.applied_code, rate: b.applied_rate }
        }
      }
      return null
    }
    const previewCode = preview?.ut_breakdown?.applied_code_verified ?? null
    const previewRate = preview?.object_bonus_verified
    if (previewCode && typeof previewRate === "number") {
      return { code: previewCode, rate: previewRate }
    }
    if (!preview) {
      const bucket = snapshot.ut_verified_bucket
      if (bucket && typeof bucket === "object") {
        const b = bucket as {
          applied_code?: string | null
          applied_rate?: number | null
        }
        if (b.applied_code && typeof b.applied_rate === "number") {
          return { code: b.applied_code, rate: b.applied_rate }
        }
      }
    }
    return null
  })()

  return { kv: kv ?? null, areaBonus, verifiedBucket }
}

export function PrioritySummaryPanel({ profile, preview }: PrioritySummaryPanelProps) {
  const [auditOpen, setAuditOpen] = useState(false)
  const [lawOpen, setLawOpen] = useState(false)

  const { kv, areaBonus, verifiedBucket } = resolveSummaryDisplay(profile, preview)

  const evidence = getEvidence(profile)
  const pendingCodes = (profile.priority_object_codes ?? [])
    .filter((code) => evidence[code]?.status === "pending")

  const totalBonus = (areaBonus ?? 0) + (verifiedBucket?.rate ?? 0)

  // Cap = `path_bonus_rule.max_total_bonus`. Source-of-truth precedence:
  //   - Post-draft: snapshot.path_bonus_rule (frozen at submit/override)
  //   - Draft: preview.path_bonus_rule (Code review 2026-05-22 fix —
  //     trước fix preview không trả field này → UX inconsistency draft
  //     "+3.50đ" vs sau submit cap "+2.50đ"). Best-effort fallback null
  //     nếu preview chưa load đầy đủ admission_path chain.
  const isPostDraft = profile.status !== "draft"
  const snapshot = profile.priority_resolution_snapshot ?? {}
  const snapshotRule =
    snapshot.path_bonus_rule && typeof snapshot.path_bonus_rule === "object"
      ? (snapshot.path_bonus_rule as { max_total_bonus?: number | null }).max_total_bonus ?? null
      : null
  const previewRule =
    preview?.path_bonus_rule && typeof preview.path_bonus_rule === "object"
      ? preview.path_bonus_rule.max_total_bonus ?? null
      : null
  const maxTotalBonus = isPostDraft ? snapshotRule : previewRule
  const isCapped = typeof maxTotalBonus === "number" && totalBonus > maxTotalBonus
  const appliedBonus = isCapped ? (maxTotalBonus as number) : totalBonus

  return (
    <section
      data-testid="priority-summary-panel"
      className="space-y-3 rounded-lg border border-border bg-card p-4"
    >
      <h3 className="text-base font-semibold">Tóm tắt điểm ưu tiên</h3>

      {/* Tổng tạm tính */}
      <div className="space-y-1 text-sm" data-testid="priority-summary-total">
        <p className="flex items-baseline gap-2">
          <span>Tổng tạm tính:</span>
          {kv && (
            <span>
              {kv}{" "}
              <span className="tabular-nums">
                +{(areaBonus ?? 0).toFixed(2)}đ
              </span>
            </span>
          )}
          {verifiedBucket && (
            <>
              <span className="opacity-60">+</span>
              <span>
                UT{verifiedBucket.code}{" "}
                <span className="tabular-nums">+{verifiedBucket.rate.toFixed(2)}đ</span>
              </span>
            </>
          )}
          <span className="opacity-60">=</span>
          <span className="tabular-nums font-bold" data-testid="priority-summary-amount">
            +{totalBonus.toFixed(2)}đ
          </span>
        </p>
        {pendingCodes.length > 0 && (
          <p className="text-xs text-muted-foreground" data-testid="priority-summary-pending-note">
            ({pendingCodes.map((c) => `UT${c}`).join(", ")} chờ duyệt → chưa cộng)
          </p>
        )}

        {typeof maxTotalBonus === "number" && (
          <div
            className="flex flex-col gap-1 pt-1 mt-1 border-t border-dashed border-border"
            data-testid="priority-summary-cap"
          >
            <p className="text-xs text-muted-foreground flex items-baseline gap-2">
              <span>Cap tối đa của ngành:</span>
              <span className="tabular-nums">+{maxTotalBonus.toFixed(2)}đ</span>
            </p>
            <p className="flex items-baseline gap-2">
              <span>Áp dụng cuối:</span>
              <span
                className="tabular-nums font-bold"
                data-testid="priority-summary-applied"
              >
                +{appliedBonus.toFixed(2)}đ
              </span>
              {isCapped && (
                <span
                  className="rounded-full bg-warning-100 text-warning-800 text-xs px-2 py-0.5"
                  data-testid="priority-summary-cap-badge"
                >
                  Bị cap
                </span>
              )}
            </p>
          </div>
        )}
      </div>

      {/* Audit log disclosure */}
      <div className="border-t border-border pt-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setAuditOpen(!auditOpen)}
          className="w-full justify-between text-sm"
          data-testid="priority-summary-audit-toggle"
        >
          <span className="flex items-center gap-2">
            <History className="h-4 w-4" />
            Audit log (
            {(profile.priority_audit_log ?? []).length} thao tác)
          </span>
          {auditOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </Button>
        {auditOpen && (
          <div className="mt-2" data-testid="priority-summary-audit-content">
            <PriorityAuditTimeline entries={profile.priority_audit_log ?? []} />
          </div>
        )}
      </div>

      {/* Law citation disclosure */}
      <div className="border-t border-border pt-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setLawOpen(!lawOpen)}
          className="w-full justify-between text-sm"
          data-testid="priority-summary-law-toggle"
        >
          <span className="flex items-center gap-2">
            <FileText className="h-4 w-4" />
            Căn cứ pháp lý
          </span>
          {lawOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </Button>
        {lawOpen && (
          <div
            className="mt-2 space-y-2 rounded-md border border-border bg-muted/40 p-3 text-xs"
            data-testid="priority-summary-law-content"
          >
            <p>
              <strong>Thông tư 05/2021/TT-BLĐTBXH</strong> Phụ lục 01 — Quy định
              điểm ưu tiên tuyển sinh giáo dục nghề nghiệp.
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li>
                <strong>Mục 4:</strong> KV theo mã xã/phường thường trú (trường hợp
                đặc biệt: PTDT nội trú, dự bị ĐH, lớp tạo nguồn, quân nhân/CAND).
              </li>
              <li>
                <strong>Mục 5.a:</strong> KV theo trường tốt nghiệp khi học &lt; 3
                năm hoặc tied duration.
              </li>
              <li>
                <strong>Mục 5.b:</strong> KV theo trường học &gt; 3 năm
                (longest_duration rule).
              </li>
              <li>
                <strong>Mục 6:</strong> Admin override KV thủ công — yêu cầu lý do
                + audit trail.
              </li>
            </ul>
          </div>
        )}
      </div>
    </section>
  )
}
