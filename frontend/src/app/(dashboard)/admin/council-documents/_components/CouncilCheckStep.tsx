"use client"

import { useMemo, useState } from "react"
import { Loader2, RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useCouncilSelectionStore } from "@/lib/stores/council-selection.store"
import { cn } from "@/lib/utils"
import type { CouncilSetPreview } from "@/lib/zod/council-documents"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { CouncilPreviewSummary } from "./CouncilPreviewSummary"
import { nganhTrinhDo, nhanMucKiem, thoiDiem } from "./hien-thi"

interface Props {
  xemTruoc: CouncilSetPreview | undefined
  dangKiem: boolean
  loi?: unknown
  /** id hồ sơ ĐÃ gửi kiểm, đúng thứ tự gửi — để đổi VỊ TRÍ `khong_tim_thay` (đếm từ 1) thành id */
  idDaGui: readonly number[]
  onKiemLai: () => void
  onQuayLai: () => void
  onTiep: () => void
}

/**
 * Bước 2 — Kiểm tra & chốt (đặc tả 5.2). Bảng theo `stt` MÁY CHỦ trả; KHÔNG có nút đổi thứ tự (thứ tự trên giấy do
 * máy chủ sắp, đổi chỗ ở đây không đổi được). Lý do chặn / cần xác nhận hiện NGUYÊN VĂN câu của cổng. "Chốt" bị khoá
 * khi còn dòng bị chặn hoặc kết quả kiểm cũ hơn lần đổi danh sách cuối.
 */
