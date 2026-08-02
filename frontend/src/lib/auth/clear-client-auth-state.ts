// src/lib/auth/clear-client-auth-state.ts
/**
 * Dọn state phía CLIENT của một phiên — và chỉ có thế.
 *
 * 🔴 Hàm này KHÔNG đụng tới cookie và KHÔNG đụng tới nhật ký refresh. Đó là
 * ranh giới quan trọng nhất ở đây:
 *
 *  - cookie do proxy hoặc backend xoá (`force_login`, `/auth/logout`);
 *  - nhật ký refresh chỉ được xoá qua `noteSessionTransition()` với một
 *    `ClearTrigger` nói rõ lối thoát nào đã THỰC SỰ hoàn tất.
 *
 * Gộp ba việc đó vào một hàm là cách chắc chắn nhất để `reauth` — lối CỐ Ý giữ
 * cookie refresh — vô tình xoá mất một bản ghi `ambiguous` đang cấm POST.
 *
 * Đồng bộ, không `async`: chỗ gọi quan trọng nhất (`LoginSessionResetGate`) cần
 * bảo đảm store đã sạch TRƯỚC khi `useAuth()` được gọi lần đầu. Một `await` ở
 * giữa là một cửa sổ để `useQuery(["auth","me"])` kịp phát request bằng danh
 * tính của phiên vừa chết.
 */
import { setApiLoggedOut } from "@/lib/api/session-flags";
import { useAuthStore } from "@/lib/stores/auth.store";

export function clearClientAuthState(): void {
  if (typeof window === "undefined") return;

  // Chặn request TRƯỚC khi dọn store: thứ tự ngược lại để hở một khoảnh khắc
  // mà store đã trống nhưng interceptor vẫn cho request đi.
  setApiLoggedOut(true);

  try {
    useAuthStore.getState().logout();
  } catch {
    // Best-effort: store hỏng thì cờ chặn request ở trên vẫn còn tác dụng.
  }
}
