"use client"

import { useMemo, useState } from "react"
import { Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useCreateCouncilSetByIds } from "@/hooks/admin/useCouncilDocuments"
import { councilErrorCode } from "@/lib/api/council-documents"
import { thamSoGui } from "@/lib/council-params"
import { useCouncilSelectionStore } from "@/lib/stores/council-selection.store"
import type { CouncilSetDetail, CouncilSetPreview } from "@/lib/zod/council-documents"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { nhanTrangThai, ngay } from "./hien-thi"

interface Props {
  namHoc: number
  /** kết quả kiểm trước MỚI của đúng danh sách đã chốt (cha chỉ mở bước này khi đã có) */
  xemTruoc: CouncilSetPreview
  onQuayLai: () => void
  onDungXong: (bo: CouncilSetDetail) => void
  /** 409 `du_lieu_doi_tu_luc_kiem`: dữ liệu đã đổi từ lúc kiểm — cha đưa về bước 2 và kiểm lại */
  onDuLieuDoi: () => void
}

/** Câu tóm tắt tham số đã nhập (chỉ ô có giá trị). */
function chuoiThamSo(t: ReturnType<typeof thamSoGui>): string {
  if (!t) return "không có số / ngày nào (chỗ ấy để trống trên văn bản)"
  const p: string[] = []
  if (t.so_quyet_dinh) p.push(`Số QĐ ${t.so_quyet_dinh}`)
  if (t.ngay_quyet_dinh) p.push(`ngày QĐ ${ngay(t.ngay_quyet_dinh)}`)
  if (t.dot_so) p.push(`đợt ${t.dot_so}`)
  if (t.dot_thang) p.push(`tháng ${t.dot_thang}`)
  if (t.so_bien_ban) p.push(`Số BB ${t.so_bien_ban}`)
  if (t.ngay_bien_ban) p.push(`ngày BB ${ngay(t.ngay_bien_ban)}`)
  return p.join(" · ")
}

/**
 * Bước 4 (phần dựng) — gọi `POST /sets` dạng id (đặc tả 5.4, 3.3). Gửi ĐÚNG danh sách và thứ tự máy chủ đã trả ở lần
 * kiểm trước, kèm dấu `phien_ban_kiem`; máy chủ kiểm lại. Hồ sơ ở mức "cần xác nhận": người dùng gõ lại đúng số hồ sơ
 * theo từng trạng thái (số do máy chủ báo; giao diện chỉ yêu cầu gõ khớp để mở nút — máy chủ vẫn kiểm).
 */
