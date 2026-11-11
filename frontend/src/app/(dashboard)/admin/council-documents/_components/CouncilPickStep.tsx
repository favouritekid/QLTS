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
import { dongNhapThanhDanhSach } from "@/lib/council-params"
import { getStatusConfig } from "@/lib/status-config"
import { useCouncilSelectionStore } from "@/lib/stores/council-selection.store"
import type { CouncilCodesOut, CouncilSetPreview } from "@/lib/zod/council-documents"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { nhanLyDoDanMa, nhanMucKiem } from "./hien-thi"

const CO_TRANG = 25
/** Trạng thái hồ sơ cho bộ lọc (đúng ba mức của bản mẫu); "Tất cả" = không gửi bộ lọc trạng thái. */
const TRANG_THAI_LOC = ["approved", "submitted", "resubmitted"] as const

interface Props {
  /** kiểm trước của ĐÚNG danh sách đang chọn (cột "Kiểm trước" / "Điểm" chỉ có cho hồ sơ đã chọn) */
  xemTruoc: CouncilSetPreview | undefined
  dangKiem: boolean
  /** cờ `doi_ma` của máy chủ: có route đổi mã hồ sơ ⇒ hiện cách phụ dán mã */
  coDoiMa: boolean
}

/**
 * Bước 1 — chọn hồ sơ (đặc tả 5.1, bản 2 mục 5.1). Tìm bằng `POST /sets/tim-ho-so` (từ khoá trong thân JSON, không URL);
 * lựa chọn nằm ở store RIÊNG của trang Hội đồng, giữ qua trang. Cột "Kiểm trước" chỉ lấy từ `kiem-truoc` cho hồ sơ
 * ĐÃ chọn, hồ sơ chưa chọn hiện "—" (không tạo đường cổng thứ hai).
 */
