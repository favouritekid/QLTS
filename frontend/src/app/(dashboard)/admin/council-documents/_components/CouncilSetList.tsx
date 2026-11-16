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
import { useCouncilSetCreators, useCouncilSets, useDownloadCouncilSetZip } from "@/hooks/admin/useCouncilDocuments"
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value"
import { UNDETERMINED_LABEL } from "@/lib/council-submission"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import {
  NOT_RECORDED_NOTE,
  formatDate,
  userLabel,
  setStateLabel,
  formatTime,
} from "./display"

const PAGE_SIZE = 50
const STATE_OPTIONS = ["chua_ghi_nhan", "con_hieu_luc", "het_hieu_luc", "da_huy_ghi_nhan", "chua_xac_dinh"] as const

interface Props {
  canOpenDetail: boolean
  /** cờ `tai_ca_bo` của máy chủ — nút "Tải cả bộ" từng dòng */
  canZip?: boolean
  /** cờ `xem_nguoi_tao_bo` của máy chủ — bộ lọc "Người tạo" (không có cờ ⇒ không hiện và KHÔNG gọi route) */
  canFilterCreator?: boolean
}

/**
 * Danh sách bộ văn bản (đặc tả 5.7): Bộ · Năm · Quyết định · Hồ sơ · Tình trạng · Người tạo · Dựng lúc · [Mở] [Tải cả bộ].
 * Máy chủ LỌC theo phạm vi (admin: mọi bộ; quản lý: bộ của đơn vị mình). Tình trạng / tên người tạo / Quyết định do MÁY
 * CHỦ trả (đặc tả 3.4, máy chủ `083a428d`); `null` ⇒ "—", giao diện KHÔNG tự suy từ chỗ khác. Bốn bộ lọc (số Quyết định,
 * năm học, tình trạng, người tạo) LỌC Ở MÁY CHỦ — giao diện chỉ gửi giá trị, không lọc lại.
 */
