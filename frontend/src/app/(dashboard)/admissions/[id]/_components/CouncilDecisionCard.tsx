// src/app/(dashboard)/admissions/[id]/_components/CouncilDecisionCard.tsx
"use client"

import Link from "next/link"

import { Badge } from "@/components/ui/badge"
import {
  ngay,
  nhanLoaiQuyetDinh,
  nhanTrangThaiQuyetDinh,
} from "@/app/(dashboard)/admin/council-documents/_components/hien-thi"
import { councilProfileDecisionSchema } from "@/lib/zod/council-documents"

/** Nhãn tình trạng do MÁY CHỦ tính (đặc tả 3.9); giá trị lạ ⇒ in nguyên (không suy). */
const NHAN_TINH_TRANG: Record<string, string> = {
  co_qd_hieu_luc: "Còn hiệu lực",
  cho_admin_quyet: "Đang chờ Admin quyết",
  da_cho_xet_lai: "Đã cho xét lại",
  chua_co_qd: "Chưa có Quyết định",
}

/**
 * Thẻ "Quyết định trúng tuyển" trên trang hồ sơ (đặc tả 5.8, bản mẫu — ba dạng: còn hiệu lực + đã đối chiếu sổ · chỉ dấu
 * AppSheet · đã huỷ ghi nhận). Mọi chữ lấy từ DTO máy chủ; không suy tình trạng từ chỗ khác.
 *
 * ⏳ CHỜ MÁY CHỦ: DTO chi tiết hồ sơ chưa có `quyet_dinh_trung_tuyen`. Vắng hoặc sai dạng ⇒ KHÔNG hiện thẻ (không đoán).
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
                <Link href={`/admin/council-documents/${vb.set_id}`} className="underline-offset-2 hover:underline" data-testid="qd-bo-link">
                  bộ #{vb.set_id}
                </Link>
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
