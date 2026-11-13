"use client"

import { Loader2 } from "lucide-react"

import type { CouncilSetPreview } from "@/lib/zod/council-documents"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { nganhTrinhDo, thoiDiem } from "./hien-thi"

interface Props {
  /** số hồ sơ đang chọn (để nói "chưa chọn") */
  soDangChon: number
  /** kết quả kiểm trước của ĐÚNG danh sách đang chọn; `undefined` khi chưa có */
  xemTruoc: CouncilSetPreview | undefined
  /** đang chờ (đợi 600 ms sau lần đổi cuối, hoặc đang gọi máy chủ) — KHÔNG hiện số cũ như còn đúng */
  dangKiem: boolean
  loi?: unknown
}

/**
 * Bảng tổng hợp bước 1–2 (đặc tả 5.1). Mọi số do MÁY CHỦ trả; giao diện không tự cộng. Trong lúc chờ kiểm lại chỉ
 * hiện "đang kiểm…" — không giữ số của lần kiểm trước.
 */
export function CouncilPreviewSummary({ soDangChon, xemTruoc, dangKiem, loi }: Props) {
  if (soDangChon === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="tom-tat-trong">
        Chưa chọn hồ sơ nào.
      </p>
    )
  }
  if (dangKiem) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="tom-tat-dang-kiem">
        <Loader2 className="h-4 w-4 animate-spin" /> Đang kiểm {soDangChon} hồ sơ…
      </div>
    )
  }
  if (loi) return <CouncilErrorAlert error={loi} testId="tom-tat-loi" />
  if (!xemTruoc) return null
  const t = xemTruoc.tom_tat
  return (
    <section className="space-y-2" data-testid="tom-tat">
      <h3 className="text-sm font-semibold">Bảng tổng hợp</h3>
      <p className="text-sm" data-testid="tom-tat-tong">
        {t.tong} hồ sơ đang chọn
      </p>
      <dl className="grid grid-cols-3 gap-2 text-center text-sm">
        <div className="rounded border p-2">
          <dd className="text-lg font-semibold" data-testid="tom-tat-duoc-dung">{t.duoc_dung}</dd>
          <dt className="text-muted-foreground">Được dựng</dt>
        </div>
        <div className="rounded border p-2">
          <dd className="text-lg font-semibold" data-testid="tom-tat-can-xac-nhan">{t.can_xac_nhan}</dd>
          <dt className="text-muted-foreground">Cần xác nhận</dt>
        </div>
        <div className="rounded border p-2">
          <dd className="text-lg font-semibold" data-testid="tom-tat-bi-chan">{t.bi_chan}</dd>
          <dt className="text-muted-foreground">Bị chặn</dt>
        </div>
      </dl>
      {t.theo_nganh.length > 0 ? (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Theo ngành</h4>
          <ul className="text-sm" data-testid="tom-tat-theo-nganh">
            {t.theo_nganh.map((n) => (
              <li key={`${n.nganh_nhan}|${n.trinh_do}`} className="flex justify-between gap-2">
                <span>{nganhTrinhDo(n.nganh_nhan, n.trinh_do)}</span>
                <span className="font-medium">{n.so}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="text-xs text-muted-foreground" data-testid="tom-tat-gio">
        Kiểm trước lúc {thoiDiem(xemTruoc.kiem_luc)} · máy chủ kiểm lại khi dựng
      </p>
    </section>
  )
}