export function CouncilSetList({ canOpenDetail, canZip = false, canFilterCreator = false }: Props) {
  const [offset, setOffset] = useState(0)
  const [decisionNumber, setDecisionNumber] = useState("")
  const deferredDecisionNumber = useDebouncedValue(decisionNumber, 400)
  const [year, setYear] = useState("")
  const [status, setStatus] = useState("")
  const [creator, setCreator] = useState("")
  const { data: yearOptions } = useAcademicYears()
  const creatorOptions = useCouncilSetCreators(canFilterCreator)
  const zip = useDownloadCouncilSetZip()

  const q = useCouncilSets(
    {
      limit: PAGE_SIZE,
      offset,
      ...(deferredDecisionNumber ? { so_quyet_dinh: deferredDecisionNumber } : {}),
      ...(year ? { nam_hoc: Number(year) } : {}),
      ...(status ? { tinh_trang: status } : {}),
      ...(canFilterCreator && creator ? { nguoi_tao_id: Number(creator) } : {}),
    },
    true,
  )

  const filtering = decisionNumber !== "" || year !== "" || status !== "" || (canFilterCreator && creator !== "")

  const filters = (
    <div className={`grid grid-cols-1 gap-3 ${canFilterCreator ? "sm:grid-cols-4" : "sm:grid-cols-3"}`} data-testid="set-list-filters">
      <div className="space-y-1">
        <Label htmlFor="ds-so-qd">Tìm theo số Quyết định</Label>
        <Input
          id="ds-so-qd"
          data-testid="loc-so-qd"
          inputMode="numeric"
          autoComplete="off"
          value={decisionNumber}
          onChange={(e) => {
            setDecisionNumber(e.target.value.replace(/[^0-9]/g, "").slice(0, 6))
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
          value={year}
          onChange={(e) => {
            setYear(e.target.value)
            setOffset(0)
          }}
        >
          <option value="">Tất cả</option>
          {(yearOptions ?? []).map((y) => (
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
          value={status}
          onChange={(e) => {
            setStatus(e.target.value)
            setOffset(0)
          }}
        >
          <option value="">Tất cả</option>
          {STATE_OPTIONS.map((t) => (
            <option key={t} value={t}>
              {t === "chua_xac_dinh" ? `${setStateLabel(t)} (lượt gửi chưa rõ)` : setStateLabel(t)}
            </option>
          ))}
        </select>
      </div>
      {canFilterCreator ? (
        <div className="space-y-1">
          <Label htmlFor="ds-nguoi-tao">Người tạo</Label>
          <select
            id="ds-nguoi-tao"
            data-testid="loc-nguoi-tao"
            className="h-10 w-full rounded-md border border-border bg-card px-2 text-sm md:h-9"
            value={creator}
            disabled={creatorOptions.isError}
            onChange={(e) => {
              setCreator(e.target.value)
              setOffset(0)
            }}
          >
            <option value="">Tất cả</option>
            {(creatorOptions.data ?? []).map((n) => (
              <option key={n.id} value={n.id}>
                {n.ten}
              </option>
            ))}
          </select>
          {creatorOptions.isError ? (
            <p className="text-xs text-muted-foreground" data-testid="loc-nguoi-tao-loi">
              Không tải được danh sách người tạo — bộ lọc này tạm tắt.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  )

  if (q.isPending) {
    return (
      <div className="space-y-3">
        {filters}
        <div className="flex items-center gap-2 text-muted-foreground" data-testid="set-list-loading">
          <Loader2 className="h-4 w-4 animate-spin" /> Đang tải danh sách bộ văn bản…
        </div>
      </div>
    )
  }
  if (q.isError) {
    return (
      <div className="space-y-3">
        {filters}
        <CouncilErrorAlert error={q.error} testId="set-list-error" />
      </div>
    )
  }

  const rows = q.data
  return (
    <div className="space-y-3">
      {filters}
      {rows.length === 0 ? (
        <p className="text-muted-foreground" data-testid="set-list-empty">
          {offset > 0 ? "Hết danh sách." : filtering ? "Không có bộ nào khớp bộ lọc." : "Chưa có bộ văn bản nào trong phạm vi của bạn."}
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
            {rows.map((b) => {
              const decision = b.quyet_dinh
              const unknown = b.tinh_trang === "chua_xac_dinh" || b.luot_gui_cho !== null
              const href = `/admin/council-documents/${b.id}${unknown ? "?buoc=ghi-nhan" : ""}`
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
                    {decision ? (
                      <>
                        <div>
                          Số {decision.so_quyet_dinh} · {formatDate(decision.ngay_ky)}
                        </div>
                        {decision.goc ? (
                          <div className="text-xs text-muted-foreground">
                            bổ sung cho số {decision.goc.so_quyet_dinh} ({formatDate(decision.goc.ngay_ky)})
                          </div>
                        ) : null}
                      </>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell className="text-right">{b.so_ho_so}</TableCell>
                  <TableCell data-testid={`tt-${b.id}`}>
                    {b.tinh_trang === null && !unknown ? (
                      "—"
                    ) : (
                      <>
                        <div>{unknown ? UNDETERMINED_LABEL : setStateLabel(b.tinh_trang ?? "")}</div>
                        {!unknown && b.tinh_trang === "chua_ghi_nhan" ? (
                          <div className="text-xs text-muted-foreground">{NOT_RECORDED_NOTE}</div>
                        ) : null}
                      </>
                    )}
                  </TableCell>
                  <TableCell>{userLabel(b.nguoi_tao_ten, b.nguoi_tao_id)}</TableCell>
                  <TableCell>{formatTime(b.tao_luc)}</TableCell>
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
          onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
          data-testid="set-list-prev"
        >
          Trang trước
        </Button>
        <span className="text-sm text-muted-foreground">
          Trang {Math.floor(offset / PAGE_SIZE) + 1}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={rows.length < PAGE_SIZE || q.isFetching}
          onClick={() => setOffset((o) => o + PAGE_SIZE)}
          data-testid="set-list-next"
        >
          Trang sau
        </Button>
      </div>
    </div>
  )
}
