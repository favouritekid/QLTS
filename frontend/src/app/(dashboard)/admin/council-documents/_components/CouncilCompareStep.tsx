"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useCompareCouncilSet } from "@/hooks/admin/useCouncilDocuments"
import type { CouncilSetDetail } from "@/lib/zod/council-documents"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { compareFieldLabel, formatTime } from "./display"

interface Props {
  docSet: CouncilSetDetail
  onBack: () => void
  /** `null` = không có bước kế (người dùng không có quyền ghi nhận) */
  onNext: (() => void) | null
}

/**
 * Bước 5 — Đối chiếu bản ký (đặc tả 5.5). Gọi `GET /sets/{id}/so-voi-hien-tai` khi BẤM (không tự chạy): máy chủ chỉ
 * trả SỐ DÒNG + TÊN trường đã đổi, không giá trị cũ / mới — giao diện hiện đúng thế, không tự so gì.
 */
export function CouncilCompareStep({ docSet, onBack, onNext }: Props) {
  const number = useCompareCouncilSet()
  const [time, setTime] = useState<string | null>(null)
  const result = number.data
  const rowCount = result ? result.dong_khac.length + result.khong_dung_lai_duoc.length + result.mat_ho_so.length : 0

  return (
    <div className="space-y-4" data-testid="buoc-doi-chieu">
      <p className="text-sm text-muted-foreground">
        Bước 5 — trước khi ghi nhận, xem dữ liệu nào đã đổi so với lúc dựng, để đối chiếu với giấy đã ký.
      </p>
      <div className="text-sm">
        Bộ #{docSet.id} · dựng lúc {formatTime(docSet.tao_luc)} · {docSet.so_ho_so} hồ sơ
      </div>

      <Button
        type="button"
        variant="outline"
        disabled={number.isPending}
        data-testid="so-sanh"
        onClick={() => number.mutate({ setId: docSet.id }, { onSuccess: () => setTime(new Date().toISOString()) })}
      >
        {number.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        Kiểm tra thay đổi sau khi dựng
      </Button>

      <CouncilErrorAlert error={number.error} testId="so-sanh-loi" />

      {result ? (
        rowCount === 0 ? (
          <p className="text-sm" data-testid="khong-doi">
            Không dòng nào đổi so với lúc dựng{time ? ` (kiểm lúc ${formatTime(time)})` : ""}.
          </p>
        ) : (
          <div className="space-y-2 text-sm" data-testid="co-doi">
            <p className="font-medium">
              {rowCount} dòng đã đổi so với lúc dựng{time ? ` (kiểm lúc ${formatTime(time)})` : ""}
            </p>
            <ul className="list-disc space-y-1 pl-5">
              {result.dong_khac.map((d) => (
                <li key={`k${d.stt}`} data-testid={`dong-doi-${d.stt}`}>{`Dòng ${d.stt} — đổi: ${d.truong.map(compareFieldLabel).join(", ")}`}</li>
              ))}
              {result.khong_dung_lai_duoc.map((d) => (
                <li key={`x${d.stt}`} data-testid={`dong-khong-dung-lai-${d.stt}`}>
                  {`Dòng ${d.stt} — không dựng lại được để so (${d.ma.join(", ")})`}
                </li>
              ))}
              {result.mat_ho_so.map((seq) => (
                <li key={`m${seq}`} data-testid={`dong-mat-ho-so-${seq}`}>{`Dòng ${seq} — hồ sơ không còn`}</li>
              ))}
            </ul>
            <p className="text-muted-foreground">
              Giấy đã ký in theo bộ #{docSet.id} (dữ liệu lúc dựng) thì vẫn ghi nhận được. Nếu cần giấy mới theo dữ liệu hiện tại thì
              dựng bộ mới và trình ký lại.
            </p>
          </div>
        )
      ) : null}

      <div className="flex items-center justify-between">
        <Button type="button" variant="outline" onClick={onBack} data-testid="doi-chieu-quay-lai">
          ← Quay lại
        </Button>
        {onNext ? (
          <Button type="button" onClick={onNext} data-testid="doi-chieu-tiep">
            Tiếp: Ghi nhận →
          </Button>
        ) : null}
      </div>
    </div>
  )
}
