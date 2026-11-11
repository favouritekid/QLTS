"use client"

import Link from "next/link"
import { useState } from "react"
import { Download, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useAcademicYears } from "@/hooks/admissions/useAdmissions"
import { useCouncilSets, useDownloadCouncilSetZip } from "@/hooks/admin/useCouncilDocuments"
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value"
import { NHAN_CHUA_XAC_DINH } from "@/lib/council-submission"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import {
  CHU_THICH_CHUA_GHI_NHAN,
  ngay,
  nguoiHienThi,
  nhanTinhTrangBo,
  thoiDiem,
  tomTatQuyetDinh,
} from "./hien-thi"

const CO_TRANG = 50
const TINH_TRANG = ["chua_ghi_nhan", "con_hieu_luc", "het_hieu_luc", "da_huy_ghi_nhan", "chua_xac_dinh"] as const

interface Props {
  canOpenDetail: boolean
  /** cờ `tai_ca_bo` của máy chủ — nút "Tải cả bộ" từng dòng */
  canZip?: boolean
}

/**
 * Danh sách bộ văn bản (đặc tả 5.7): Bộ · Năm · Quyết định · Hồ sơ · Tình trạng · Người tạo · Dựng lúc · [Mở] [Tải cả bộ].
 * Máy chủ LỌC theo phạm vi (admin: mọi bộ; quản lý: bộ của đơn vị mình). Tình trạng / tên người tạo / Quyết định do MÁY
 * CHỦ trả (⏳ chờ — đặc tả 3.4); vắng ⇒ "—", giao diện KHÔNG tự suy từ chỗ khác. Bộ lọc gửi lên máy chủ; máy chủ cũ bỏ qua.
 */
