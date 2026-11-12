// src/app/(dashboard)/admissions/[id]/_components/CouncilDecisionCard.tsx
"use client"

import Link from "next/link"

import { Badge } from "@/components/ui/badge"
import {
  ngay,
  nhanLoaiQuyetDinh,
  nhanTrangThaiQuyetDinh,
} from "@/app/(dashboard)/admin/council-documents/_components/hien-thi"
import { useCouncilDocumentPermissions } from "@/hooks/admin/useCouncilDocuments"
import { councilProfileDecisionSchema } from "@/lib/zod/council-documents"

/** Nhãn tình trạng do MÁY CHỦ tính (đặc tả 3.9); giá trị lạ ⇒ in nguyên (không suy). */
const NHAN_TINH_TRANG: Record<string, string> = {
  co_qd_hieu_luc: "Còn hiệu lực",
  cho_admin_quyet: "Đang chờ Admin quyết",
  da_cho_xet_lai: "Đã cho xét lại",
  chua_co_qd: "Chưa có Quyết định",
}

/**
 * Mã bộ của văn bản. Cán bộ xem được hồ sơ chưa chắc được xem bộ văn bản Hội đồng (cổng RIÊNG của module): chỉ làm LIÊN KẾT khi
 * máy chủ báo cờ `xem_chi_tiet_bo` (`GET /quyen`; 403 = mọi cờ tắt — hợp đồng hiện có). Đang tải / lỗi / 403 / thiếu cờ ⇒ chỉ
 * hiện mã bộ dạng chữ (bấm ra chỉ gặp từ chối quyền — F279). Đọc cờ CHỈ khi thật sự có bộ để trỏ tới (component con).
 */
function MaBo({ setId }: { setId: number }) {
  const vm = useCouncilDocumentPermissions()
  const nhan = `bộ #${setId}`
  if (vm.state === "ready" && vm.permissions.xem_chi_tiet_bo) {
    return (
      <Link href={`/admin/council-documents/${setId}`} className="underline-offset-2 hover:underline" data-testid="qd-bo-link">
        {nhan}
      </Link>
    )
  }
  return <span data-testid="qd-bo-ma">{nhan}</span>
}

/**
 * Thẻ "Quyết định trúng tuyển" trên trang hồ sơ (đặc tả 5.8, bản mẫu — ba dạng: còn hiệu lực + đã đối chiếu sổ · chỉ dấu
 * AppSheet · đã huỷ ghi nhận). Mọi chữ lấy từ DTO máy chủ; không suy tình trạng từ chỗ khác.
 *
 * Máy chủ `083a428d`: CHỈ `GET /api/admissions/{id}` điền `quyet_dinh_trung_tuyen`; route khác (vd PUT cập nhật hồ sơ) trả `null`.
 * `null` / vắng / sai dạng ⇒ KHÔNG hiện thẻ (không đoán). `ly_do_huy_ghi_nhan` CHỈ admin có giá trị (người khác: khoá vẫn có, giá trị null).
 * Hồ sơ chỉ mang dấu AppSheet hiện TÁCH RIÊNG ("chưa đối chiếu"), không trông giống hồ sơ đã đối chiếu.
 */
export function CouncilDecisionCard({ value }: { value: unknown }) {
  const r = councilProfileDecisionSchema.safeParse(value)
  if (!r.success) return null
  const d = r.data
  const vb = d.van_ban
  const daHuy = vb?.trang_thai === "huy_ghi_nhan"

  return (
    <section className="mb-4 rounded-lg border bg-card p-4 text-sm" data-testid="the-quyet-dinh-trung-tuyen" aria-label="Quyết định trúng tuyển">
      <h3 className="mb-2 font-semibold">Quyết định trúng tuyển</h3>

      {vb ? (
        <div className="space-y-1" data-testid="qd-co-van-ban">
          <div>
            {nhanLoaiQuyetDinh(vb.loai)} số {vb.so_quyet_dinh} ngày {ngay(vb.ngay_ky)}
            {vb.set_id !== null ? (
              <>
                {" · "}
                <MaBo setId={vb.set_id} />
              </>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={daHuy ? "error" : "success"} data-testid="qd-nhan-trang-thai">
              {nhanTrangThaiQuyetDinh(vb.trang_thai)}
            </Badge>
            {d.tinh_trang === "co_qd_hieu_luc" ? (
              <span className="text-xs text-muted-foreground" data-testid="qd-doi-chieu-so">
                Đã đối chiếu sổ Quyết định
              </span>
            ) : (
              <span className="text-xs text-muted-foreground" data-testid="qd-tinh-trang">
                {NHAN_TINH_TRANG[d.tinh_trang] ?? d.tinh_trang}
              </span>
            )}
          </div>
          {d.ly_do_huy_ghi_nhan ? (
            <div className="text-xs text-muted-foreground" data-testid="qd-ly-do-huy">
              Lý do: {d.ly_do_huy_ghi_nhan}
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-muted-foreground" data-testid="qd-chua-co">
          Chưa có trong sổ Quyết định của phần mềm.
        </p>
      )}

      {d.dau_appsheet ? (
        <div className="mt-3 space-y-1 rounded border border-warning-300 bg-warning-50 p-3" data-testid="qd-dau-appsheet">
          <div>
            Dữ liệu nhập từ AppSheet ghi: Quyết định{d.dau_appsheet_so_qd ? ` số ${d.dau_appsheet_so_qd}` : ""}
          </div>
          <Badge variant="warning">Chỉ có dấu AppSheet — chưa đối chiếu</Badge>
          {!vb ? (
            <div className="text-xs text-muted-foreground">Vì có dấu này, hồ sơ bị chặn khi đưa vào bộ mới (xem bước 2).</div>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
