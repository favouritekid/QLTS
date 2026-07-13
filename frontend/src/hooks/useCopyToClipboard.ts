// src/hooks/useCopyToClipboard.ts
"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { copyToClipboard } from "@/lib/clipboard"

/**
 * Copy-to-clipboard với trạng thái `copied` tự tắt sau `resetMs` — gom pattern
 * lặp ở nhiều nút copy (consult link, magic link, số điện thoại…). Tự
 * clearTimeout khi copy lại/unmount (chống set-state sau unmount). `copy` trả
 * boolean thành/bại để caller báo lỗi (clipboard bị chặn / context HTTP).
 */
export function useCopyToClipboard(resetMs = 2000) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )

  const copy = useCallback(
    async (text: string): Promise<boolean> => {
      // copyToClipboard tự fallback execCommand khi HTTP/insecure (không throw).
      const ok = await copyToClipboard(text)
      if (ok) {
        setCopied(true)
        if (timer.current) clearTimeout(timer.current)
        timer.current = setTimeout(() => setCopied(false), resetMs)
      }
      return ok
    },
    [resetMs],
  )

  /** Reset thủ công (vd khi đổi nội dung nguồn). */
  const reset = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    setCopied(false)
  }, [])

  return { copied, copy, reset }
}