export function CouncilCheckStep({ xemTruoc, dangKiem, loi, idDaGui, onKiemLai, onQuayLai, onTiep }: Props) {
  const bo = useCouncilSelectionStore((s) => s.bo)
  const soDangChon = useCouncilSelectionStore((s) => s.idHoSo.length)
  const [daMo, setDaMo] = useState<ReadonlySet<number>>(new Set())

  const khongTimThay = useMemo(
    () =>
      (xemTruoc?.khong_tim_thay ?? [])
        .map((viTri) => idDaGui[viTri - 1])
        .filter((id): id is number => typeof id === "number"),
    [xemTruoc, idDaGui],
  )

  const t = xemTruoc?.tom_tat
  const lyDoKhoa = dangKiem
    ? "Đang kiểm lại — chờ kết quả."
    : loi
      ? "Chưa có kết quả kiểm — bấm “Kiểm tra lại”."
      : !t
        ? "Chưa có kết quả kiểm."
        : khongTimThay.length > 0
          ? `${khongTimThay.length} hồ sơ trong danh sách không còn tìm thấy — bỏ khỏi bộ.`
          : t.bi_chan > 0
            ? `Còn ${t.bi_chan} dòng bị chặn: sửa hồ sơ rồi bấm “Kiểm tra lại”, hoặc bỏ khỏi bộ.`
            : t.tong === 0
              ? "Danh sách trống."
              : null

  return (
    <div className="space-y-4" data-testid="buoc-kiem-tra">
      <p className="text-sm text-muted-foreground">
        Bước 2 — mỗi dòng là một hồ sơ sẽ gửi dựng, đúng thứ tự gửi. Sửa được thì mở hồ sơ để sửa; không sửa được thì bỏ khỏi bộ.
      </p>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <CouncilPreviewSummary soDangChon={soDangChon} xemTruoc={xemTruoc} dangKiem={dangKiem} loi={loi} />
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          {xemTruoc ? <span data-testid="kiem-luc">Kiểm lúc {thoiDiem(xemTruoc.kiem_luc)}</span> : null}
          <Button type="button" variant="outline" size="sm" onClick={onKiemLai} disabled={dangKiem} data-testid="kiem-lai">
            {dangKiem ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-1 h-4 w-4" />}
            Kiểm tra lại
          </Button>
        </div>
      </div>

      <details className="rounded border p-3 text-sm" data-testid="thu-tu-tren-giay">
        <summary className="cursor-pointer font-medium">Thứ tự trên giấy</summary>
        <div className="mt-2 space-y-2 text-muted-foreground">
          <p>
            Thứ tự dòng do máy chủ sắp, giống thứ tự trong Quyết định: theo nhóm ngành – trình độ; trong mỗi nhóm theo điểm xét
            tuyển giảm dần, bằng điểm thì theo tên. Quyết định đánh số lại từ 1 ở mỗi ngành — cột “Dòng” ghi kèm số ấy.
          </p>
          <p>
            Danh sách xét tuyển (Word và Excel, mỗi nhóm ngành một bộ): bảng danh sách xếp theo tên; bảng điểm xếp theo điểm giảm
            dần. Biên bản: chỉ có số liệu theo ngành, không có tên từng em.
          </p>
          <p>Vì vậy màn này không có nút đổi thứ tự: đổi chỗ ở đây không đổi được thứ tự trên giấy.</p>
        </div>
      </details>

      {khongTimThay.length > 0 ? (
        <div className="rounded border border-destructive/50 p-3 text-sm" role="alert" data-testid="khong-tim-thay">
          <p>
            {khongTimThay.length} hồ sơ trong danh sách không còn tìm thấy (đã đổi năm học / ngoài phạm vi của bạn / không còn).
          </p>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="mt-2"
            data-testid="bo-khong-tim-thay"
            onClick={() => {
              for (const id of khongTimThay) bo(id)
            }}
          >
            Bỏ các hồ sơ này khỏi danh sách
          </Button>
        </div>
      ) : null}

      {xemTruoc ? (
        <div className={cn("overflow-x-auto rounded border", dangKiem && "opacity-60")} aria-busy={dangKiem} data-testid="khung-bang-kiem-tra">
          <Table data-testid="bang-kiem-tra">
            <TableHeader>
              <TableRow>
                <TableHead>Dòng</TableHead>
                <TableHead>Họ tên · trạng thái</TableHead>
                <TableHead>Ngành · đường xét</TableHead>
                <TableHead>Điểm</TableHead>
                <TableHead>Kết quả kiểm</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {xemTruoc.dong.map((d) => (
                <TableRow
                  key={d.profile_id}
                  data-testid={`dong-${d.profile_id}`}
                  className={cn(d.muc === "bi_chan" && "bg-destructive/5", d.muc === "can_xac_nhan" && "bg-warning-50")}
                >
                  <TableCell data-testid={`stt-${d.profile_id}`}>
                    {d.stt} <span className="text-xs text-muted-foreground">(QĐ: {d.stt_qd})</span>
                  </TableCell>
                  <TableCell>
                    <div>{d.ho_ten}</div>
                    <div className="text-xs text-muted-foreground">{d.trang_thai_nhan}</div>
                  </TableCell>
                  <TableCell>
                    <div>{nganhTrinhDo(d.nganh_nhan, d.trinh_do)}</div>
                    <div className="text-xs text-muted-foreground">{d.duong_xet_nhan ?? "—"}</div>
                  </TableCell>
                  <TableCell>{d.diem_in ?? "—"}</TableCell>
                  <TableCell data-testid={`muc-${d.profile_id}`}>
                    <div className="font-medium">{nhanMucKiem(d.muc)}</div>
                    {d.ly_do.map((l) => (
                      <div key={l.ma} className="text-xs" data-testid={`ly-do-${d.profile_id}`}>
                        {l.cau}
                      </div>
                    ))}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    <a
                      href={`/admissions/${d.profile_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-primary hover:underline"
                      data-testid={`mo-ho-so-${d.profile_id}`}
                      onClick={() => setDaMo((s) => new Set(s).add(d.profile_id))}
                    >
                      Mở hồ sơ để sửa ↗
                    </a>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      data-testid={`bo-khoi-bo-${d.profile_id}`}
                      onClick={() => bo(d.profile_id)}
                    >
                      Bỏ khỏi bộ
                    </Button>
                    {daMo.has(d.profile_id) ? (
                      <div className="text-xs text-muted-foreground" data-testid={`da-mo-${d.profile_id}`}>
                        Đã mở hồ sơ ở thẻ mới — sửa xong bấm “Kiểm tra lại”.
                      </div>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}

      {!xemTruoc && !dangKiem && loi ? <CouncilErrorAlert error={loi} testId="kiem-tra-loi" /> : null}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button type="button" variant="outline" onClick={onQuayLai} data-testid="quay-lai-chon">
          ← Quay lại chọn thêm
        </Button>
        <div className="flex items-center gap-3">
          {lyDoKhoa ? (
            <span className="text-sm text-muted-foreground" data-testid="ly-do-khoa-chot">
              {lyDoKhoa}
            </span>
          ) : null}
          <Button type="button" onClick={onTiep} disabled={lyDoKhoa !== null} data-testid="chot-tiep">
            Chốt danh sách & tiếp →
          </Button>
        </div>
      </div>
    </div>
  )
}
