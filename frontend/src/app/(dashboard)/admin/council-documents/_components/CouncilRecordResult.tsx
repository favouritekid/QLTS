"use client"

import Link from "next/link"
import { useState } from "react"
import { AlertTriangle, CheckCircle2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import type {
  CouncilDecision,
  CouncilDecisionWrite,
  CouncilDocumentPermissions,
  CouncilQuotaWarning,
} from "@/lib/zod/council-documents"

import { CouncilCancelDialog } from "./CouncilCancelDialog"
import { ngay, nhanLoaiQuyetDinh, nhanTrangThaiQuyetDinh, thoiDiem } from "./hien-thi"

/**
 * Số chính của một ô chỉ tiêu ngành: MỨC LỚN NHẤT trong hai cách đếm, ghi đúng chữ ấy — KHÔNG gọi là "tổng"
 * (đặc tả 3.8, Codex G.4 K-4). Chỉ chọn số lớn hơn trong hai số máy chủ trả; thiếu cả hai ⇒ null.
 */
export function mucLonNhatHaiCachDem(w: Pick<CouncilQuotaWarning, "da_dung_cong_bo" | "da_dung_phe_duyet_cu">): number | null {
  const co = [w.da_dung_cong_bo, w.da_dung_phe_duyet_cu].filter((x): x is number => typeof x === "number")
  return co.length === 0 ? null : Math.max(...co)
}

/** Tên hiển thị của ô vượt: `nhan` do máy chủ trả; thiếu ⇒ mã + id (đặc tả 3.8). */
function tenO(w: CouncilQuotaWarning): string {
  if (w.nhan) return w.nhan
  return w.loai === "nganh" ? `ngành (học vụ #${w.academic_info_id ?? "?"})` : `đường xét (#${w.admission_path_id ?? "?"})`
}

export function CouncilQuotaWarnings({ canhBao }: { canhBao: readonly CouncilQuotaWarning[] }) {
  if (canhBao.length === 0) return null
  return (
    <div className="space-y-2 rounded border border-warning-500/60 bg-warning-50 p-3 text-sm" role="status" data-testid="canh-bao-chi-tieu">
      <div className="flex items-center gap-2 font-medium">
        <AlertTriangle className="h-4 w-4" aria-hidden="true" /> Cảnh báo vượt chỉ tiêu — đã ghi nhận, không chặn. Báo Ban thư ký xem lại.
      </div>
      <ul className="space-y-1">
        {canhBao.map((w, i) => {
          const chinh = w.loai === "nganh" ? mucLonNhatHaiCachDem(w) : (w.da_dung ?? null)
          return (
            <li key={`${w.loai}-${w.academic_info_id ?? w.admission_path_id ?? i}`} data-testid={`canh-bao-${i}`}>
              <span className="font-medium">{tenO(w)}</span>: chỉ tiêu {w.chi_tieu}; đã dùng{" "}
              {w.loai === "nganh" ? "(mức lớn nhất trong hai cách đếm) " : ""}
              <strong data-testid={`canh-bao-so-chinh-${i}`}>{chinh ?? "—"}</strong>
              {w.loai === "nganh" ? (
                <span className="text-xs text-muted-foreground" data-testid={`canh-bao-chi-tiet-${i}`}>
                  {" "}
                  (công bố: {w.da_dung_cong_bo ?? "—"} · Phê duyệt cũ: {w.da_dung_phe_duyet_cu ?? "—"})
                </span>
              ) : null}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

interface Props {
  /** văn bản đã ghi — đọc từ DTO máy chủ (ghi nhận / phân xử / `GET /decisions`), KHÔNG từ các ô nhập */
  quyetDinh: CouncilDecisionWrite | CouncilDecision
  setId: number
  quyen: CouncilDocumentPermissions
  /** sau khi đã huỷ ghi nhận: cha mở lại biểu mẫu */
  onDaHuy: () => void
}

function laDtoGhi(q: CouncilDecisionWrite | CouncilDecision): q is CouncilDecisionWrite {
  return "canh_bao_vuot_chi_tieu" in q
}

/**
 * Khung kết quả bước 6 (đặc tả 5.6, bản mẫu): loại, số, ngày ký, số hồ sơ, bộ, giờ ghi, gốc nếu bổ sung — CHỈ từ DTO
 * máy chủ. Biểu mẫu khoá. Cảnh báo vượt chỉ tiêu hiện riêng ("đã ghi nhận, không chặn").
 */
export function CouncilRecordResult({ quyetDinh, setId, quyen, onDaHuy }: Props) {
  const [moHuy, setMoHuy] = useState(false)
  const ghi = laDtoGhi(quyetDinh) ? quyetDinh : null
  const daHuy = quyetDinh.trang_thai === "huy_ghi_nhan"

  return (
    <div className="space-y-3" data-testid="ket-qua-ghi-nhan">
      <div className="space-y-2 rounded border border-success-500/50 p-4">
        <div className="flex items-center gap-2 text-base font-semibold">
          <CheckCircle2 className="h-5 w-5 text-success-600" aria-hidden="true" />
          {daHuy ? "Văn bản đã huỷ ghi nhận" : "Đã ghi nhận Quyết định"}
        </div>
        <p className="text-sm" data-testid="ket-qua-dong">
          Máy chủ trả: {nhanLoaiQuyetDinh(quyetDinh.loai)} số {quyetDinh.so_quyet_dinh} · ngày ký {ngay(quyetDinh.ngay_ky)} ·{" "}
          {quyetDinh.so_ho_so} hồ sơ · bộ #{quyetDinh.set_id ?? setId} · ghi lúc {thoiDiem(quyetDinh.ghi_nhan_luc)} ·{" "}
          {nhanTrangThaiQuyetDinh(quyetDinh.trang_thai)}
        </p>
        {ghi?.goc ? (
          <p className="text-sm" data-testid="ket-qua-goc">
            Bổ sung cho Quyết định số {ghi.goc.so_quyet_dinh} ngày {ngay(ghi.goc.ngay_ky)}
          </p>
        ) : null}
        {ghi?.lap_lai ? (
          <p className="text-sm text-muted-foreground" data-testid="ket-qua-lap-lai">
            Lượt này đã ghi trước đó — hiển thị văn bản cũ, không ghi lần hai.
          </p>
        ) : null}
        <p className="text-xs text-muted-foreground">
          Biểu mẫu đã khoá. Thông tin trên lấy từ máy chủ, không lấy từ các ô nhập. Nếu nhập sai: Admin dùng “Huỷ ghi nhận” (ghi lý
          do) rồi ghi nhận lại.
        </p>
      </div>

      {ghi ? <CouncilQuotaWarnings canhBao={ghi.canh_bao_vuot_chi_tieu} /> : null}

      <div className="flex flex-wrap gap-2">
        <Button asChild variant="outline" size="sm">
          <Link href="/admin/council-documents" data-testid="xem-danh-sach-bo">
            Xem danh sách bộ
          </Link>
        </Button>
        {quyen.huy_ghi_nhan_qd && !daHuy ? (
          <Button type="button" variant="outline" size="sm" onClick={() => setMoHuy(true)} data-testid="huy-ghi-nhan-mo">
            Huỷ ghi nhận…
          </Button>
        ) : null}
        {quyen.tao_bo && quyen.kiem_truoc ? (
          <Button asChild variant="outline" size="sm">
            <Link href="/admin/council-documents/moi" data-testid="dung-bo-moi">
              + Dựng bộ mới
            </Link>
          </Button>
        ) : null}
      </div>

      <CouncilCancelDialog
        open={moHuy}
        onOpenChange={setMoHuy}
        decisionId={quyetDinh.id}
        loai={quyetDinh.loai}
        soQuyetDinh={quyetDinh.so_quyet_dinh}
        soHoSo={quyetDinh.so_ho_so}
        onXong={onDaHuy}
      />
    </div>
  )
}
