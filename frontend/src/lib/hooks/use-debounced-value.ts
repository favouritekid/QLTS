// src/lib/hooks/use-debounced-value.ts
import { useEffect, useState } from "react"

/**
 * Trả về giá trị trễ `delay` ms sau lần đổi cuối — dùng cho ô tìm kiếm để
 * không gọi API mỗi lần gõ. Timeout được dọn khi value/delay đổi.
 */
export function useDebouncedValue<T>(value: T, delay = 400): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}
