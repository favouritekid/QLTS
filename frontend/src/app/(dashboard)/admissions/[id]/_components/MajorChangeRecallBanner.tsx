// src/app/(dashboard)/admissions/[id]/_components/MajorChangeRecallBanner.tsx
"use client"

import * as React from "react"
import { Check, Copy, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"

interface Props {
  /** BE-owned: hồ sơ đang trong chu kỳ đổi ngành. */
  cycleOpen: boolean
  /** Tên thí sinh (nếu có) để chèn vào câu mẫu. */
  candidateName?: string | null
}

/**
 * Banner nhắc officer thu hồi giấy báo cũ khi hồ sơ ĐỔI NGÀNH (phương án c).
 *
 * Giấy báo cũ (ngành/số tiền cũ) được BE tự đóng dấu "hết hiệu lực" (superseded)
 * ở bước reprice, nhưng bản GIẤY/PDF đã trao tay thí sinh thì hệ thống không thu
 * hồi được. Banner biến việc nhắc thí sinh thành thao tác có dấu vết, kèm câu
 * mẫu copy-sẵn (officer sửa trước khi gửi). Bản mới phát sau khi kế toán xác nhận.
 *
 * Thin-client: chỉ hiện theo cờ BE ``major_change_cycle_open``.
 */
export function MajorChangeRecallBanner({ cycleOpen, candidateName }: Props) {
  const [copied, setCopied] = React.useState(false)

  if (!cycleOpen) return null

  const who = candidateName?.trim() || "Anh/Chị"
  const template =
    `Kính gửi ${who},\n` +
    `Hồ sơ của bạn đang được cập nhật ngành trúng tuyển. Giấy báo nhập học đã ` +
    `phát trước đó (nếu có) KHÔNG còn hiệu lực — vui lòng KHÔNG sử dụng bản cũ. ` +
    `Nhà trường sẽ gửi giấy báo mới sau khi hoàn tất xác nhận học phí. ` +
    `Trân trọng.`

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(template)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard bị chặn (không HTTPS / quyền) — im lặng, officer copy tay.
    }
  }

  return (
    <div
      role="alert"
      className="mb-4 rounded-lg border-2 border-amber-300 bg-amber-50 p-4 text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200"
    >
      <p className="mb-1 flex items-center gap-2 font-semibold">
        <RefreshCw className="h-4 w-4" aria-hidden="true" />
        Hồ sơ đang đổi ngành — cần thu hồi giấy báo cũ
      </p>
      <p className="text-sm">
        Giấy báo nhập học đã phát trước đó (nếu có) đã <strong>hết hiệu lực</strong>.
        Hãy báo thí sinh KHÔNG dùng bản cũ; bản mới sẽ phát sau khi{" "}
        <strong>kế toán xác nhận học phí</strong>.
      </p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="mt-2.5 gap-1.5 border-amber-400 bg-white/60 hover:bg-white dark:bg-transparent"
        onClick={handleCopy}
      >
        {copied ? (
          <Check className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <Copy className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        {copied ? "Đã copy câu mẫu" : "Copy câu mẫu nhắn thí sinh"}
      </Button>
    </div>
  )
}

export default MajorChangeRecallBanner
