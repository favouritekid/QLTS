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
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface ScoreSnapshotProps {
  profile: AdmissionProfileResponse
}

export function ScoreSnapshot({ profile }: ScoreSnapshotProps) {
  const [isOpen, setIsOpen] = useState(false)

  const methodType = profile.applied_rules?.method_type
  const isGpaOnly = methodType === "gpa_only"
  const subjectScores = profile.admission_scores?.subject_scores ?? {}
  const totalScore = profile.admission_scores?.total_score
  const selectedGroup = profile.admission_scores?.selected_group

  // ✅ THIN CLIENT: Use backend-computed score status instead of local calculation
  const scoreStatus = profile.score_snapshot_status
  const minSubjectScore = scoreStatus?.min_subject_score ?? profile.applied_rules?.min_subject_score
  const minScore = scoreStatus?.min_score ?? profile.applied_rules?.min_score

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
                <TableHead className="w-[50%]">Môn học</TableHead>
                <TableHead className="text-right w-[25%]">Điểm</TableHead>
                <TableHead className="text-right w-[25%]">Trạng thái</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {/* Subject Rows */}
              {Object.entries(subjectScores).map(([subjectCode, score]) => {
                // ✅ THIN CLIENT: Use backend-computed status, NOT local calculation
                const subjectStatus = scoreStatus?.subject_statuses?.[subjectCode]
                const isPassing = subjectStatus === "passing"

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
                    <TableCell className="text-right">
                      {score !== null && score !== undefined && subjectStatus !== null ? (
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

              {/* Total Row */}
              <TableRow className="bg-info-50 font-bold border-t-2">
                <TableCell>Tổng điểm</TableCell>
                <TableCell className="text-right text-xl text-info-700 tabular-nums">
                  {totalScore !== null && totalScore !== undefined
                    ? totalScore.toFixed(2)
                    : "N/A"}
                </TableCell>
                <TableCell className="text-right">
                  {/* ✅ THIN CLIENT: Use backend-computed status, NOT local calculation */}
                  {totalScore !== null && totalScore !== undefined && scoreStatus?.total_status !== null ? (
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
                  <TableCell colSpan={3} className="text-xs text-muted-foreground text-center pt-2 tabular-nums">
                    Điểm chuẩn tối thiểu: {minScore.toFixed(2)}
                    {minSubjectScore !== null && minSubjectScore !== undefined && (
                      <> • Điểm liệt: {minSubjectScore.toFixed(1)}</>
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
