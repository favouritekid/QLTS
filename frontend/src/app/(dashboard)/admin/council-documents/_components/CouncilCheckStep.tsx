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
import { majorWithLevel, checkItemLabel, checkReasonText, statusLabel, formatTime } from "./display"

interface Props {
  preview: CouncilSetPreview | undefined
  checking: boolean
  error?: unknown
  /** id hồ sơ ĐÃ gửi kiểm, đúng thứ tự gửi — để đổi VỊ TRÍ `khong_tim_thay` (đếm từ 1) thành id */
  submittedIds: readonly number[]
  onRecheck: () => void
  onBack: () => void
  onNext: () => void
}

/**
 * Bước 2 — Kiểm tra & chốt (đặc tả 5.2). Bảng theo `stt` MÁY CHỦ trả; KHÔNG có nút đổi thứ tự (thứ tự trên giấy do
 * máy chủ sắp, đổi chỗ ở đây không đổi được). Lý do chặn / cần xác nhận hiện NGUYÊN VĂN câu của cổng. "Chốt" bị khoá
 * khi còn dòng bị chặn hoặc kết quả kiểm cũ hơn lần đổi danh sách cuối.
 */
export function CouncilCheckStep({ preview, checking, error, submittedIds, onRecheck, onBack, onNext }: Props) {
  const docSet = useCouncilSelectionStore((s) => s.docSet)
  const selectedCount = useCouncilSelectionStore((s) => s.profileId.length)
  const [opened, setOpened] = useState<ReadonlySet<number>>(new Set())

  const notFound = useMemo(
    () =>
      (preview?.khong_tim_thay ?? [])
        .map((position) => submittedIds[position - 1])
        .filter((id): id is number => typeof id === "number"),
    [preview, submittedIds],
  )

  const t = preview?.tom_tat
  const lockReason = checking
    ? "Đang kiểm lại — chờ kết quả."
    : error
      ? "Chưa có kết quả kiểm — bấm “Kiểm tra lại”."
      : !t
        ? "Chưa có kết quả kiểm."
        : notFound.length > 0
          ? `${notFound.length} hồ sơ trong danh sách không còn tìm thấy — bỏ khỏi bộ.`
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
        <CouncilPreviewSummary selectedCount={selectedCount} preview={preview} checking={checking} error={error} />
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          {preview ? <span data-testid="kiem-luc">Kiểm lúc {formatTime(preview.kiem_luc)}</span> : null}
          <Button type="button" variant="outline" size="sm" onClick={onRecheck} disabled={checking} data-testid="kiem-lai">
            {checking ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-1 h-4 w-4" />}
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

      {notFound.length > 0 ? (
        <div className="rounded border border-destructive/50 p-3 text-sm" role="alert" data-testid="khong-tim-thay">
          <p>
            {notFound.length} hồ sơ trong danh sách không còn tìm thấy (đã đổi năm học / ngoài phạm vi của bạn / không còn).
          </p>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="mt-2"
            data-testid="bo-khong-tim-thay"
            onClick={() => {
              for (const id of notFound) docSet(id)
            }}
          >
            Bỏ các hồ sơ này khỏi danh sách
          </Button>
        </div>
      ) : null}

      {preview ? (
        <div className={cn("overflow-x-auto rounded border", checking && "opacity-60")} aria-busy={checking} data-testid="khung-bang-kiem-tra">
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
              {preview.dong.map((d) => (
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
                    <div className="text-xs text-muted-foreground">{statusLabel(d.trang_thai)}</div>
                  </TableCell>
                  <TableCell>
                    <div>{majorWithLevel(d.nganh_nhan, d.trinh_do)}</div>
                    <div className="text-xs text-muted-foreground">{d.duong_xet_nhan ?? "—"}</div>
                  </TableCell>
                  <TableCell>{d.diem_in ?? "—"}</TableCell>
                  <TableCell data-testid={`muc-${d.profile_id}`}>
                    <div className="font-medium">{checkItemLabel(d.muc)}</div>
                    {d.ly_do.map((l) => (
                      <div key={l.ma} className="text-xs" data-testid={`ly-do-${d.profile_id}`}>
                        {checkReasonText(l)}
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
                      onClick={() => setOpened((s) => new Set(s).add(d.profile_id))}
                    >
                      Mở hồ sơ để sửa ↗
                    </a>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      data-testid={`bo-khoi-bo-${d.profile_id}`}
                      onClick={() => docSet(d.profile_id)}
                    >
                      Bỏ khỏi bộ
                    </Button>
                    {opened.has(d.profile_id) ? (
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

      {!preview && !checking && error ? <CouncilErrorAlert error={error} testId="kiem-tra-loi" /> : null}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button type="button" variant="outline" onClick={onBack} data-testid="quay-lai-chon">
          ← Quay lại chọn thêm
        </Button>
        <div className="flex items-center gap-3">
          {lockReason ? (
            <span className="text-sm text-muted-foreground" data-testid="ly-do-khoa-chot">
              {lockReason}
            </span>
          ) : null}
          <Button type="button" onClick={onNext} disabled={lockReason !== null} data-testid="chot-tiep">
            Chốt danh sách & tiếp →
          </Button>
        </div>
      </div>
    </div>
  )
}
