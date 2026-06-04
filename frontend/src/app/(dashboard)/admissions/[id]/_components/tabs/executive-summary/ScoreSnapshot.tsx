/**
 * ScoreSnapshot Component
 *
 * Section 3.1: Snapshot Điểm Chuẩn (Best N)
 * Displays: Table of subject scores with pass/fail indicators
 */

"use client"

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Calculator } from "lucide-react"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { ChevronDown } from "lucide-react"
import { useState } from "react"
import { getSubjectLabel } from "@/lib/utils/admission-helpers"
import { PerNvScoreSummary } from "./PerNvScoreSummary"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface ScoreSnapshotProps {
  profile: AdmissionProfileResponse
}

export function ScoreSnapshot({ profile }: ScoreSnapshotProps) {
  const [isOpen, setIsOpen] = useState(false)

  const isMultiNv = profile.uses_choice_engine === true
  const choices = profile.choices ?? []
  const methodType = profile.applied_rules?.method_type
  const isGpaOnly = methodType === "gpa_only"
  const allSubjectScores = profile.admission_scores?.subject_scores ?? {}
  const totalScore = profile.total_score  // root-level computed field (source of truth)
  const selectedGroup = profile.admission_scores?.selected_group

  // PR6 Step 3 follow-up (2026-04-19): honour backend subject selection.
  //
  // On `best_n` / `any_n` selection modes the backend picks a subset of
  // the submitted scores and `total_score` is computed from that subset.
  // `admission_scores.subject_scores` still contains every submitted
  // score (ignored + selected) so the weighted breakdown would explain
  // an inflated, wrong total if we rendered all of them.
  //
  // `score_snapshot_status.subject_statuses` already holds exactly the
  // selected subjects (backend only emits statuses for what it scored).
  // Prefer `snapshot_score.selected_subjects` when present because it's
  // the explicit contract; fall back to the subject_statuses keys; last
  // fallback is the full map (legacy behavior for snapshots that predate
  // these fields).
  const selectedSubjectCodes: string[] | null = (() => {
    const explicit = profile.snapshot_score?.selected_subjects
    if (explicit && explicit.length > 0) return explicit
    const statusKeys = profile.score_snapshot_status?.subject_statuses
      ? Object.keys(profile.score_snapshot_status.subject_statuses)
      : []
    if (statusKeys.length > 0) return statusKeys
    return null
  })()
  const subjectScores: Record<string, number | null | undefined> =
    selectedSubjectCodes !== null
      ? Object.fromEntries(
          selectedSubjectCodes.map((code) => [code, allSubjectScores[code]]),
        )
      : allSubjectScores

  // ✅ THIN CLIENT: Use backend-computed score status instead of local calculation
  const scoreStatus = profile.score_snapshot_status
  const minSubjectScore = scoreStatus?.min_subject_score ?? profile.applied_rules?.min_subject_score
  const minScore = scoreStatus?.min_score ?? profile.applied_rules?.min_score

  // PR6 Step 3 (2026-04-19): weighted-scoring breakdown. Source of truth
  // for `totalScore` is still the backend (thin client). The extra
  // columns below are a READ-ONLY explanation of how the backend got
  // there — useful when scoring_method="weighted" and the frozen
  // `subject_weights` map is present on the snapshot.
  //
  // Missing key → fallback 1.0, matching the backend scoring contract.
  // Pre-migration snapshots (no `subject_weights`) → degrade to the
  // original 3-column view, no-op.
  const scoringMethod = profile.applied_rules?.scoring_method
  const subjectWeights = profile.applied_rules?.subject_weights ?? {}
  const hasWeights =
    scoringMethod === "weighted" &&
    Object.keys(subjectWeights).length > 0
  const getWeight = (code: string): number =>
    subjectWeights[code] !== undefined ? subjectWeights[code] : 1.0

  // P0 hotfix multi-NV — scores live per choice (ProfileChoiceScore), the
  // profile-level snapshot table below is empty. Render per-NV instead.
  if (isMultiNv) {
    return (
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CollapsibleTrigger className="flex items-center justify-between w-full p-4 hover:bg-muted/50 rounded-lg transition-colors border">
          <div className="flex items-center gap-2">
            <Calculator className="w-5 h-5 text-muted-foreground" />
            <span className="font-semibold">Điểm Theo Nguyện Vọng</span>
          </div>
          <ChevronDown
            className={`w-4 h-4 transition-transform ${
              isOpen ? "transform rotate-180" : ""
            }`}
          />
        </CollapsibleTrigger>

        <CollapsibleContent className="p-4 border border-t-0 rounded-b-lg">
          <PerNvScoreSummary choices={choices} />
        </CollapsibleContent>
      </Collapsible>
    )
  }

  // If GPA-only method, show message
  if (isGpaOnly) {
    return (
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CollapsibleTrigger className="flex items-center justify-between w-full p-4 hover:bg-muted/50 rounded-lg transition-colors border">
          <div className="flex items-center gap-2">
            <Calculator className="w-5 h-5 text-muted-foreground" />
            <span className="font-semibold">Snapshot Điểm Chuẩn</span>
          </div>
          <ChevronDown
            className={`w-4 h-4 transition-transform ${
              isOpen ? "transform rotate-180" : ""
            }`}
          />
        </CollapsibleTrigger>

        <CollapsibleContent className="p-4 border border-t-0 rounded-b-lg">
          <div className="text-center text-muted-foreground py-6">
            Phương thức này chỉ xét học bạ (GPA), không tính điểm từng môn.
          </div>
        </CollapsibleContent>
      </Collapsible>
    )
  }

  // Subject-based method - show score table
  const hasScores = Object.keys(subjectScores).length > 0

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger className="flex items-center justify-between w-full p-4 hover:bg-muted/50 rounded-lg transition-colors border">
        <div className="flex items-center gap-2">
          <Calculator className="w-5 h-5 text-muted-foreground" />
          <span className="font-semibold">
            Snapshot Điểm Chuẩn
            {selectedGroup && (
              <span className="ml-1 text-primary">
                (Khối {selectedGroup})
              </span>
            )}
          </span>
        </div>
        <ChevronDown
          className={`w-4 h-4 transition-transform ${
            isOpen ? "transform rotate-180" : ""
          }`}
        />
      </CollapsibleTrigger>

      <CollapsibleContent className="p-4 border border-t-0 rounded-b-lg">
        {!hasScores ? (
          <div className="text-center text-muted-foreground py-6">
            Chưa có dữ liệu điểm xét tuyển
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                {hasWeights ? (
                  <>
                    <TableHead className="w-[32%]">Môn học</TableHead>
                    <TableHead className="text-right w-[16%]">Điểm</TableHead>
                    <TableHead className="text-right w-[12%]">Hệ số</TableHead>
                    <TableHead className="text-right w-[20%]">Điểm sau nhân</TableHead>
                    <TableHead className="text-right w-[20%]">Trạng thái</TableHead>
                  </>
                ) : (
                  <>
                    <TableHead className="w-[50%]">Môn học</TableHead>
                    <TableHead className="text-right w-[25%]">Điểm</TableHead>
                    <TableHead className="text-right w-[25%]">Trạng thái</TableHead>
                  </>
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {/* Subject Rows */}
              {Object.entries(subjectScores).map(([subjectCode, score]) => {
                // ✅ THIN CLIENT: Use backend-computed status, NOT local calculation
                const subjectStatus = scoreStatus?.subject_statuses?.[subjectCode]
                const isPassing = subjectStatus === "passing"
                const weight = hasWeights ? getWeight(subjectCode) : null
                const weightedScore =
                  hasWeights && score !== null && score !== undefined && weight !== null
                    ? score * weight
                    : null

                return (
                  <TableRow key={subjectCode}>
                    <TableCell className="font-medium">
                      {getSubjectLabel(subjectCode)}
                    </TableCell>
                    <TableCell className="text-right text-lg font-semibold tabular-nums">
                      {score !== null && score !== undefined
                        ? score.toFixed(1)
                        : "N/A"}
                    </TableCell>
                    {hasWeights && (
                      <>
                        <TableCell className="text-right text-sm tabular-nums text-muted-foreground">
                          {weight !== null ? `×${weight}` : "×1"}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {weightedScore !== null ? weightedScore.toFixed(2) : "—"}
                        </TableCell>
                      </>
                    )}
                    <TableCell className="text-right">
                      {score !== null && score !== undefined && subjectStatus != null ? (
                        isPassing ? (
                          <Badge className="bg-success-600">Đạt</Badge>
                        ) : (
                          <Badge variant="destructive">Liệt</Badge>
                        )
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}

              {/* Total Row — totalScore stays the backend-computed source
                  of truth. When hasWeights, we also widen the "Điểm"
                  cell's colspan so the total aligns with the
                  already-weighted per-subject column above. */}
              <TableRow className="bg-info-50 font-bold border-t-2">
                <TableCell>
                  Tổng điểm
                  {hasWeights && (
                    <span className="ml-2 text-xs font-normal text-muted-foreground">
                      (đã áp hệ số)
                    </span>
                  )}
                </TableCell>
                <TableCell
                  colSpan={hasWeights ? 3 : 1}
                  className="text-right text-xl text-info-700 tabular-nums"
                >
                  {totalScore !== null && totalScore !== undefined
                    ? totalScore.toFixed(2)
                    : "N/A"}
                </TableCell>
                <TableCell className="text-right">
                  {/* ✅ THIN CLIENT: Use backend-computed status, NOT local calculation */}
                  {totalScore !== null && totalScore !== undefined && scoreStatus?.total_status != null ? (
                    scoreStatus?.total_status === "passing" ? (
                      <Badge className="bg-success-600 text-base px-3 py-1">
                        Đạt chuẩn
                      </Badge>
                    ) : (
                      <Badge variant="destructive" className="text-base px-3 py-1">
                        Chưa đạt
                      </Badge>
                    )
                  ) : (
                    <span className="text-muted-foreground">-</span>
                  )}
                </TableCell>
              </TableRow>

              {/* Min Score Info */}
              {minScore !== null && minScore !== undefined && (
                <TableRow>
                  <TableCell colSpan={hasWeights ? 5 : 3} className="text-xs text-muted-foreground text-center pt-2 tabular-nums">
                    Điểm chuẩn tối thiểu: {minScore.toFixed(2)}
                    {minSubjectScore !== null && minSubjectScore !== undefined && (
                      <> • Điểm liệt: {minSubjectScore.toFixed(1)}</>
                    )}
                    {hasWeights && (
                      <> • Phương thức: tính theo hệ số</>
                    )}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}