export function CouncilBuildStep({ namHoc, xemTruoc, onQuayLai, onDungXong, onDuLieuDoi }: Props) {
  const thamSoNhap = useCouncilSelectionStore((s) => s.thamSo)
  const lamSach = useCouncilSelectionStore((s) => s.lamSach)
  const tao = useCreateCouncilSetByIds()
  const t = xemTruoc.tom_tat
  const ts = thamSoGui(thamSoNhap)

  const canXacNhan = useMemo(() => Object.entries(t.can_xac_nhan_theo_trang_thai), [t.can_xac_nhan_theo_trang_thai])
  const [go, setGo] = useState<Record<string, string>>({})
  const khop = canXacNhan.every(([tt, n]) => (go[tt] ?? "").trim() === String(n))
  // ⏳ CHỜ MÁY CHỦ: máy chủ nói tài khoản này KHÔNG xác nhận được (cổng quyền xác nhận) ⇒ khoá. Vắng ⇒ không khoá
  // (máy chủ vẫn kiểm khi dựng); giao diện không tự xét vai.
  const khongXacNhanDuoc = canXacNhan.length > 0 && t.nguoi_goi_duoc_xac_nhan === false
  const dongTheoTrangThai = useMemo(() => {
    const m: Record<string, number[]> = {}
    for (const d of xemTruoc.dong) if (d.muc === "can_xac_nhan") (m[d.trang_thai] ??= []).push(d.stt)
    return m
  }, [xemTruoc.dong])

  const maLoi = tao.error ? councilErrorCode(tao.error).maLoi : undefined

  const dung = () => {
    tao.mutate(
      {
        // ĐÚNG thứ tự máy chủ trả — khác thứ tự ⇒ 409 `du_lieu_doi_tu_luc_kiem`, không tự sắp lại
        profile_ids: xemTruoc.dong.map((d) => d.profile_id),
        phien_ban_kiem: xemTruoc.phien_ban_kiem,
        academic_year: namHoc,
        ...(ts ? { tham_so_quyet_dinh: ts } : {}),
        ...(canXacNhan.length > 0 ? { xac_nhan_trang_thai: t.can_xac_nhan_theo_trang_thai } : {}),
      },
      {
        onSuccess: (bo) => {
          lamSach()
          onDungXong(bo)
        },
        onError: (loi) => {
          if (councilErrorCode(loi).maLoi === "du_lieu_doi_tu_luc_kiem") onDuLieuDoi()
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
          {t.tong} hồ sơ · {t.so_nhom} nhóm ngành – trình độ · theo danh sách đã chốt · {chuoiThamSo(ts)}
        </div>
        <div className="mt-1 text-muted-foreground" data-testid="du-kien-tep">
          Sẽ tạo {t.du_kien_so_tep} tệp: Biên bản và Quyết định (2 tệp chung) + Danh sách xét tuyển Word và Excel cho mỗi nhóm
          ngành – trình độ (2 × {t.so_nhom}).
        </div>
      </div>

      {canXacNhan.length > 0 ? (
        <div className="space-y-2 rounded border border-warning-500/50 p-3" data-testid="khoi-xac-nhan">
          <div className="text-sm font-medium">
            Có hồ sơ chưa ở trạng thái “Đã duyệt” — Admin xác nhận để đưa vào bộ
          </div>
          {khongXacNhanDuoc ? (
            <p className="text-sm font-medium text-destructive" data-testid="khong-xac-nhan-duoc">
              Cần Admin xác nhận — tài khoản của bạn không xác nhận được.
            </p>
          ) : null}
          {canXacNhan.map(([tt, n]) => (
            <div key={tt} className="space-y-1">
              <Label htmlFor={`xn-${tt}`}>
                {`“${nhanTrangThai(tt)}”: ${n} hồ sơ${
                  dongTheoTrangThai[tt] ? ` (dòng ${dongTheoTrangThai[tt].join(", ")})` : ""
                } — gõ số hồ sơ để xác nhận`}
              </Label>
              <Input
                id={`xn-${tt}`}
                data-testid={`xac-nhan-${tt}`}
                className="max-w-[8rem]"
                inputMode="numeric"
                autoComplete="off"
                value={go[tt] ?? ""}
                disabled={tao.isPending || khongXacNhanDuoc}
                onChange={(e) => setGo((g) => ({ ...g, [tt]: e.target.value }))}
              />
            </div>
          ))}
        </div>
      ) : null}

      {maLoi === "du_lieu_doi_tu_luc_kiem" ? (
        <div className="rounded border border-destructive/50 p-3 text-sm" role="alert" data-testid="du-lieu-doi">
          Dữ liệu đã đổi từ lúc kiểm — bấm “Kiểm tra lại”.
          <Button type="button" variant="outline" size="sm" className="ml-3" onClick={onDuLieuDoi} data-testid="ve-kiem-tra">
            Về bước kiểm tra
          </Button>
        </div>
      ) : (
        <CouncilErrorAlert error={tao.error} testId="dung-bo-loi" />
      )}

      <div className="flex items-center justify-between">
        <Button type="button" variant="outline" onClick={onQuayLai} disabled={tao.isPending} data-testid="dung-quay-lai">
          ← Quay lại
        </Button>
        <Button type="button" onClick={dung} disabled={tao.isPending || !khop || khongXacNhanDuoc} data-testid="dung-bo">
          {tao.isPending ? (
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
