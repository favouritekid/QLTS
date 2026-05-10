/**
 * QuotaMatrixTab — admin matrix UI cho path-level quota allocation
 * (Phase 2 v8.2 PR-2D.1 — FE follow-up to PR-2D BE).
 *
 * Top-level standalone tab in Phase 1 sidebar. Allows admin manage
 * round_quota + admit_quota per AdmissionPath với inline edit + Tier 1+2
 * chain validation server-side.
 *
 * UX:
 * - Year selector (current ± 2 năm)
 * - Academic_info dropdown (filter paths)
 * - Table: rows = paths, cols = round_quota | admit_quota | round
 * - Inline edit cells → PATCH /api/v2/admin/admission-paths/{id}/quota
 * - Toast feedback success/error (BusinessRuleViolation surfaces Vietnamese)
 *
 * Tiếng Việt nhất quán per user feedback (RoundsManagementTab parity).
 */
"use client"

import { Save } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
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
  useAdmissionPathsByAcademicInfo,
  useUpdatePathQuota,
} from "@/hooks/admissions/useAdmissionPaths"
import { useAdmissionRounds } from "@/hooks/admissions/useAdmissionRounds"

interface QuotaCellEdit {
  pathId: number
  round_quota: number | null
  admit_quota: number | null
}

const CURRENT_YEAR = new Date().getFullYear()
const YEAR_OPTIONS = [CURRENT_YEAR - 1, CURRENT_YEAR, CURRENT_YEAR + 1]

export function QuotaMatrixTab() {
  const [selectedYear, setSelectedYear] = useState<number>(CURRENT_YEAR)
  const [academicInfoId, setAcademicInfoId] = useState<number | undefined>(undefined)
  const [edits, setEdits] = useState<Record<number, QuotaCellEdit>>({})

  const { data: roundsData } = useAdmissionRounds(selectedYear)
  const { data: pathsData, isLoading: pathsLoading } =
    useAdmissionPathsByAcademicInfo(academicInfoId)
  const updateMutation = useUpdatePathQuota()

  const paths = pathsData?.items ?? []
  const rounds = roundsData?.items ?? []

  const getCellValue = (
    pathId: number,
    field: "round_quota" | "admit_quota",
    fallback: number | null,
  ): number | null => {
    const edit = edits[pathId]
    if (edit && field in edit) return edit[field]
    return fallback
  }

  const handleCellChange = (
    pathId: number,
    field: "round_quota" | "admit_quota",
    value: string,
    other: number | null,
  ) => {
    const num = value === "" ? null : Number(value)
    if (num !== null && (isNaN(num) || num < 0)) {
      toast.error("Giá trị phải là số ≥ 0")
      return
    }
    setEdits((prev) => {
      const existing = prev[pathId] ?? {
        pathId,
        round_quota: field === "round_quota" ? num : other,
        admit_quota: field === "admit_quota" ? num : other,
      }
      return { ...prev, [pathId]: { ...existing, [field]: num } }
    })
  }

  const handleSave = async (pathId: number) => {
    const edit = edits[pathId]
    if (!edit) return
    try {
      await updateMutation.mutateAsync({
        pathId,
        data: {
          round_quota: edit.round_quota,
          admit_quota: edit.admit_quota,
        },
      })
      toast.success("Cập nhật chỉ tiêu thành công")
      setEdits((prev) => {
        const { [pathId]: _, ...rest } = prev
        return rest
      })
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      toast.error(detail ?? "Cập nhật thất bại")
    }
  }

  const isDirty = (pathId: number): boolean => pathId in edits

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Ma trận chỉ tiêu</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-4">
            <div>
              <label className="text-sm font-medium">Năm học:</label>
              <Select
                value={selectedYear.toString()}
                onValueChange={(v) => setSelectedYear(Number(v))}
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
            <div>
              <label className="text-sm font-medium">Đường tuyển sinh thuộc ngành (academic_info_id):</label>
              <Input
                type="number"
                placeholder="Nhập ID ngành (academic_info_id)"
                value={academicInfoId ?? ""}
                onChange={(e) =>
                  setAcademicInfoId(
                    e.target.value === "" ? undefined : Number(e.target.value),
                  )
                }
                className="w-48 ml-2 inline-flex"
              />
            </div>
            <Badge variant="outline">
              {rounds.length} đợt năm {selectedYear}
            </Badge>
          </div>

          {!academicInfoId && (
            <div className="text-sm text-muted-foreground">
              Nhập ID ngành để tải danh sách đường tuyển sinh.
            </div>
          )}

          {academicInfoId && pathsLoading && (
            <div className="text-sm text-muted-foreground">Đang tải...</div>
          )}

          {academicInfoId && !pathsLoading && paths.length === 0 && (
            <div className="text-sm text-muted-foreground">
              Không có đường tuyển sinh nào cho ngành này.
            </div>
          )}

          {paths.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Tên đường tuyển sinh</TableHead>
                  <TableHead>Đợt</TableHead>
                  <TableHead>Trạng thái</TableHead>
                  <TableHead>Chỉ tiêu nộp hồ sơ</TableHead>
                  <TableHead>Chỉ tiêu trúng tuyển</TableHead>
                  <TableHead>Đã nộp</TableHead>
                  <TableHead>Hành động</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paths.map((path) => {
                  const round = rounds.find((r) => r.id === path.admission_round_id)
                  const dirty = isDirty(path.id)
                  const roundQuotaVal = getCellValue(
                    path.id,
                    "round_quota",
                    path.round_quota ?? null,
                  )
                  const admitQuotaVal = getCellValue(
                    path.id,
                    "admit_quota",
                    path.admit_quota ?? null,
                  )
                  return (
                    <TableRow key={path.id} className={dirty ? "bg-amber-50" : ""}>
                      <TableCell>{path.id}</TableCell>
                      <TableCell>
                        {path.display_name ?? "(không tên)"}
                      </TableCell>
                      <TableCell>
                        {round ? (
                          <Badge variant="secondary">{round.round_code}</Badge>
                        ) : (
                          <Badge variant="outline">—</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant={path.status === "active" ? "default" : "outline"}>
                          {path.status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Input
                          type="number"
                          min={0}
                          value={roundQuotaVal ?? ""}
                          placeholder="∞"
                          onChange={(e) =>
                            handleCellChange(
                              path.id,
                              "round_quota",
                              e.target.value,
                              admitQuotaVal,
                            )
                          }
                          className="w-24"
                        />
                      </TableCell>
                      <TableCell>
                        <Input
                          type="number"
                          min={0}
                          value={admitQuotaVal ?? ""}
                          placeholder="∞"
                          onChange={(e) =>
                            handleCellChange(
                              path.id,
                              "admit_quota",
                              e.target.value,
                              roundQuotaVal,
                            )
                          }
                          className="w-24"
                        />
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">
                          {path.submission_count ?? 0}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Button
                          size="sm"
                          variant={dirty ? "default" : "ghost"}
                          disabled={!dirty || updateMutation.isPending}
                          onClick={() => handleSave(path.id)}
                        >
                          <Save className="h-4 w-4 mr-1" />
                          Lưu
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
