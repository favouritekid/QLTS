"use client"

import { AlertCircle } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { describeCouncilDocumentError } from "@/lib/api/council-documents"
import type { CouncilSetGate } from "@/lib/zod/council-documents"

import { nhanTrangThai } from "./hien-thi"

/**
 * Danh sách của cổng dựng bộ (lượt G) — y nguyên phản hồi máy chủ: từng lý do chặn kèm SỐ DÒNG,
 * hồ sơ ở trạng thái cần cảnh báo kèm số đếm + số dòng. Không có mã hồ sơ (máy chủ chỉ trả số
 * dòng). Câu "cần admin xác nhận" hiện khi MÁY CHỦ nói người gọi không được xác nhận.
 */
export function CouncilGateDetail({ gate }: { gate: CouncilSetGate }) {
  const canhBao = Object.entries(gate.canh_bao.so_ho_so_theo_trang_thai)
  return (
    <div className="mt-2 space-y-2 text-sm" data-testid="council-gate">
      {gate.chan.length ? (
        <div>
          <p className="font-medium">Không đưa được vào văn bản (chặn — sửa hồ sơ hoặc bỏ dòng):</p>
          <ul className="list-disc space-y-1 pl-5">
            {gate.chan.map((c) => (
              <li key={`${c.ma}:${c.trang_thai ?? ""}`} data-testid="gate-chan-item">
                {`${c.mo_ta}${c.trang_thai ? ` — trạng thái ${nhanTrangThai(c.trang_thai)}` : ""}: ${c.so_ho_so} hồ sơ — dòng ${c.dong.join(", ")}`}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {canhBao.length ? (
        <div>
          <p className="font-medium">Hồ sơ ở trạng thái cần cảnh báo (cần admin xác nhận):</p>
          <ul className="list-disc space-y-1 pl-5">
            {canhBao.map(([s, n]) => (
              <li key={s} data-testid="gate-canh-bao-item">
                {`${nhanTrangThai(s)}: ${n} hồ sơ — dòng ${(gate.canh_bao.dong_theo_trang_thai[s] ?? []).join(", ")}`}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {gate.can_admin_xac_nhan && !gate.nguoi_goi_duoc_xac_nhan ? (
        <p className="font-medium" data-testid="gate-can-admin">
          Cần admin xác nhận — tài khoản của bạn không xác nhận được.
        </p>
      ) : null}
    </div>
  )
}

/**
 * Lỗi của một thao tác văn bản Hội đồng — câu chính + (lỗi miền) câu nguyên văn
 * của máy chủ, giữ xuống dòng; lỗi cổng dựng bộ kèm danh sách theo số dòng. Không in gì ra
 * console.
 */
export function CouncilErrorAlert({
  error,
  testId,
}: {
  error: unknown
  testId?: string
}) {
  if (!error) return null
  const loi = describeCouncilDocumentError(error)
  return (
    <Alert variant="destructive" data-testid={testId ?? "council-error"} role="alert">
      <AlertCircle className="h-4 w-4" />
      <AlertTitle>{loi.title}</AlertTitle>
      {loi.detail ? (
        <AlertDescription className="whitespace-pre-line" data-testid="council-error-detail">
          {loi.detail}
        </AlertDescription>
      ) : null}
      {loi.gate ? <CouncilGateDetail gate={loi.gate} /> : null}
    </Alert>
  )
}
