/**
 * DocumentReviewCard — compact "Tài liệu" cockpit signal.
 *
 * BE-driven: document_stats (submitted/verified/mandatory/missing/unverified) +
 * missing_priority_evidence_codes. Distinguishes the two failure modes the BE
 * already splits (zod document_stats):
 *   - missing_count   → tài liệu CHƯA nộp        → error (đỏ)
 *   - unverified_count → đã nộp, CHỜ xác minh     → warning (KHÔNG đỏ)
 * Previously "đã nộp đủ chờ xác minh" fell through to the error tone; that is the
 * bug this rewrite fixes. unverified_count is optional (legacy) → fall back to
 * submitted − verified.
 */

"use client"

import { SignalCell, type SignalTone } from "./SignalCell"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface DocumentReviewCardProps {
  profile: AdmissionProfileResponse
}

export function DocumentReviewCard({ profile }: DocumentReviewCardProps) {
  const stats = profile.document_stats ?? null
  const verified = stats?.verified_count ?? 0
  const submitted = stats?.submitted_count ?? 0
  const mandatory = stats?.mandatory_count ?? 0
  const missing = stats?.missing_count ?? 0
  const unverified = stats?.unverified_count ?? Math.max(0, submitted - verified)
  const missingUtCount = profile.missing_priority_evidence_codes?.length ?? 0

  const noMandatory = mandatory === 0
  const hasMissingDocs = missing > 0 // chưa nộp → blocker
  // Pending-verify only matters when mandatory docs exist; for a no-mandatory path
  // an unverified OPTIONAL upload must not produce "Đã nộp đủ, còn N chờ xác minh"
  // alongside the "Không yêu cầu tài liệu" primary (self-contradiction).
  const hasPendingVerify = mandatory > 0 && unverified > 0 // đã nộp, chờ xác minh → cảnh báo

  const tone: SignalTone = hasMissingDocs
    ? "error"
    : hasPendingVerify || missingUtCount > 0
      ? "warning"
      : "success"

  const primary = noMandatory ? "Không yêu cầu tài liệu" : `${submitted}/${mandatory} đã nộp`

  const secondary = hasMissingDocs
    ? `Thiếu ${missing} tài liệu bắt buộc${hasPendingVerify ? ` · ${unverified} chờ xác minh` : ""}${missingUtCount > 0 ? ` · thiếu ${missingUtCount} minh chứng UT` : ""}`
    : hasPendingVerify
      ? `Đã nộp đủ, còn ${unverified} tài liệu chờ xác minh`
      : missingUtCount > 0
        ? `Thiếu ${missingUtCount} minh chứng UT`
        : noMandatory
          ? "Không có tài liệu bắt buộc"
          : "Đã xác minh đủ"

  return (
    <SignalCell
      testId="document-review-card"
      title="Tài liệu"
      tone={tone}
      primary={primary}
      secondary={secondary}
    />
  )
}
