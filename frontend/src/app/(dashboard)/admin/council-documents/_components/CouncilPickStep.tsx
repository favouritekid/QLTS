"use client"

import { useMemo, useState } from "react"
import { Loader2 } from "lucide-react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { CURRENT_ADMISSIONS_YEAR } from "@/hooks/admissions/filterDefaults"
import { useAcademicYears, useAdmissionPrograms } from "@/hooks/admissions/useAdmissions"
import { useCouncilProfileSearch, useResolveCouncilCodes } from "@/hooks/admin/useCouncilDocuments"
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value"
import { parseRowsToList } from "@/lib/council-params"
import { getStatusConfig } from "@/lib/status-config"
import { useCouncilSelectionStore } from "@/lib/stores/council-selection.store"
import type { CouncilCodesOut, CouncilSetPreview } from "@/lib/zod/council-documents"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { majorLabel, pasteCodeReasonLabel, checkItemLabel, statusLabel } from "./display"

const PAGE_SIZE = 25
/** Trạng thái hồ sơ cho bộ lọc (đúng ba mức của bản mẫu); "Tất cả" = không gửi bộ lọc trạng thái. */
const STATUS_FILTER_OPTIONS = ["approved", "submitted", "resubmitted"] as const

interface Props {
  /** kiểm trước của ĐÚNG danh sách đang chọn (cột "Kiểm trước" / "Điểm" chỉ có cho hồ sơ đã chọn) */
  preview: CouncilSetPreview | undefined
  checking: boolean
  /** cờ `doi_ma` của máy chủ: có route đổi mã hồ sơ ⇒ hiện cách phụ dán mã */
  hasCodeChange: boolean
}

/**
 * Bước 1 — chọn hồ sơ (đặc tả 5.1, bản 2 mục 5.1). Tìm bằng `POST /sets/tim-ho-so` (từ khoá trong thân JSON, không URL);
 * lựa chọn nằm ở store RIÊNG của trang Hội đồng, giữ qua trang. Cột "Kiểm trước" chỉ lấy từ `kiem-truoc` cho hồ sơ
 * ĐÃ chọn, hồ sơ chưa chọn hiện "—" (không tạo đường cổng thứ hai).
 */
