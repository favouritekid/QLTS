/**
 * QuotaMatrixOverview — admin global quota allocation matrix (Phase 2 v8.2 PR-2D.1 v2).
 *
 * Phase 3 view, NO context filter. Shows ALL ngành × all rounds cho năm filter.
 *
 * UX:
 * - Year selector (current ± 2 năm)
 * - Table: rows = ngành (academic_info × academic_year), cols = rounds
 * - Cells = ∑ admit_quota across paths trong cùng (academic_info × round)
 * - Tổng quota | Đã rải | Còn lại columns
 * - Cảnh báo đỏ nếu Còn lại < 0 (vượt cap)
 *
 * Tiếng Việt nhất quán per user feedback.
 */
"use client"

import { AlertTriangle, ChevronLeft } from "lucide-react"
import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useQuotaMatrix } from "@/hooks/admissions/useQuotaMatrix"

const CURRENT_YEAR = new Date().getFullYear()
const YEAR_OPTIONS = [CURRENT_YEAR - 1, CURRENT_YEAR, CURRENT_YEAR + 1, CURRENT_YEAR + 2]

interface Props {
  academicYear: number
  onYearChange: (year: number) => void
  onBack: () => void
}

export function QuotaMatrixOverview({ academicYear, onYearChange, onBack }: Props) {
  const { data, isLoading, isError } = useQuotaMatrix(academicYear)
  const [showAdmit, setShowAdmit] = useState(true)

  const totalCols = useMemo(() => (data?.rounds.length ?? 0) + 4, [data?.rounds])

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ChevronLeft className="h-4 w-4 mr-1" />
          Quay lại
        </Button>
        <h2 className="text-xl font-semibold">Ma trận chỉ tiêu theo đợt</h2>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Tổng quan rải chỉ tiêu năm {academicYear}</span>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant={showAdmit ? "default" : "outline"}
                onClick={() => setShowAdmit(true)}
              >
                Chỉ tiêu trúng tuyển
              </Button>
              <Button
                size="sm"
                variant={!showAdmit ? "default" : "outline"}
                onClick={() => setShowAdmit(false)}
              >
                Chỉ tiêu nộp hồ sơ
              </Button>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-4">
            <div>
              <label className="text-sm font-medium">Năm tuyển sinh:</label>
              <Select
                value={academicYear.toString()}
                onValueChange={(v) => onYearChange(Number(v))}
              >
                <SelectTrigger className="w-32 ml-2 inline-flex">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {YEAR_OPTIONS.map((y) => (
                    <SelectItem key={y} value={y.toString()}>
                      {y}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {data && (
              <Badge variant="outline">
                {data.total_rows} ngành × {data.rounds.length} đợt
              </Badge>
            )}
          </div>

          {isLoading && <div className="text-sm text-muted-foreground">Đang tải...</div>}
          {isError && (
            <div className="text-sm text-destructive">
              Lỗi tải dữ liệu. Vui lòng thử lại.
            </div>
          )}

          {data && data.rows.length === 0 && (
            <div className="text-sm text-muted-foreground">
              Chưa có ngành nào được công bố cho năm {academicYear}.
            </div>
          )}

          {data && data.rows.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ngành</TableHead>
                  <TableHead>Bậc</TableHead>
                  <TableHead className="text-right">Tổng chỉ tiêu</TableHead>
                  {data.rounds.map((r) => (
                    <TableHead key={r.id} className="text-right">
                      <div className="font-semibold">{r.round_code}</div>
                      <div className="text-xs text-muted-foreground">{r.round_name}</div>
                    </TableHead>
                  ))}
                  <TableHead className="text-right">Đã rải</TableHead>
                  <TableHead className="text-right">Còn lại</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.rows.map((row) => {
                  const isOver = row.sum_remaining !== null && row.sum_remaining < 0
                  return (
                    <TableRow key={row.academic_info_id} className={isOver ? "bg-red-50" : ""}>
                      <TableCell className="font-medium">
                        {row.program_name}
                        {row.program_code && (
                          <span className="ml-2 text-xs text-muted-foreground">
                            ({row.program_code})
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-xs">
                          {row.degree_level ?? "—"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {row.annual_admission_quota ?? (
                          <span className="text-muted-foreground italic">∞</span>
                        )}
                      </TableCell>
                      {data.rounds.map((r) => {
                        const cell = row.cells_by_round_id[r.id]
                        const value = cell
                          ? showAdmit
                            ? cell.total_admit_quota
                            : cell.total_round_quota
                          : 0
                        return (
                          <TableCell key={r.id} className="text-right">
                            {cell ? (
                              <div>
                                <div className="font-medium">{value}</div>
                                {cell.path_count > 1 && (
                                  <div className="text-xs text-muted-foreground">
                                    ({cell.path_count} paths)
                                  </div>
                                )}
                              </div>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </TableCell>
                        )
                      })}
                      <TableCell className="text-right font-medium">
                        {row.sum_admit_allocated}
                      </TableCell>
                      <TableCell className="text-right">
                        {row.sum_remaining === null ? (
                          <span className="text-muted-foreground italic">∞</span>
                        ) : isOver ? (
                          <span className="text-destructive font-semibold inline-flex items-center gap-1">
                            <AlertTriangle className="h-4 w-4" />
                            {row.sum_remaining}
                          </span>
                        ) : (
                          <span className="font-medium">{row.sum_remaining}</span>
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}

          <div className="text-xs text-muted-foreground space-y-1 mt-4">
            <p>• Cells = ∑ chỉ tiêu của tất cả đường tuyển sinh thuộc ngành đó cho đợt đó.</p>
            <p>• Cảnh báo đỏ ⚠ nếu Đã rải vượt Tổng chỉ tiêu (Tier 1 chain violation).</p>
            <p>
              • Để chỉnh chỉ tiêu chi tiết per đường tuyển sinh, vào "Cấu hình Đường tuyển sinh"
              chọn ngành cụ thể.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
