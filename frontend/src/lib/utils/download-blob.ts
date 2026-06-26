/**
 * Tiện ích tải Blob về máy (dùng chung — tránh lặp logic createObjectURL/revoke).
 */
import { AxiosError } from "axios"

/** Trigger browser download của 1 Blob qua thẻ <a download> tạm (cleanup revoke). */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

/**
 * Lấy message lỗi khi tải blob: vì `responseType:'blob'`, body lỗi (JSON) bị axios bọc
 * thành Blob → phải đọc `.text()` rồi parse mới ra `detail` thật (không thì luôn fallback).
 */
export async function blobErrorMessage(
  error: AxiosError,
  fallback: string,
): Promise<string> {
  const data = error.response?.data as unknown
  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text())
      if (typeof parsed?.detail === "string") return parsed.detail
    } catch {
      /* blob không phải JSON → giữ fallback */
    }
  } else if (
    typeof (data as { detail?: unknown } | undefined)?.detail === "string"
  ) {
    return (data as { detail: string }).detail
  }
  return fallback
}
