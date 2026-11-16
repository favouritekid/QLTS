"use client"

import { useEffect, useMemo, useState } from "react"
import { Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useCreateCouncilSetByIds } from "@/hooks/admin/useCouncilDocuments"
import { councilErrorCode } from "@/lib/api/council-documents"
import { submitParams } from "@/lib/council-params"
import { useCouncilSelectionStore } from "@/lib/stores/council-selection.store"
import type { CouncilSetDetail, CouncilSetPreview } from "@/lib/zod/council-documents"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { statusLabel, formatDate } from "./display"

interface Props {
  academicYear: number
  /** kết quả kiểm trước MỚI của đúng danh sách đã chốt (cha chỉ mở bước này khi đã có) */
  preview: CouncilSetPreview
  onBack: () => void
  onBuildDone: (docSet: CouncilSetDetail) => void
  /** 409 `du_lieu_doi_tu_luc_kiem`: dữ liệu đã đổi từ lúc kiểm — cha đưa về bước 2 và kiểm lại */
  onDataChange: () => void
  /** Review max PR #724 (R12): báo cha khi lệnh dựng đang chạy — cha khoá thanh bước (chuyển bước lúc đang dựng gỡ
   * bước này ⇒ react-query bỏ callback của `mutate` ⇒ bộ đã tạo mà không chuyển trang; bấm "Dựng" lại ⇒ bộ TRÙNG). */
  onBuildingChange?: (building: boolean) => void
}

/** Câu tóm tắt tham số đã nhập (chỉ ô có giá trị). */
function paramsQueryString(t: ReturnType<typeof submitParams>): string {
  if (!t) return "không có số / ngày nào (chỗ ấy để trống trên văn bản)"
  const p: string[] = []
  if (t.so_quyet_dinh) p.push(`Số QĐ ${t.so_quyet_dinh}`)
  if (t.ngay_quyet_dinh) p.push(`ngày QĐ ${formatDate(t.ngay_quyet_dinh)}`)
  if (t.dot_so) p.push(`đợt ${t.dot_so}`)
  if (t.dot_thang) p.push(`tháng ${t.dot_thang}`)
  if (t.so_bien_ban) p.push(`Số BB ${t.so_bien_ban}`)
  if (t.ngay_bien_ban) p.push(`ngày BB ${formatDate(t.ngay_bien_ban)}`)
  return p.join(" · ")
}

/**
 * Bước 4 (phần dựng) — gọi `POST /sets` dạng id (đặc tả 5.4, 3.3). Gửi ĐÚNG danh sách và thứ tự máy chủ đã trả ở lần
 * kiểm trước, kèm dấu `phien_ban_kiem`; máy chủ kiểm lại. Hồ sơ ở mức "cần xác nhận": người dùng gõ lại đúng số hồ sơ
 * theo từng trạng thái (số do máy chủ báo; giao diện chỉ yêu cầu gõ khớp để mở nút — máy chủ vẫn kiểm).
 */