export function CouncilSetList({ canOpenDetail, canZip = false }: Props) {
  const [offset, setOffset] = useState(0)
  const [soQd, setSoQd] = useState("")
  const soQdTre = useDebouncedValue(soQd, 400)
  const [nam, setNam] = useState("")
  const [tt, setTt] = useState("")
  const { data: namCo } = useAcademicYears()
  const zip = useDownloadCouncilSetZip()

  const q = useCouncilSets(
    {
      limit: CO_TRANG,
      offset,
      ...(soQdTre ? { so_quyet_dinh: soQdTre } : {}),
      ...(nam ? { nam_hoc: Number(nam) } : {}),
      ...(tt ? { tinh_trang: tt } : {}),
    },
    true,
  )

  const dangLoc = soQd !== "" || nam !== "" || tt !== ""

  const loc = (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" data-testid="set-list-filters">
      <div className="space-y-1">
        <Label htmlFor="ds-so-qd">Tìm theo số Quyết định</Label>
        <Input
          id="ds-so-qd"
          data-testid="loc-so-qd"
          inputMode="numeric"
          autoComplete="off"
          value={soQd}
          onChange={(e) => {
            setSoQd(e.target.value.replace(/[^0-9]/g, "").slice(0, 6))
            setOffset(0)
          }}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="ds-nam">Năm học</Label>
        <select
          id="ds-nam"
          data-testid="loc-nam-bo"
          className="h-10 w-full rounded-md border border-border bg-card px-2 text-sm md:h-9"
          value={nam}
          onChange={(e) => {
            setNam(e.target.value)
            setOffset(0)
          }}
        >
          <option value="">Tất cả</option>
          {(namCo ?? []).map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="ds-tt">Tình trạng</Label>
        <select
          id="ds-tt"
          data-testid="loc-tinh-trang"
          className="h-10 w-full rounded-md border border-border bg-card px-2 text-sm md:h-9"
          value={tt}
          onChange={(e) => {
            setTt(e.target.value)
            setOffset(0)
          }}
        >
          <option value="">Tất cả</option>
          {TINH_TRANG.map((t) => (
            <option key={t} value={t}>
              {t === "chua_xac_dinh" ? `${nhanTinhTrangBo(t)} (lượt gửi chưa rõ)` : nhanTinhTrangBo(t)}
            </option>
          ))}
        </select>
      </div>
    </div>
  )

  if (q.isPending) {
    return (
      <div className="space-y-3">
        {loc}
        <div className="flex items-center gap-2 text-muted-foreground" data-testid="set-list-loading">
          <Loader2 className="h-4 w-4 animate-spin" /> Đang tải danh sách bộ văn bản…
        </div>
      </div>
    )
  }
  if (q.isError) {
    return (
      <div className="space-y-3">
        {loc}
        <CouncilErrorAlert error={q.error} testId="set-list-error" />
      </div>
    )
  }

  const ds = q.data
  return (
    <div className="space-y-3">
      {loc}
      {ds.length === 0 ? (
        <p className="text-muted-foreground" data-testid="set-list-empty">
          {offset > 0 ? "Hết danh sách." : dangLoc ? "Không có bộ nào khớp bộ lọc." : "Chưa có bộ văn bản nào trong phạm vi của bạn."}
        </p>
      ) : (
        <Table data-testid="set-list">
          <TableHeader>
            <TableRow>
              <TableHead>Bộ</TableHead>
              <TableHead>Năm</TableHead>
              <TableHead>Quyết định</TableHead>
              <TableHead className="text-right">Hồ sơ</TableHead>
              <TableHead>Tình trạng</TableHead>
              <TableHead>Người tạo</TableHead>
              <TableHead>Dựng lúc</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {ds.map((b) => {
              const qd = tomTatQuyetDinh(b.quyet_dinh)
              const khongRo = b.tinh_trang === "chua_xac_dinh" || (b.luot_gui_cho ?? null) !== null
              const href = `/admin/council-documents/${b.id}${khongRo ? "?buoc=ghi-nhan" : ""}`
              return (
                <TableRow key={b.id} data-testid={`set-row-${b.id}`}>
                  <TableCell>
                    <span className="font-medium">#{b.id}</span>
                  </TableCell>
                  <TableCell>
                    <div>{b.nam_hoc ?? "—"}</div>
                    <div className="text-xs text-muted-foreground">{b.trinh_do}</div>
                  </TableCell>
                  <TableCell data-testid={`qd-${b.id}`}>
                    {qd && qd.so ? (
                      <>
                        <div>
                          Số {qd.so}
                          {qd.ngay ? ` · ${ngay(qd.ngay)}` : ""}
                        </div>
                        {qd.goc ? (
                          <div className="text-xs text-muted-foreground">
                            bổ sung cho số {qd.goc.so} ({ngay(qd.goc.ngay)})
                          </div>
                        ) : null}
                      </>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell className="text-right">{b.so_ho_so}</TableCell>
                  <TableCell data-testid={`tt-${b.id}`}>
                    {b.tinh_trang === undefined && !khongRo ? (
                      "—"
                    ) : (
                      <>
                        <div>{khongRo ? NHAN_CHUA_XAC_DINH : nhanTinhTrangBo(b.tinh_trang ?? "")}</div>
                        {!khongRo && b.tinh_trang === "chua_ghi_nhan" ? (
                          <div className="text-xs text-muted-foreground">{CHU_THICH_CHUA_GHI_NHAN}</div>
                        ) : null}
                      </>
                    )}
                  </TableCell>
                  <TableCell>{nguoiHienThi(b.nguoi_tao_ten, b.nguoi_tao_id)}</TableCell>
                  <TableCell>{thoiDiem(b.tao_luc)}</TableCell>
                  <TableCell className="whitespace-nowrap">
                    {canOpenDetail ? (
                      <Button asChild variant="outline" size="sm">
                        <Link href={href} data-testid={`mo-bo-${b.id}`}>
                          Mở
                        </Link>
                      </Button>
                    ) : null}
                    {canZip ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={zip.isPending}
                        data-testid={`tai-ca-bo-${b.id}`}
                        onClick={() => zip.mutate({ setId: b.id })}
                      >
                        {zip.isPending && zip.variables?.setId === b.id ? (
                          <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                        ) : (
                          <Download className="mr-1 h-4 w-4" />
                        )}
                        Tải cả bộ
                      </Button>
                    ) : null}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
      <CouncilErrorAlert error={zip.error} testId="set-list-zip-error" />
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={offset === 0 || q.isFetching}
          onClick={() => setOffset((o) => Math.max(0, o - CO_TRANG))}
          data-testid="set-list-prev"
        >
          Trang trước
        </Button>
        <span className="text-sm text-muted-foreground">
          Trang {Math.floor(offset / CO_TRANG) + 1}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={ds.length < CO_TRANG || q.isFetching}
          onClick={() => setOffset((o) => o + CO_TRANG)}
          data-testid="set-list-next"
        >
          Trang sau
        </Button>
      </div>
    </div>
  )
}
