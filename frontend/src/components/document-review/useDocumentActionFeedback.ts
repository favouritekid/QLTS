"use client"

/**
 * Xử lý kết quả chung của ba hộp nút lẻ GĐ1b: 409 `VERSION_CHANGED` ⇒ báo + ĐÓNG hộp (phiên bản đang cầm đã cũ; hook đã
 * làm mới chi tiết); lỗi khác ⇒ giữ hộp, hiện câu. Không `console.*`.
 */
import { useState } from "react"
import { toast } from "sonner"

import { describeDocumentActionError } from "@/lib/document-review/messages"

export function useDocumentActionFeedback(onClose: () => void) {
  const [error, setError] = useState<string | null>(null)

  const onError = (e: unknown) => {
    const view = describeDocumentActionError(e)
    if (view.kind === "version_changed") {
      toast.warning(view.message)
      onClose()
      return
    }
    setError(view.message)
  }

  const onSuccess = (message: string) => {
    toast.success(message)
    onClose()
  }

  return { error, clearError: () => setError(null), onError, onSuccess }
}
