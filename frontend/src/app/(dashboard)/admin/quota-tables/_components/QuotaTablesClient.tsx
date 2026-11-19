"use client"

/**
 * GĐ2-F1 — trang "Bảng chỉ tiêu năm" (chỉ Admin — máy chủ là chốt: không phải Admin ⇒ 403 ⇒ trang báo, không kiểm vai ở
 * đây). Năm chưa có bảng ⇒ 404 ⇒ cho tạo (PUT `version` 0). Nút Sửa / Khoá / Mở khoá theo `available_actions` của máy chủ.
 */
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { readApiError } from "@/lib/error-handler"
import { useOfferingAcademicInfos, useProgramOfferings } from "@/hooks/admissions/useProgramData"
import { useQuotaTable } from "@/lib/hooks/use-quota-tables"
import { draftFromTable, memberLabel } from "@/lib/quota-tables/draft"
import { describeQuotaTableError } from "@/lib/quota-tables/messages"

import { QuotaTableEditor, type MemberOption } from "./QuotaTableEditor"
import { QuotaTableView } from "./QuotaTableView"

interface AcademicInfoLite {
  id: number
  offering_id: number
  academic_year: number
  annual_admission_quota?: number | null
  is_deleted?: boolean
}

interface OfferingLite {
  id: number
  offering_type?: string | null
  program?: { code?: string | null; name?: string | null } | null
}

/** Nối học vụ của ĐÚNG năm với tên ngành để hiển thị trong ô chọn — không quyết định ai được vào bảng (máy chủ kiểm). */
export function buildMemberOptions(infos: unknown, offerings: unknown, year: number): MemberOption[] {
  const ds = Array.isArray(infos) ? (infos as AcademicInfoLite[]) : []
  const os = new Map((Array.isArray(offerings) ? (offerings as OfferingLite[]) : []).map((o) => [o.id, o]))
  return ds
    .filter((i) => i.academic_year === year && !i.is_deleted)
    .map((i) => {
      const o = os.get(i.offering_id)
      return {
        offering_academic_info_id: i.id,
        label: memberLabel({
          offering_academic_info_id: i.id,
          major_code: o?.program?.code ?? null,
          major_name: o?.program?.name ?? null,
          offering_type: o?.offering_type ?? null,
        }),
        annual_admission_quota: typeof i.annual_admission_quota === "number" ? i.annual_admission_quota : null,
      }
    })
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
  const infos = useOfferingAcademicInfos()
  const offerings = useProgramOfferings()

  const options = useMemo(() => buildMemberOptions(infos.data, offerings.data, year), [infos.data, offerings.data, year])
  const labels = useMemo(() => {
    const m = new Map<number, string>()
    for (const o of options) m.set(o.offering_academic_info_id, o.label)
    for (const g of table.data?.groups ?? []) for (const x of g.members) m.set(x.offering_academic_info_id, memberLabel(x))
    return m
  }, [options, table.data])
  const labelOf = (id: number) => labels.get(id) ?? `Học vụ #${id}`

  const err = table.error ? readApiError(table.error) : null
  const noTable = err?.status === 404
  const data = table.data ?? null
  // GĐ2-F1: năm chưa có bảng — máy chủ vẫn trả dấu chỉ tiêu trong thân 404 để tạo bảng (version 0) không đè chỉ tiêu ai vừa sửa.
  const noTableFingerprint =
    noTable && typeof err?.data?.quota_fingerprint === "string" ? err.data.quota_fingerprint : ""

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
