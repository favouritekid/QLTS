"use client"

/**
 * GĐ1b §4.2 / §7 — hộp cam kết "không rõ người nhận": chỉ hiện khi máy chủ trả `requires_ack = true`.
 * Nút lẻ chỉ đi được qua ngoại lệ này khi có CẢ cam kết LẪN lý do (máy chủ kiểm lại; giao diện chỉ chặn nút gửi).
 * Lý do KHÔNG lưu vào "lý do gần đây" / storage (có thể chứa dữ liệu cá nhân).
 */
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"

export const ACK_STATEMENT =
  "Không rõ ai đã nhận / tải giấy này. Tôi cam kết đã tự đối chiếu giấy thật và chịu trách nhiệm về thao tác này."

interface Props {
  id: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  disabled?: boolean
}

export function UnknownSubmitterAckFields({ id, checked, onCheckedChange, disabled }: Props) {
  return (
    <div
      className="rounded-md border border-warning-300 bg-warning-50 p-3 text-sm dark:bg-warning-900/20"
      data-testid="hop-cam-ket-khong-ro-nguoi-nhan"
    >
      <p className="font-medium">Không rõ người nhận giấy</p>
      <div className="mt-2 flex items-start gap-2">
        <Checkbox
          id={id}
          checked={checked}
          onCheckedChange={(v) => onCheckedChange(v === true)}
          disabled={disabled}
          aria-describedby={`${id}-mo-ta`}
        />
        <Label htmlFor={id} id={`${id}-mo-ta`} className="font-normal leading-snug">
          {ACK_STATEMENT}
        </Label>
      </div>
    </div>
  )
}
