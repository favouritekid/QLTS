// src/app/(dashboard)/admissions/[id]/_components/MajorChangeRecallBanner.tsx
"use client"

import * as React from "react"
import { Check, Copy, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"

interface Props {
  /** BE-owned: hồ sơ đang trong chu kỳ đổi ngành. */
  cycleOpen: boolean
  /**
   * BE-owned: GIAI ĐOẠN 2 — đã định giá lại, đang chờ kế toán xác nhận. CHỈ khi
   * đó BE mới đóng dấu hết hiệu lực (supersede) giấy báo hiện hành. Giai đoạn 1
   * (admin vừa cho phép đổi ngành, officer chưa nộp lại) giấy cũ VẪN còn hiệu
   * lực — và chu kỳ còn có thể bị bỏ dở (rollback thường clear cờ), nên nói "hết
   * hiệu lực" lúc đó là thông tin sai gửi cho cả officer lẫn thí sinh.
   */
  awaitingConfirmation?: boolean
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
export function MajorChangeRecallBanner({
  cycleOpen,
  awaitingConfirmation = false,
  candidateName,
}: Props) {
  // Rules of Hooks: MỌI useState phải gọi TRƯỚC early-return `!cycleOpen`
  // — nếu không, khi cờ lật false→true số hook đổi → React crash.
  const [copied, setCopied] = React.useState(false)
  const [failed, setFailed] = React.useState(false)

  if (!cycleOpen) return null

  const who = candidateName?.trim() || "Anh/Chị"
  // Câu mẫu KHÁC nhau theo giai đoạn: chỉ tuyên bố "hết hiệu lực" khi BE đã thực
  // sự supersede giấy (sau reprice). Trước đó chỉ nhắc CHỜ, vì chu kỳ có thể bị
  // bỏ dở và giấy hiện hành vẫn dùng được.
  const template = awaitingConfirmation
    ? `Kính gửi ${who},\n` +
      `Hồ sơ của bạn đã được cập nhật ngành trúng tuyển. Giấy báo nhập học đã ` +
      `phát trước đó (nếu có) KHÔNG còn hiệu lực — vui lòng KHÔNG sử dụng bản cũ. ` +
      `Nhà trường sẽ gửi giấy báo mới sau khi hoàn tất xác nhận học phí. ` +
      `Trân trọng.`
    : `Kính gửi ${who},\n` +
      `Hồ sơ của bạn đang được xem xét đổi ngành trúng tuyển. Vui lòng CHỜ nhà ` +
      `trường xác nhận trước khi làm thủ tục nhập học; nếu ngành thay đổi, nhà ` +
      `trường sẽ gửi giấy báo mới thay cho bản hiện tại. ` +
      `Trân trọng.`

  const handleCopy = async () => {
    setFailed(false)
    // navigator.clipboard là undefined trên HTTP (LAN test 192.168.x) → fallback
    // execCommand qua textarea ẩn; nếu vẫn không được thì báo lỗi để officer
    // copy tay, KHÔNG im lặng (review #13).
    let ok = false
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(template)
        ok = true
      }
    } catch {
      ok = false
    }
    if (!ok) {
      try {
        const ta = document.createElement("textarea")
        ta.value = template
        ta.style.position = "fixed"
        ta.style.opacity = "0"
        document.body.appendChild(ta)
        ta.select()
        ok = document.execCommand("copy")
        document.body.removeChild(ta)
      } catch {
        ok = false
      }
    }
    if (ok) {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } else {
      setFailed(true)
    }
  }

  return (
    <div
      role="alert"
      className="mb-4 rounded-lg border-2 border-amber-300 bg-amber-50 p-4 text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200"
    >
      <p className="mb-1 flex items-center gap-2 font-semibold">
        <RefreshCw className="h-4 w-4" aria-hidden="true" />
        {awaitingConfirmation
          ? "Hồ sơ đang đổi ngành — cần thu hồi giấy báo cũ"
          : "Hồ sơ đang chờ đổi ngành — chưa thu hồi giấy báo"}
      </p>
      {awaitingConfirmation ? (
        <p className="text-sm">
          Giấy báo nhập học đã phát trước đó (nếu có) đã{" "}
          <strong>hết hiệu lực</strong>. Hãy báo thí sinh KHÔNG dùng bản cũ; bản
          mới sẽ phát sau khi <strong>kế toán xác nhận học phí</strong>.
        </p>
      ) : (
        <p className="text-sm">
          Giấy báo đã phát <strong>vẫn còn hiệu lực</strong> cho tới khi hồ sơ
          được nộp lại và học phí ngành mới được định giá — lúc đó hệ thống mới
          đóng dấu hết hiệu lực bản cũ. Hãy nhắc thí sinh <strong>chờ</strong>,
          đừng nói bản cũ đã bỏ.
        </p>
      )}
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
      {failed && (
        <div className="mt-2">
          <p className="mb-1 text-xs">
            Không copy tự động được (trình duyệt chặn) — hãy chọn và copy tay:
          </p>
          <textarea
            readOnly
            value={template}
            rows={4}
            className="w-full resize-none rounded border border-amber-300 bg-white/70 p-2 text-xs dark:bg-transparent"
            onFocus={(e) => e.currentTarget.select()}
          />
        </div>
      )}
    </div>
  )
}

export default MajorChangeRecallBanner
