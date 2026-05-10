/**
 * ByMajorView — Theo ngành (default daily ops mode).
 *
 * Pick 1 ngành → matrix [method × đợt] cho ngành đó.
 * Cell = exact path (NOT aggregate) vì filter (academic_info × method × round)
 * = UNIQUE 3-col. Click cell → PathDetailDrawer trực tiếp (1-step).
 */
"use client"

import { AlertTriangle } from "lucide-react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useCallback, useEffect, useMemo, useState } from "react"

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
import { useQuotaMatrix, usePathMatrixByMajor } from "@/hooks/admissions/useQuotaMatrix"

import { PathDetailDrawer } from "./PathDetailDrawer"
import { QuickCreatePathModal } from "./QuickCreatePathModal"
import { pathStatusLabel } from "./labels"

const CURRENT_YEAR = new Date().getFullYear()
const YEAR_OPTIONS = [CURRENT_YEAR - 1, CURRENT_YEAR, CURRENT_YEAR + 1, CURRENT_YEAR + 2]

interface Props {
  academicYear: number
  onYearChange: (year: number) => void
}

export function ByMajorView({ academicYear, onYearChange }: Props) {
  // Reuse global quota-matrix endpoint to populate ngành dropdown options
  const { data: globalData } = useQuotaMatrix(academicYear)
  const [selectedAcademicInfoId, setSelectedAcademicInfoId] = useState<number | undefined>(undefined)
  const { data: matrix, isLoading } = usePathMatrixByMajor(selectedAcademicInfoId)

  // Pass 2 hard-review F-2-1: URL state sync cho openPathId.
  // Drawer state là URL state theo Frontend CLAUDE.md ("URL State: Filters,
  // pagination") — admin share link mở thẳng path detail, browser
  // back/forward navigate giữa các drawer mở/đóng.
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const openPathId = useMemo(() => {
    const raw = searchParams.get("pathId")
    if (!raw) return null
    const n = Number(raw)
    return Number.isFinite(n) && n > 0 ? n : null
  }, [searchParams])
  const setOpenPathId = useCallback(
    (id: number | null) => {
      const params = new URLSearchParams(searchParams.toString())
      if (id === null) params.delete("pathId")
      else params.set("pathId", id.toString())
      const qs = params.toString()
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
    },
    [pathname, router, searchParams],
  )

  const [createCell, setCreateCell] = useState<{
    methodId: number
    methodName: string
    roundId: number
    roundCode: string
  } | null>(null)

  // Auto-select first ngành on year change
  useEffect(() => {
    if (globalData && globalData.rows.length > 0 && selectedAcademicInfoId === undefined) {
      setSelectedAcademicInfoId(globalData.rows[0].academic_info_id)
    }
  }, [globalData, selectedAcademicInfoId])

  const isOver = matrix?.sum_remaining !== null && matrix !== undefined && matrix.sum_remaining! < 0

  return (
    <Card>
      <CardHeader className="space-y-3 pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Cấu hình theo ngành — daily ops</CardTitle>
          <Select value={academicYear.toString()} onValueChange={(v) => onYearChange(Number(v))}>
            <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
            <SelectContent>
              {YEAR_OPTIONS.map((y) => (
                <SelectItem key={y} value={y.toString()}>{y}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <label className="text-sm font-medium">Ngành:</label>
          <Select
            value={selectedAcademicInfoId?.toString() ?? ""}
            onValueChange={(v) => setSelectedAcademicInfoId(Number(v))}
          >
            <SelectTrigger className="w-72">
              <SelectValue placeholder="Chọn ngành…" />
            </SelectTrigger>
            <SelectContent>
              {globalData?.rows.map((r) => (
                <SelectItem key={r.academic_info_id} value={r.academic_info_id.toString()}>
                  {r.program_name}
                  {r.degree_level && (
                    <span className="text-muted-foreground"> ({r.degree_level})</span>
                  )}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {matrix && (
            <div className="flex items-center gap-2 text-sm ml-auto">
              <span className="text-muted-foreground">Cap năm:</span>
              <span className="font-medium">{matrix.annual_admission_quota ?? "∞"}</span>
              <span className="text-muted-foreground">·</span>
              <span className="text-muted-foreground">Đã rải:</span>
              <span className="font-medium">{matrix.sum_admit_allocated}</span>
              <span className="text-muted-foreground">·</span>
              <span className="text-muted-foreground">Còn:</span>
              {matrix.sum_remaining === null ? (
                <span className="font-medium italic">∞</span>
              ) : isOver ? (
                <span className="font-semibold text-destructive inline-flex items-center gap-1">
                  <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
                  {matrix.sum_remaining}
                </span>
              ) : (
                <span className="font-medium text-emerald-600">{matrix.sum_remaining}</span>
              )}
            </div>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {!selectedAcademicInfoId && (
          <div className="text-sm text-muted-foreground py-4">
            Chọn ngành để xem cấu hình.
          </div>
        )}
        {selectedAcademicInfoId && isLoading && (
          <div className="text-sm text-muted-foreground py-4">Đang tải...</div>
        )}
        {matrix && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Phương thức</TableHead>
                {matrix.rounds.map((r) => (
                  <TableHead key={r.id} className="text-center min-w-[120px]" translate="no">
                    {r.round_code}
                  </TableHead>
                ))}
                <TableHead className="text-right">Tổng phương thức</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {matrix.methods.map((m) => (
                <TableRow key={m.admission_method_id}>
                  <TableCell>
                    <div className="font-medium">{m.method_name}</div>
                    <div className="text-xs text-muted-foreground" translate="no">
                      {m.method_code}
                    </div>
                  </TableCell>
                  {matrix.rounds.map((r) => {
                    const cell = m.cells_by_round_id[r.id]
                    if (!cell) {
                      return (
                        <TableCell key={r.id} className="p-1 text-center">
                          <button
                            onClick={() =>
                              setCreateCell({
                                methodId: m.admission_method_id,
                                methodName: m.method_name,
                                roundId: r.id,
                                roundCode: r.round_code,
                              })
                            }
                            className="text-xs text-muted-foreground hover:text-foreground hover:bg-muted rounded px-2 py-1.5 w-full transition-colors"
                            aria-label={`Tạo đường tuyển sinh ${m.method_name} đợt ${r.round_code}`}
                          >
                            + Tạo
                          </button>
                        </TableCell>
                      )
                    }
                    return (
                      <TableCell key={r.id} className="p-1">
                        <button
                          onClick={() => setOpenPathId(cell.path_id)}
                          className="w-full text-left bg-blue-50 dark:bg-blue-950/40 hover:bg-blue-100 dark:hover:bg-blue-900/50 border border-blue-200 dark:border-blue-800 rounded-md px-2 py-1.5 transition-colors"
                          aria-label={`Mở chi tiết ${m.method_name} đợt ${r.round_code}: trần admit ${cell.admit_quota ?? "chưa đặt"} trên cap năm ${matrix.annual_admission_quota ?? "không giới hạn"}, trạng thái ${pathStatusLabel(cell.status)}`}
                        >
                          <div className="text-xs font-semibold tabular-nums">
                            {cell.admit_quota ?? "—"} / {matrix.annual_admission_quota ?? "∞"}
                          </div>
                          <div className="text-[11px] text-muted-foreground tabular-nums">
                            Submit {cell.round_quota ?? "—"}
                          </div>
                          <div className="text-[11px]">
                            <Badge
                              variant={cell.status === "active" ? "default" : "outline"}
                              className="text-[10px] h-4 px-1"
                            >
                              {pathStatusLabel(cell.status)}
                            </Badge>
                          </div>
                        </button>
                      </TableCell>
                    )
                  })}
                  <TableCell className="text-right font-medium tabular-nums">
                    {m.sum_admit_quota}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        {matrix && (
          <div className="mt-4 text-xs text-muted-foreground space-y-0.5">
            <p>Mỗi ô gồm 3 dòng: trần admit / cap năm · trần submit · trạng thái. Bấm ô để xem chi tiết &amp; chỉnh chỉ tiêu.</p>
            <p>Dấu "—" = chưa có đường tuyển sinh cho (phương thức × đợt).</p>
          </div>
        )}
      </CardContent>

      {openPathId !== null && (
        <PathDetailDrawer
          pathId={openPathId}
          onClose={() => setOpenPathId(null)}
        />
      )}

      {createCell && selectedAcademicInfoId && (
        <QuickCreatePathModal
          academicInfoId={selectedAcademicInfoId}
          admissionRoundId={createCell.roundId}
          admissionMethodId={createCell.methodId}
          contextLabel={`${matrix?.program_name ?? ""} × ${createCell.roundCode} × ${createCell.methodName}`}
          onClose={() => setCreateCell(null)}
          onCreated={(newPathId) => {
            setCreateCell(null)
            setOpenPathId(newPathId)
          }}
        />
      )}
    </Card>
  )
}