export function CouncilPickStep({ preview, checking, hasCodeChange }: Props) {
  const academicYear = useCouncilSelectionStore((s) => s.academicYear)
  const pickedId = useCouncilSelectionStore((s) => s.profileId)
  const setAcademicYear = useCouncilSelectionStore((s) => s.setAcademicYear)
  const add = useCouncilSelectionStore((s) => s.add)
  const docSet = useCouncilSelectionStore((s) => s.docSet)

  const { data: year } = useAcademicYears()
  const { data: programs } = useAdmissionPrograms()
  const [keyword, setKeyword] = useState("")
  const deferredKeyword = useDebouncedValue(keyword.trim(), 400)
  const [majorFilter, setMajorFilter] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [currentPage, setPage] = useState(1)
  /** yêu cầu đổi năm đang chờ xác nhận (có danh sách chọn); `null` = không có yêu cầu. `nam` null = bỏ chọn năm. */
  const [pendingYearChange, setPendingYearChange] = useState<{ year: number | null } | null>(null)

  const search = useCouncilProfileSearch(
    {
      academic_year: academicYear ?? 0,
      tu_khoa: deferredKeyword === "" ? null : deferredKeyword.slice(0, 100),
      major_ids: majorFilter === "" ? null : [Number(majorFilter)],
      trang_thai: statusFilter === "" ? null : [statusFilter],
      page: currentPage,
      page_size: PAGE_SIZE,
    },
    academicYear !== null,
  )

  const checkRows = useMemo(() => {
    const m = new Map<number, CouncilSetPreview["dong"][number]>()
    for (const d of preview?.dong ?? []) m.set(d.profile_id, d)
    return m
  }, [preview])

  const picked = useMemo(() => new Set(pickedId), [pickedId])
  const pageRows = search.data?.dong ?? []
  const pickedInPageCount = pageRows.filter((d) => picked.has(d.profile_id)).length
  const allPages = pageRows.length > 0 && pickedInPageCount === pageRows.length
  const one = pickedInPageCount > 0 && !allPages
  const total = search.data?.tong ?? 0
  const pageNumber = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const changeAcademicYear = (n: number | null) => {
    if (pickedId.length > 0 && n !== academicYear) setPendingYearChange({ year: n })
    else {
      setAcademicYear(n)
      setPage(1)
    }
  }

  const yearList = useMemo(() => {
    // Máy chủ chưa trả danh sách năm ⇒ dự phòng như màn "Hồ sơ tuyển sinh" (năm nay ± 1), để ô chọn năm không trống.
    const rows =
      year && year.length > 0
        ? year
        : [CURRENT_ADMISSIONS_YEAR + 1, CURRENT_ADMISSIONS_YEAR, CURRENT_ADMISSIONS_YEAR - 1]
    return academicYear !== null && !rows.includes(academicYear) ? [...rows, academicYear].sort((a, b) => b - a) : rows
  }, [year, academicYear])

  return (
    <div className="space-y-4" data-testid="buoc-chon">
      <p className="text-sm text-muted-foreground">
        Bước 1 — chọn hồ sơ đưa vào bộ văn bản Hội đồng: lọc, tìm, tick. Danh sách đang chọn giữ nguyên khi chuyển trang.
      </p>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <div className="space-y-1">
          <Label htmlFor="hd-tim">Tìm theo tên hoặc CCCD</Label>
          <Input
            id="hd-tim"
            data-testid="loc-tu-khoa"
            autoComplete="off"
            spellCheck={false}
            value={keyword}
            onChange={(e) => {
              setKeyword(e.target.value)
              setPage(1)
            }}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="hd-nam">Năm học (bắt buộc)</Label>
          <select
            id="hd-nam"
            data-testid="loc-nam"
            className="h-10 w-full rounded-md border border-border bg-card px-2 text-sm md:h-9"
            value={academicYear ?? ""}
            onChange={(e) => changeAcademicYear(e.target.value === "" ? null : Number(e.target.value))}
          >
            <option value="">— chọn năm học —</option>
            {yearList.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="hd-nganh">Ngành trên hồ sơ</Label>
          <select
            id="hd-nganh"
            data-testid="loc-nganh"
            className="h-10 w-full rounded-md border border-border bg-card px-2 text-sm md:h-9"
            value={majorFilter}
            onChange={(e) => {
              setMajorFilter(e.target.value)
              setPage(1)
            }}
          >
            <option value="">Tất cả ngành</option>
            {(programs ?? []).map((p) => (
              <option key={p.id} value={String(p.id)}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="hd-tt">Trạng thái hồ sơ</Label>
          <select
            id="hd-tt"
            data-testid="loc-trang-thai"
            className="h-10 w-full rounded-md border border-border bg-card px-2 text-sm md:h-9"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value)
              setPage(1)
            }}
          >
            <option value="">Tất cả</option>
            {STATUS_FILTER_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {getStatusConfig(t).label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {academicYear === null ? (
        <p className="text-sm text-muted-foreground" data-testid="chon-nam-truoc">
          Chọn năm học để bắt đầu tìm hồ sơ.
        </p>
      ) : (
        <>
          <div className="overflow-x-auto rounded border">
            <Table data-testid="bang-chon-ho-so">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">
                    <Checkbox
                      aria-label="Chọn cả trang"
                      data-testid="chon-ca-trang"
                      checked={allPages ? true : one ? "indeterminate" : false}
                      disabled={pageRows.length === 0}
                      onCheckedChange={(v) => {
                        if (v === true) add(pageRows.map((d) => d.profile_id))
                        else for (const d of pageRows) docSet(d.profile_id)
                      }}
                    />
                  </TableHead>
                  <TableHead>#</TableHead>
                  <TableHead>Họ tên</TableHead>
                  <TableHead>CCCD</TableHead>
                  <TableHead>Ngành trên hồ sơ</TableHead>
                  <TableHead>Đường xét</TableHead>
                  <TableHead>Điểm</TableHead>
                  <TableHead>Trạng thái</TableHead>
                  <TableHead>Kiểm trước</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {search.isPending ? (
                  <TableRow>
                    <TableCell colSpan={9} className="text-muted-foreground">
                      <Loader2 className="mr-2 inline h-4 w-4 animate-spin" /> Đang tìm hồ sơ…
                    </TableCell>
                  </TableRow>
                ) : null}
                {pageRows.map((d) => {
                  const k = checkRows.get(d.profile_id)
                  return (
                    <TableRow key={d.profile_id} data-testid={`ho-so-${d.profile_id}`}>
                      <TableCell>
                        <Checkbox
                          aria-label={`Chọn hồ sơ ${d.profile_id}`}
                          data-testid={`chon-${d.profile_id}`}
                          checked={picked.has(d.profile_id)}
                          onCheckedChange={(v) => (v === true ? add([d.profile_id]) : docSet(d.profile_id))}
                        />
                      </TableCell>
                      <TableCell>{d.profile_id}</TableCell>
                      <TableCell>{d.ho_ten}</TableCell>
                      <TableCell className="font-mono text-xs">{d.cccd}</TableCell>
                      {/* hồ sơ không có ngành ⇒ máy chủ trả chuỗi rỗng; hiện "—" như màn Hồ sơ tuyển sinh (Đ2-4) */}
                      <TableCell data-testid={`nganh-${d.profile_id}`}>{majorLabel(d.nganh_nhan)}</TableCell>
                      {/* danh sách tìm là dạng nhẹ (máy chủ luôn trả `duong_xet_nhan: null`): đường xét / điểm CHÍNH XÁC chỉ có
                          ở kiểm trước, nên chỉ hồ sơ ĐÃ chọn (đã kiểm) mới có giá trị */}
                      <TableCell data-testid={`duong-xet-${d.profile_id}`}>
                        {k ? (k.duong_xet_nhan ?? "—") : (d.duong_xet_nhan ?? "—")}
                      </TableCell>
                      <TableCell>{k ? (k.diem_in ?? "—") : "—"}</TableCell>
                      <TableCell data-testid={`trang-thai-${d.profile_id}`}>{statusLabel(d.trang_thai)}</TableCell>
                      <TableCell data-testid={`kiem-${d.profile_id}`}>
                        {k ? checkItemLabel(k.muc) : picked.has(d.profile_id) && checking ? "đang kiểm…" : "—"}
                      </TableCell>
                    </TableRow>
                  )
                })}
                {!search.isPending && pageRows.length === 0 && !search.isError ? (
                  <TableRow>
                    <TableCell colSpan={9} className="text-muted-foreground" data-testid="khong-co-ho-so">
                      Không có hồ sơ nào khớp bộ lọc.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
          <CouncilErrorAlert error={search.error} testId="tim-ho-so-loi" />
          <p className="text-xs text-muted-foreground" data-testid="chu-thich-nganh-ho-so">
            “Ngành trên hồ sơ” là ngành ghi trên hồ sơ lúc tìm. Ngành xét và đường xét chính xác chỉ có sau khi kiểm trước (hồ sơ đã
            chọn) — xem cột Đường xét, Điểm và Kiểm trước.
          </p>
          <div className="flex items-center justify-between text-sm">
            <span data-testid="phan-trang-nhan">
              {search.data ? `${total} hồ sơ · trang ${search.data.page}/${pageNumber}` : ""}
            </span>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={currentPage <= 1}
                onClick={() => setPage((t) => Math.max(1, t - 1))}
              >
                ‹ Trang trước
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={currentPage >= pageNumber}
                onClick={() => setPage((t) => t + 1)}
              >
                Trang sau ›
              </Button>
            </div>
          </div>
        </>
      )}

      {academicYear !== null && hasCodeChange ? <PasteCodes academicYear={academicYear} /> : null}

      <AlertDialog open={pendingYearChange !== null} onOpenChange={(isOpen) => !isOpen && setPendingYearChange(null)}>
        <AlertDialogContent data-testid="doi-nam-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Đổi năm học?</AlertDialogTitle>
            <AlertDialogDescription>
              Đang chọn {pickedId.length} hồ sơ của năm {academicYear}. Đổi năm học sẽ xoá danh sách đang chọn (id hồ sơ của năm này
              không dùng cho năm khác).
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Giữ nguyên</AlertDialogCancel>
            <AlertDialogAction
              data-testid="doi-nam-dong-y"
              onClick={() => {
                if (pendingYearChange) setAcademicYear(pendingYearChange.year)
                setPage(1)
                setPendingYearChange(null)
              }}
            >
              Đổi và xoá danh sách
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

/** Cách phụ: dán danh sách mã hồ sơ ⇒ máy chủ đổi sang id và báo SỐ DÒNG không khớp (không báo giá trị). */
function PasteCodes({ academicYear }: { academicYear: number }) {
  const add = useCouncilSelectionStore((s) => s.add)
  const resolveCodes = useResolveCouncilCodes()
  const [document, setDocument] = useState("")
  const [result, setResult] = useState<CouncilCodesOut | null>(null)
  const list = parseRowsToList(document)
  const hasCode = list.some((d) => d.trim() !== "")

  return (
    <details className="rounded border p-3" data-testid="dan-ma">
      <summary className="cursor-pointer text-sm font-medium">Cách phụ: dán danh sách mã hồ sơ có sẵn</summary>
      <div className="mt-3 space-y-2">
        <p className="text-xs text-muted-foreground">
          Mỗi dòng một mã — máy chủ đổi sang hồ sơ của năm học đã chọn và báo dòng không khớp.
        </p>
        <textarea
          data-testid="dan-ma-input"
          className="min-h-[6rem] w-full rounded-md border border-input bg-background px-2 py-1.5 font-mono text-sm"
          wrap="off"
          spellCheck={false}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          aria-label="Danh sách mã hồ sơ"
          value={document}
          disabled={resolveCodes.isPending}
          onChange={(e) => setDocument(e.target.value)}
        />
        <Button
          type="button"
          size="sm"
          disabled={!hasCode || resolveCodes.isPending}
          data-testid="dan-ma-them"
          onClick={() =>
            resolveCodes.mutate(
              { academic_year: academicYear, ma_ho_so: list },
              {
                onSuccess: (r) => {
                  add(r.profile_ids)
                  setResult(r)
                  if (r.dong_loi.length === 0) setDocument("")
                },
              },
            )
          }
        >
          {resolveCodes.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
          Thêm vào danh sách đang chọn
        </Button>
        <CouncilErrorAlert error={resolveCodes.error} testId="dan-ma-loi" />
        {result ? (
          <div className="text-sm" data-testid="dan-ma-ket-qua">
            <p>Đã thêm {result.profile_ids.length} hồ sơ.</p>
            {result.dong_loi.length > 0 ? (
              <ul className="list-disc pl-5 text-destructive" data-testid="dan-ma-dong-loi">
                {result.dong_loi.map((l) => (
                  <li key={l.dong}>{`Dòng ${l.dong}: ${pasteCodeReasonLabel(l.ly_do)}`}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </div>
    </details>
  )
}
