"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useCompareCouncilSet } from "@/hooks/admin/useCouncilDocuments"
import type { CouncilSetDetail } from "@/lib/zod/council-documents"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { thoiDiem } from "./hien-thi"

interface Props {
  bo: CouncilSetDetail
  onQuayLai: () => void
  /** `null` = không có bước kế (người dùng không có quyền ghi nhận) */
  onTiep: (() => void) | null
}

/**
 * Bước 5 — Đối chiếu bản ký (đặc tả 5.5). Gọi `GET /sets/{id}/so-voi-hien-tai` khi BẤM (không tự chạy): máy chủ chỉ
 * trả SỐ DÒNG + TÊN trường đã đổi, không giá trị cũ / mới — giao diện hiện đúng thế, không tự so gì.
 */
export function CouncilCompareStep({ bo, onQuayLai, onTiep }: Props) {
  const so = useCompareCouncilSet()
  const [luc, setLuc] = useState<string | null>(null)
  const kq = so.data
  const soDong = kq ? kq.dong_khac.length + kq.khong_dung_lai_duoc.length + kq.mat_ho_so.length : 0

  return (
    <div className="space-y-4" data-testid="buoc-doi-chieu">
      <p className="text-sm text-muted-foreground">
        Bước 5 — trước khi ghi nhận, xem dữ liệu nào đã đổi so với lúc dựng, để đối chiếu với giấy đã ký.
      </p>
      <div className="text-sm">
        Bộ #{bo.id} · dựng lúc {thoiDiem(bo.tao_luc)} · {bo.so_ho_so} hồ sơ
      </div>

      <Button
        type="button"
        variant="outline"
        disabled={so.isPending}
        data-testid="so-sanh"
        onClick={() => so.mutate({ setId: bo.id }, { onSuccess: () => setLuc(new Date().toISOString()) })}
      >
        {so.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        Kiểm tra thay đổi sau khi dựng
      </Button>

      <CouncilErrorAlert error={so.error} testId="so-sanh-loi" />

      {kq ? (
        soDong === 0 ? (
          <p className="text-sm" data-testid="khong-doi">
            Không dòng nào đổi so với lúc dựng{luc ? ` (kiểm lúc ${thoiDiem(luc)})` : ""}.
          </p>
        ) : (
          <div className="space-y-2 text-sm" data-testid="co-doi">
            <p className="font-medium">
              {soDong} dòng đã đổi so với lúc dựng{luc ? ` (kiểm lúc ${thoiDiem(luc)})` : ""}
            </p>
            <ul className="list-disc space-y-1 pl-5">
              {kq.dong_khac.map((d) => (
                <li key={`k${d.stt}`} data-testid={`dong-doi-${d.stt}`}>{`Dòng ${d.stt} — đổi: ${d.truong.join(", ")}`}</li>
              ))}
              {kq.khong_dung_lai_duoc.map((d) => (
                <li key={`x${d.stt}`} data-testid={`dong-khong-dung-lai-${d.stt}`}>
                  {`Dòng ${d.stt} — không dựng lại được để so (${d.ma.join(", ")})`}
                </li>
              ))}
              {kq.mat_ho_so.map((stt) => (
                <li key={`m${stt}`} data-testid={`dong-mat-ho-so-${stt}`}>{`Dòng ${stt} — hồ sơ không còn`}</li>
              ))}
            </ul>
            <p className="text-muted-foreground">
              Giấy đã ký in theo bộ #{bo.id} (dữ liệu lúc dựng) thì vẫn ghi nhận được. Nếu cần giấy mới theo dữ liệu hiện tại thì
              dựng bộ mới và trình ký lại.
            </p>
          </div>
        )
      ) : null}

      <div className="flex items-center justify-between">
        <Button type="button" variant="outline" onClick={onQuayLai} data-testid="doi-chieu-quay-lai">
          ← Quay lại
        </Button>
        {onTiep ? (
          <Button type="button" onClick={onTiep} data-testid="doi-chieu-tiep">
            Tiếp: Ghi nhận →
          </Button>
        ) : null}
      </div>
    </div>
  )
}
