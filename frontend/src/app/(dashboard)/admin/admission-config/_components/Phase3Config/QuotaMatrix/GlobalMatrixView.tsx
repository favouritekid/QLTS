/**
 * GlobalMatrixView — Ma trận toàn cảnh (power mode).
 *
 * Rows = academic_info × academic_year, cols = rounds, cells = aggregate.
 * Cell read-only, click → AggregateDrawer.
 *
 * FM-5 follow-up: memoize cell button pending. Tooltip wrapper (Radix)
 * trigger asChild render-prop khiến memoization phức tạp hơn ByMajorView;
 * cần đo perf trên schema thực (20 ngành × 4 đợt = 80 cells) trước khi
 * extract component. ByMajorView (240 cells / 1 method × round) đã memoize
 * trong CHECKPOINT 6.
 */
"use client"

import { AlertTriangle } from "lucide-react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useQuotaMatrix } from "@/hooks/admissions/useQuotaMatrix"

import { AggregateDrawer } from "./AggregateDrawer"

const CURRENT_YEAR = new Date().getFullYear()
const YEAR_OPTIONS = [CURRENT_YEAR - 1, CURRENT_YEAR, CURRENT_YEAR + 1, CURRENT_YEAR + 2]

function fmtCap(cap: number | null | undefined): string {
  return cap === null || cap === undefined ? "∞" : String(cap)
}

interface Props {
  academicYear: number
  onYearChange: (year: number) => void
}

