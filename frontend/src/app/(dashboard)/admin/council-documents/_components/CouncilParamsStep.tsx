"use client"

import type { ChangeEvent } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useCouncilSelectionStore } from "@/lib/stores/council-selection.store"
import type { ThamSoNhap } from "@/lib/council-params"
import type { CouncilSetPreview } from "@/lib/zod/council-documents"

interface Props {
  namHoc: number
  xemTruoc: CouncilSetPreview | undefined
  onQuayLai: () => void
  onTiep: () => void
}

/**
 * Bước 3 — tham số văn bản (đặc tả 5.3). Sáu ô như bản mẫu; ngày nhập bằng lịch; để trống được. KHÔNG đặt luật mới ở
 * giao diện: hai luật của máy chủ (đợt số + tháng cùng điền / cùng trống; ngày Biên bản không sau ngày Quyết định) chỉ
 * hiện khi MÁY CHỦ trả lỗi lúc dựng.
 */
export function CouncilParamsStep({ namHoc, xemTruoc, onQuayLai, onTiep }: Props) {
  const thamSo = useCouncilSelectionStore((s) => s.thamSo)
  const datThamSo = useCouncilSelectionStore((s) => s.datThamSo)
  const t = xemTruoc?.tom_tat

  const doi = (k: keyof ThamSoNhap) => (e: ChangeEvent<HTMLInputElement>) => datThamSo({ [k]: e.target.value })

  return (
    <div className="space-y-4" data-testid="buoc-tham-so">
      <p className="text-sm text-muted-foreground">
        Bước 3 — số và ngày in lên Biên bản, Quyết định. Chưa được cấp thì để trống.
      </p>

      <div className="rounded border p-3 text-sm" data-testid="bo-se-dung">
        <div className="font-medium">Bộ sẽ dựng</div>
        <div className="text-muted-foreground">
          Năm học {namHoc}
          {t ? ` · ${t.tong} hồ sơ · ${t.so_nhom} nhóm ngành – trình độ` : ""}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" data-testid="tham-so-fields">
        <div className="space-y-1">
          <Label htmlFor="b3-so-qd">Số Quyết định</Label>
          <Input id="b3-so-qd" inputMode="numeric" value={thamSo.so_quyet_dinh} onChange={doi("so_quyet_dinh")} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="b3-ngay-qd">Ngày Quyết định</Label>
          <Input id="b3-ngay-qd" type="date" value={thamSo.ngay_quyet_dinh} onChange={doi("ngay_quyet_dinh")} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="b3-dot-so">Đợt số</Label>
          <Input id="b3-dot-so" inputMode="numeric" value={thamSo.dot_so} onChange={doi("dot_so")} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="b3-dot-thang">Tháng của đợt</Label>
          <Input id="b3-dot-thang" inputMode="numeric" value={thamSo.dot_thang} onChange={doi("dot_thang")} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="b3-so-bb">Số Biên bản</Label>
          <Input id="b3-so-bb" inputMode="numeric" value={thamSo.so_bien_ban} onChange={doi("so_bien_ban")} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="b3-ngay-bb">Ngày Biên bản</Label>
          <Input id="b3-ngay-bb" type="date" value={thamSo.ngay_bien_ban} onChange={doi("ngay_bien_ban")} />
        </div>
      </div>

      <div className="space-y-1 text-sm text-muted-foreground">
        <p>Ô đã điền — in lên giấy. Khi ghi nhận bản đã ký, giá trị trên giấy phải khớp; lệch thì phải dựng lại bộ.</p>
        <p>
          Ô để trống — chỗ ấy trên giấy để trống cho văn thư điền tay. Khi ghi nhận, Admin gõ giá trị trên giấy vào các ô này.
        </p>
        <p>
          Không có “bộ chính thức” và “bộ dự thảo” riêng: bộ để trống số vẫn ghi nhận được khi giấy đã ký về. Số và ngày ký chỉ
          bắt buộc ở bước Ghi nhận.
        </p>
      </div>

      <div className="flex items-center justify-between">
        <Button type="button" variant="outline" onClick={onQuayLai} data-testid="tham-so-quay-lai">
          ← Quay lại
        </Button>
        <Button type="button" onClick={onTiep} data-testid="tham-so-tiep">
          Tiếp: Dựng bộ →
        </Button>
      </div>
    </div>
  )
}
