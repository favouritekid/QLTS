"use client"

/**
 * GĐ2-F1 — trang "Bảng chỉ tiêu năm" (chỉ Admin — máy chủ là chốt: không phải Admin ⇒ 403 ⇒ trang báo, không kiểm vai ở
 * đây). Năm chưa có bảng ⇒ 404 ⇒ cho tạo (PUT `version` 0). Nút Sửa / Khoá / Mở khoá theo `available_actions` của máy chủ.
 */
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { readApiError } from "@/lib/error-handler"
import { useQuotaTable } from "@/lib/hooks/use-quota-tables"
import { draftFromTable, memberLabel } from "@/lib/quota-tables/draft"
import { describeQuotaTableError } from "@/lib/quota-tables/messages"
import { parseYearAcademicInfos, type QuotaYearAcademicInfo } from "@/lib/zod/quota-tables"

import { QuotaTableEditor, type MemberOption } from "./QuotaTableEditor"
import { QuotaTableView } from "./QuotaTableView"

/**
 * Danh sách "thêm ngành" + giá trị điền sẵn — CHỈ từ học vụ máy chủ trả KÈM dấu chỉ tiêu (GET bảng; năm chưa có bảng: thân 404),
 * cùng một lần đọc với dấu (Codex lượt 3, rà độc lập). Không lấy từ danh mục học vụ (`["academic-infos"]`): bộ đệm ấy có thể cũ
 * hơn dấu ⇒ điền chỉ tiêu cũ rồi lưu với dấu mới ⇒ máy chủ nhận ⇒ ghi đè im lặng chỉ tiêu người khác vừa sửa. Chỉ lọc để hiển thị
 * (bỏ học vụ đã xoá mềm) — không quyết định ai được vào bảng (máy chủ kiểm).
 */
export function buildMemberOptions(infos: QuotaYearAcademicInfo[]): MemberOption[] {
  return infos
    .filter((i) => !i.is_deleted)
    .map((i) => ({
      offering_academic_info_id: i.offering_academic_info_id,
      label: memberLabel(i),
      annual_admission_quota: i.annual_admission_quota,
    }))
    .sort((a, b) => a.label.localeCompare(b.label, "vi"))
}

function buildYearOptions(): number[] {
  const current = new Date().getFullYear()
  return Array.from({ length: 6 }, (_, i) => current - 2 + i)
}

export function QuotaTablesClient({ initialYear }: { initialYear?: number }) {
  const [year, setYear] = useState<number>(() => initialYear ?? new Date().getFullYear())
  const [mode, setMode] = useState<"view" | "edit">("view")
  const yearOptions = buildYearOptions()
  const table = useQuotaTable(year)

  const err = table.error ? readApiError(table.error) : null
  const noTable = err?.status === 404
  const data = table.data ?? null
  // GĐ2-F1: năm chưa có bảng — máy chủ vẫn trả dấu chỉ tiêu trong thân 404 để tạo bảng (version 0) không đè chỉ tiêu ai vừa sửa.
  const noTableFingerprint =
    noTable && typeof err?.data?.quota_fingerprint === "string" ? err.data.quota_fingerprint : ""
  // Học vụ của năm CÙNG ảnh với dấu: bảng có (200) ⇒ `academic_infos` của bảng; năm chưa có bảng ⇒ `academic_infos` trong thân 404.
  const noTableInfos = noTable ? err?.data?.academic_infos : undefined
  const snapshotInfos = useMemo(
    () => (data ? data.academic_infos : parseYearAcademicInfos(noTableInfos)),
    [data, noTableInfos],
  )

  const options = useMemo(() => buildMemberOptions(snapshotInfos), [snapshotInfos])
  const labels = useMemo(() => {
    const m = new Map<number, string>()
    for (const o of options) m.set(o.offering_academic_info_id, o.label)
    for (const g of data?.groups ?? []) for (const x of g.members) m.set(x.offering_academic_info_id, memberLabel(x))
    return m
  }, [options, data])
  const labelOf = (id: number) => labels.get(id) ?? `Học vụ #${id}`

  return (
    <div className="container mx-auto space-y-6 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Bảng chỉ tiêu năm</h1>
          <p className="text-sm text-muted-foreground">
            Nhóm ngành, trần chỉ tiêu nhóm và chỉ tiêu năm của từng ngành. Khoá bảng trước khi xét tuyển; mở khoá phải có
            lý do.
          </p>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="nam-bang-chi-tieu" className="text-xs text-muted-foreground">
            Năm tuyển sinh
          </label>
          <Select
            value={String(year)}
            onValueChange={(v) => {
              setYear(Number(v))
              setMode("view")
            }}
            disabled={mode === "edit"}
          >
            <SelectTrigger id="nam-bang-chi-tieu" className="w-[120px]">
              <SelectValue placeholder="Năm" />
            </SelectTrigger>
            <SelectContent>
              {yearOptions.map((y) => (
                <SelectItem key={y} value={String(y)}>
                  {y}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {table.isLoading && <p className="text-sm text-muted-foreground">Đang tải bảng chỉ tiêu…</p>}

      {err && !noTable && (
        <p role="alert" className="text-sm text-destructive" data-testid="loi-tai-bang">
          {describeQuotaTableError(table.error, { year, labelOf })}
        </p>
      )}

      {mode === "edit" && (noTable || data) && (
        <QuotaTableEditor
          year={year}
          version={data?.version ?? 0}
          quotaFingerprint={data?.quota_fingerprint ?? noTableFingerprint}
          initialGroups={draftFromTable(data)}
          options={options}
          labelOf={labelOf}
          onCancel={() => setMode("view")}
          onSaved={() => setMode("view")}
        />
      )}

      {mode === "view" && noTable && (
        <div className="space-y-3 rounded-md border border-dashed p-4" data-testid="chua-co-bang">
          <p className="text-sm">Năm {year} chưa có bảng chỉ tiêu.</p>
          <Button onClick={() => setMode("edit")} data-testid="nut-tao-bang">
            Tạo bảng chỉ tiêu năm {year}
          </Button>
        </div>
      )}

      {mode === "view" && data && <QuotaTableView table={data} labelOf={labelOf} onEdit={() => setMode("edit")} />}
    </div>
  )
}