export function GlobalMatrixView({ academicYear, onYearChange }: Props) {
  const { data, isLoading, isError } = useQuotaMatrix(academicYear)
  const [openCell, setOpenCell] = useState<{
    academicInfoId: number
    roundId: number
    programName: string
    roundCode: string
  } | null>(null)

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <div>
          <CardTitle className="text-base text-pretty">
            Ma trận toàn cảnh năm {academicYear}
          </CardTitle>
          <p className="text-xs text-muted-foreground mt-1">
            Tổng quan chỉ đọc · bấm ô để xem chi tiết &amp; chỉnh chỉ tiêu.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={academicYear.toString()} onValueChange={(v) => onYearChange(Number(v))}>
            <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
            <SelectContent>
              {YEAR_OPTIONS.map((y) => (
                <SelectItem key={y} value={y.toString()}>{y}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {data && (
            <Badge variant="outline">
              {data.total_rows} ngành × {data.rounds.length} đợt
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="text-sm text-muted-foreground" aria-live="polite">
            Đang tải…
          </div>
        )}
        {isError && (
          <div className="text-sm text-destructive">Lỗi tải dữ liệu.</div>
        )}
        {data && data.rows.length === 0 && (
          <div className="text-sm text-muted-foreground">
            Chưa có ngành nào được công bố cho năm {academicYear}.
          </div>
        )}
        {data && data.rows.length > 0 && (
          <TooltipProvider delayDuration={200}>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Ngành</TableHead>
                    <TableHead className="text-center">Bậc</TableHead>
                    <TableHead className="text-right">Cap năm</TableHead>
                    <TableHead className="text-right">Đã rải</TableHead>
                    <TableHead className="text-right">Còn lại</TableHead>
                    {data.rounds.map((r) => (
                      <TableHead key={r.id} className="text-center min-w-[120px]" translate="no">
                        {r.round_code}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.rows.map((row) => {
                    const isOver = row.sum_remaining !== null && row.sum_remaining < 0
                    return (
                      <TableRow
                        key={row.academic_info_id}
                        className={isOver ? "bg-destructive/5" : ""}
                      >
                        <TableCell>
                          <div className="font-medium">{row.program_name}</div>
                          {row.program_code && (
                            <div className="text-xs text-muted-foreground">{row.program_code}</div>
                          )}
                        </TableCell>
                        <TableCell className="text-center">
                          <Badge variant="outline" className="text-xs">
                            {row.degree_level ?? "—"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right font-medium">
                          {row.annual_admission_quota ?? (
                            <span className="text-muted-foreground italic">∞</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right">{row.sum_admit_allocated}</TableCell>
                        <TableCell className="text-right">
                          {row.sum_remaining === null ? (
                            <span className="text-muted-foreground italic">∞</span>
                          ) : isOver ? (
                            <span className="text-destructive font-semibold inline-flex items-center gap-1">
                              <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
                              {row.sum_remaining}
                            </span>
                          ) : (
                            <span className="text-emerald-600 font-medium">{row.sum_remaining}</span>
                          )}
                        </TableCell>
                        {data.rounds.map((r) => {
                          const cell = row.cells_by_round_id[r.id]
                          if (!cell) {
                            return (
                              <TableCell key={r.id} className="text-center text-xs text-muted-foreground">
                                —
                              </TableCell>
                            )
                          }
                          return (
                            <TableCell key={r.id} className="p-1">
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <button
                                    onClick={() =>
                                      setOpenCell({
                                        academicInfoId: row.academic_info_id,
                                        roundId: r.id,
                                        programName: row.program_name,
                                        roundCode: r.round_code,
                                      })
                                    }
                                    className="w-full text-left bg-blue-50 dark:bg-blue-950/40 hover:bg-blue-100 dark:hover:bg-blue-900/50 border border-blue-200 dark:border-blue-800 rounded-md px-2 py-1.5 transition-colors"
                                    aria-label={`Mở tổng hợp ${row.program_name} đợt ${r.round_code}: hồ sơ ${cell.total_submitted_count} trên ${fmtCap(cell.total_round_quota)}, trúng tuyển ${cell.total_approved_count} trên ${fmtCap(cell.total_admit_quota)}, nhập học ${cell.total_enrolled_count}, ${cell.path_count} phương thức tuyển sinh`}
                                  >
                                    <div className="flex items-center justify-between gap-1 text-[11px] tabular-nums">
                                      <span className="text-muted-foreground">Hồ sơ</span>
                                      <span className="font-semibold">
                                        {cell.total_submitted_count} / {fmtCap(cell.total_round_quota)}
                                      </span>
                                    </div>
                                    <div className="flex items-center justify-between gap-1 text-[11px] tabular-nums">
                                      <span className="text-muted-foreground">Trúng tuyển</span>
                                      <span className="font-semibold">
                                        {cell.total_approved_count} / {fmtCap(cell.total_admit_quota)}
                                      </span>
                                    </div>
                                    <div className="flex items-center justify-between gap-1 text-[11px] tabular-nums">
                                      <span className="text-muted-foreground">Nhập học</span>
                                      <span className="font-semibold">
                                        {cell.total_enrolled_count}
                                        {cell.total_dropped_count > 0 && (
                                          <span className="font-normal text-muted-foreground">
                                            {" "}
                                            ({cell.total_dropped_count} đã bỏ)
                                          </span>
                                        )}
                                      </span>
                                    </div>
                                    <div className="mt-0.5 text-[11px] text-muted-foreground">
                                      {cell.path_count} phương thức
                                    </div>
                                  </button>
                                </TooltipTrigger>
                                <TooltipContent>
                                  <div className="text-xs">
                                    <div className="font-medium mb-1">
                                      {row.program_name}
                                      <span aria-hidden="true"> × </span>
                                      <span translate="no">{r.round_code}</span>
                                    </div>
                                    <div>Bấm để xem &amp; chỉnh chi tiết theo phương thức.</div>
                                  </div>
                                </TooltipContent>
                              </Tooltip>
                            </TableCell>
                          )
                        })}
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          </TooltipProvider>
        )}
      </CardContent>

      {openCell && (
        <AggregateDrawer
          academicInfoId={openCell.academicInfoId}
          roundId={openCell.roundId}
          programName={openCell.programName}
          roundCode={openCell.roundCode}
          onClose={() => setOpenCell(null)}
        />
      )}
    </Card>
  )
}