export function CouncilBuildStep({ academicYear, preview, onBack, onBuildDone, onDataChange, onBuildingChange }: Props) {
  const inputParams = useCouncilSelectionStore((s) => s.params)
  const reset = useCouncilSelectionStore((s) => s.reset)
  const create = useCreateCouncilSetByIds()
  const t = preview.tom_tat
  const decisionParams = submitParams(inputParams)

  const needsConfirmation = useMemo(() => Object.entries(t.can_xac_nhan_theo_trang_thai), [t.can_xac_nhan_theo_trang_thai])
  const [typed, setTyped] = useState<Record<string, string>>({})
  const matches = needsConfirmation.every(([status, n]) => (typed[status] ?? "").trim() === String(n))
  // Máy chủ nói tài khoản này KHÔNG xác nhận được (cổng quyền xác nhận; `nguoi_goi_duoc_xac_nhan` luôn có) ⇒ khoá.
  // Giao diện không tự xét vai.
  const cannotConfirm = needsConfirmation.length > 0 && !t.nguoi_goi_duoc_xac_nhan
  const rowsByStatus = useMemo(() => {
    const m: Record<string, number[]> = {}
    for (const d of preview.dong) if (d.muc === "can_xac_nhan") (m[d.trang_thai] ??= []).push(d.stt)
    return m
  }, [preview.dong])

  const errorCode = create.error ? councilErrorCode(create.error).errorCode : undefined

  // R12: trạng thái "đang dựng" lên cha (khoá thanh bước); gỡ bước này ⇒ báo hết dựng (không khoá kẹt).
  const isBuilding = create.isPending
  useEffect(() => {
    onBuildingChange?.(isBuilding)
  }, [isBuilding, onBuildingChange])
  useEffect(() => () => onBuildingChange?.(false), [onBuildingChange])

  const build = () => {
    create.mutate(
      {
        // ĐÚNG thứ tự máy chủ trả — khác thứ tự ⇒ 409 `du_lieu_doi_tu_luc_kiem`, không tự sắp lại
        profile_ids: preview.dong.map((d) => d.profile_id),
        phien_ban_kiem: preview.phien_ban_kiem,
        academic_year: academicYear,
        ...(decisionParams ? { tham_so_quyet_dinh: decisionParams } : {}),
        ...(needsConfirmation.length > 0 ? { xac_nhan_trang_thai: t.can_xac_nhan_theo_trang_thai } : {}),
      },
      {
        onSuccess: (docSet) => {
          reset()
          onBuildDone(docSet)
        },
        onError: (error) => {
          if (councilErrorCode(error).errorCode === "du_lieu_doi_tu_luc_kiem") onDataChange()
        },
      },
    )
  }

  return (
    <div className="space-y-4" data-testid="buoc-dung">
      <p className="text-sm text-muted-foreground">Bước 4 — dựng bộ văn bản rồi tải về in, trình ký.</p>

      <div className="rounded border p-3 text-sm" data-testid="se-dung">
        <div className="font-medium">Sẽ dựng</div>
        <div>
          {t.tong} hồ sơ · {t.so_nhom} nhóm ngành – trình độ · theo danh sách đã chốt · {paramsQueryString(decisionParams)}
        </div>
        <div className="mt-1 text-muted-foreground" data-testid="du-kien-tep">
          Sẽ tạo {t.du_kien_so_tep} tệp: Biên bản và Quyết định (2 tệp chung) + Danh sách xét tuyển Word và Excel cho mỗi nhóm
          ngành – trình độ (2 × {t.so_nhom}).
        </div>
      </div>

      {needsConfirmation.length > 0 ? (
        <div className="space-y-2 rounded border border-warning-500/50 p-3" data-testid="khoi-xac-nhan">
          <div className="text-sm font-medium">
            Có hồ sơ chưa ở trạng thái “Đã duyệt” — Admin xác nhận để đưa vào bộ
          </div>
          {cannotConfirm ? (
            <p className="text-sm font-medium text-destructive" data-testid="khong-xac-nhan-duoc">
              Cần Admin xác nhận — tài khoản của bạn không xác nhận được.
            </p>
          ) : null}
          {needsConfirmation.map(([status, n]) => (
            <div key={status} className="space-y-1">
              <Label htmlFor={`xn-${status}`}>
                {`“${statusLabel(status)}”: ${n} hồ sơ${
                  rowsByStatus[status] ? ` (dòng ${rowsByStatus[status].join(", ")})` : ""
                } — gõ số hồ sơ để xác nhận`}
              </Label>
              <Input
                id={`xn-${status}`}
                data-testid={`xac-nhan-${status}`}
                className="max-w-[8rem]"
                inputMode="numeric"
                autoComplete="off"
                value={typed[status] ?? ""}
                disabled={create.isPending || cannotConfirm}
                onChange={(e) => setTyped((g) => ({ ...g, [status]: e.target.value }))}
              />
            </div>
          ))}
        </div>
      ) : null}

      {errorCode === "du_lieu_doi_tu_luc_kiem" ? (
        <div className="rounded border border-destructive/50 p-3 text-sm" role="alert" data-testid="du-lieu-doi">
          Dữ liệu đã đổi từ lúc kiểm — bấm “Kiểm tra lại”.
          <Button type="button" variant="outline" size="sm" className="ml-3" onClick={onDataChange} data-testid="ve-kiem-tra">
            Về bước kiểm tra
          </Button>
        </div>
      ) : (
        <CouncilErrorAlert error={create.error} testId="dung-bo-loi" />
      )}

      <div className="flex items-center justify-between">
        <Button type="button" variant="outline" onClick={onBack} disabled={create.isPending} data-testid="dung-quay-lai">
          ← Quay lại
        </Button>
        <Button type="button" onClick={build} disabled={create.isPending || !matches || cannotConfirm} data-testid="dung-bo">
          {create.isPending ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Đang dựng bộ văn bản…
            </>
          ) : (
            "Dựng bộ văn bản"
          )}
        </Button>
      </div>
    </div>
  )
}