export function CouncilPickStep({ xemTruoc, dangKiem, coDoiMa }: Props) {
  const namHoc = useCouncilSelectionStore((s) => s.namHoc)
  const idChon = useCouncilSelectionStore((s) => s.idHoSo)
  const datNamHoc = useCouncilSelectionStore((s) => s.datNamHoc)
  const them = useCouncilSelectionStore((s) => s.them)
  const bo = useCouncilSelectionStore((s) => s.bo)

  const { data: nam } = useAcademicYears()
  const { data: nganh } = useAdmissionPrograms()
  const [tuKhoa, setTuKhoa] = useState("")
  const tuKhoaTre = useDebouncedValue(tuKhoa.trim(), 400)
  const [nganhLoc, setNganhLoc] = useState("")
  const [ttLoc, setTtLoc] = useState("")
  const [trang, setTrang] = useState(1)
  /** yêu cầu đổi năm đang chờ xác nhận (có danh sách chọn); `null` = không có yêu cầu. `nam` null = bỏ chọn năm. */
  const [choDoiNam, setChoDoiNam] = useState<{ nam: number | null } | null>(null)

  const tim = useCouncilProfileSearch(
    {
      academic_year: namHoc ?? 0,
      tu_khoa: tuKhoaTre === "" ? null : tuKhoaTre.slice(0, 100),
      major_ids: nganhLoc === "" ? null : [Number(nganhLoc)],
      trang_thai: ttLoc === "" ? null : [ttLoc],
      page: trang,
      page_size: CO_TRANG,
    },
    namHoc !== null,
  )

  const dongKiem = useMemo(() => {
    const m = new Map<number, CouncilSetPreview["dong"][number]>()
    for (const d of xemTruoc?.dong ?? []) m.set(d.profile_id, d)
    return m
  }, [xemTruoc])

  const chon = useMemo(() => new Set(idChon), [idChon])
  const dongTrang = tim.data?.dong ?? []
  const soChonTrongTrang = dongTrang.filter((d) => chon.has(d.profile_id)).length
  const tatCaTrang = dongTrang.length > 0 && soChonTrongTrang === dongTrang.length
  const mot = soChonTrongTrang > 0 && !tatCaTrang
  const tong = tim.data?.tong ?? 0
  const soTrang = Math.max(1, Math.ceil(tong / CO_TRANG))

  const doiNamHoc = (n: number | null) => {
    if (idChon.length > 0 && n !== namHoc) setChoDoiNam({ nam: n })
    else {
      datNamHoc(n)
      setTrang(1)
    }
  }

  const danhSachNam = useMemo(() => {
    // Máy chủ chưa trả danh sách năm ⇒ dự phòng như màn "Hồ sơ tuyển sinh" (năm nay ± 1), để ô chọn năm không trống.
    const ds =
      nam && nam.length > 0
        ? nam
        : [CURRENT_ADMISSIONS_YEAR + 1, CURRENT_ADMISSIONS_YEAR, CURRENT_ADMISSIONS_YEAR - 1]
    return namHoc !== null && !ds.includes(namHoc) ? [...ds, namHoc].sort((a, b) => b - a) : ds
  }, [nam, namHoc])

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
            value={tuKhoa}
            onChange={(e) => {
              setTuKhoa(e.target.value)
              setTrang(1)
            }}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="hd-nam">Năm học (bắt buộc)</Label>
          <select
            id="hd-nam"
            data-testid="loc-nam"
            className="h-10 w-full rounded-md border border-border bg-card px-2 text-sm md:h-9"
            value={namHoc ?? ""}
            onChange={(e) => doiNamHoc(e.target.value === "" ? null : Number(e.target.value))}
          >
            <option value="">— chọn năm học —</option>
            {danhSachNam.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="hd-nganh">Ngành</Label>
          <select
            id="hd-nganh"
            data-testid="loc-nganh"
            className="h-10 w-full rounded-md border border-border bg-card px-2 text-sm md:h-9"
            value={nganhLoc}
            onChange={(e) => {
              setNganhLoc(e.target.value)
              setTrang(1)
            }}
          >
            <option value="">Tất cả ngành</option>
            {(nganh ?? []).map((p) => (
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
            value={ttLoc}
            onChange={(e) => {
              setTtLoc(e.target.value)
              setTrang(1)
            }}
          >
            <option value="">Tất cả</option>
            {TRANG_THAI_LOC.map((t) => (
              <option key={t} value={t}>
                {getStatusConfig(t).label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {namHoc === null ? (
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
                      checked={tatCaTrang ? true : mot ? "indeterminate" : false}
                      disabled={dongTrang.length === 0}
                      onCheckedChange={(v) => {
                        if (v === true) them(dongTrang.map((d) => d.profile_id))
                        else for (const d of dongTrang) bo(d.profile_id)
                      }}
                    />
                  </TableHead>
                  <TableHead>#</TableHead>
                  <TableHead>Họ tên</TableHead>
                  <TableHead>CCCD</TableHead>
                  <TableHead>Ngành</TableHead>
                  <TableHead>Đường xét</TableHead>
                  <TableHead>Điểm</TableHead>
                  <TableHead>Trạng thái</TableHead>
                  <TableHead>Kiểm trước</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tim.isPending ? (
                  <TableRow>
                    <TableCell colSpan={9} className="text-muted-foreground">
                      <Loader2 className="mr-2 inline h-4 w-4 animate-spin" /> Đang tìm hồ sơ…
                    </TableCell>
                  </TableRow>
                ) : null}
                {dongTrang.map((d) => {
                  const k = dongKiem.get(d.profile_id)
                  return (
                    <TableRow key={d.profile_id} data-testid={`ho-so-${d.profile_id}`}>
                      <TableCell>
                        <Checkbox
                          aria-label={`Chọn hồ sơ ${d.profile_id}`}
                          data-testid={`chon-${d.profile_id}`}
                          checked={chon.has(d.profile_id)}
                          onCheckedChange={(v) => (v === true ? them([d.profile_id]) : bo(d.profile_id))}
                        />
                      </TableCell>
                      <TableCell>{d.profile_id}</TableCell>
                      <TableCell>{d.ho_ten}</TableCell>
                      <TableCell className="font-mono text-xs">{d.cccd}</TableCell>
                      <TableCell>{d.nganh_nhan}</TableCell>
                      <TableCell>{d.duong_xet_nhan ?? "—"}</TableCell>
                      <TableCell>{k ? (k.diem_in ?? "—") : "—"}</TableCell>
                      <TableCell>{d.trang_thai_nhan}</TableCell>
                      <TableCell data-testid={`kiem-${d.profile_id}`}>
                        {k ? nhanMucKiem(k.muc) : chon.has(d.profile_id) && dangKiem ? "đang kiểm…" : "—"}
                      </TableCell>
                    </TableRow>
                  )
                })}
                {!tim.isPending && dongTrang.length === 0 && !tim.isError ? (
                  <TableRow>
                    <TableCell colSpan={9} className="text-muted-foreground" data-testid="khong-co-ho-so">
                      Không có hồ sơ nào khớp bộ lọc.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
          <CouncilErrorAlert error={tim.error} testId="tim-ho-so-loi" />
          <div className="flex items-center justify-between text-sm">
            <span data-testid="phan-trang-nhan">
              {tim.data ? `${tong} hồ sơ · trang ${tim.data.page}/${soTrang}` : ""}
            </span>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={trang <= 1}
                onClick={() => setTrang((t) => Math.max(1, t - 1))}
              >
                ‹ Trang trước
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={trang >= soTrang}
                onClick={() => setTrang((t) => t + 1)}
              >
                Trang sau ›
              </Button>
            </div>
          </div>
        </>
      )}

      {namHoc !== null && coDoiMa ? <DanMa namHoc={namHoc} /> : null}

      <AlertDialog open={choDoiNam !== null} onOpenChange={(mo) => !mo && setChoDoiNam(null)}>
        <AlertDialogContent data-testid="doi-nam-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Đổi năm học?</AlertDialogTitle>
            <AlertDialogDescription>
              Đang chọn {idChon.length} hồ sơ của năm {namHoc}. Đổi năm học sẽ xoá danh sách đang chọn (id hồ sơ của năm này
              không dùng cho năm khác).
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Giữ nguyên</AlertDialogCancel>
            <AlertDialogAction
              data-testid="doi-nam-dong-y"
              onClick={() => {
                if (choDoiNam) datNamHoc(choDoiNam.nam)
                setTrang(1)
                setChoDoiNam(null)
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
function DanMa({ namHoc }: { namHoc: number }) {
  const them = useCouncilSelectionStore((s) => s.them)
  const doi = useResolveCouncilCodes()
  const [vanBan, setVanBan] = useState("")
  const [kq, setKq] = useState<CouncilCodesOut | null>(null)
  const danhSach = dongNhapThanhDanhSach(vanBan)
  const coMa = danhSach.some((d) => d.trim() !== "")

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
          value={vanBan}
          disabled={doi.isPending}
          onChange={(e) => setVanBan(e.target.value)}
        />
        <Button
          type="button"
          size="sm"
          disabled={!coMa || doi.isPending}
          data-testid="dan-ma-them"
          onClick={() =>
            doi.mutate(
              { academic_year: namHoc, ma_ho_so: danhSach },
              {
                onSuccess: (r) => {
                  them(r.profile_ids)
                  setKq(r)
                  if (r.dong_loi.length === 0) setVanBan("")
                },
              },
            )
          }
        >
          {doi.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
          Thêm vào danh sách đang chọn
        </Button>
        <CouncilErrorAlert error={doi.error} testId="dan-ma-loi" />
        {kq ? (
          <div className="text-sm" data-testid="dan-ma-ket-qua">
            <p>Đã thêm {kq.profile_ids.length} hồ sơ.</p>
            {kq.dong_loi.length > 0 ? (
              <ul className="list-disc pl-5 text-destructive" data-testid="dan-ma-dong-loi">
                {kq.dong_loi.map((l) => (
                  <li key={l.dong}>{`Dòng ${l.dong}: ${nhanLyDoDanMa(l.ly_do)}`}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </div>
    </details>
  )
}
