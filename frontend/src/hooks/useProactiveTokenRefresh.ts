// src/hooks/useProactiveTokenRefresh.ts
"use client";

import { useEffect, useRef } from "react";
import { refreshAccessToken } from "@/lib/api/refresh";
import { isApiLoggedOut, readThrottleAt } from "@/lib/api/session-flags";

// Access token sống 15' (backend). Refresh chủ động mỗi 13' để luôn còn
// biên an toàn ~2'. Ngưỡng 12' chặn refresh quá dày khi nhiều tab / nhiều
// sự kiện focus liên tiếp.
const REFRESH_INTERVAL_MS = 13 * 60 * 1000;
const MIN_REFRESH_GAP_MS = 12 * 60 * 1000;

/**
 * Proactive token refresh cho tab ĐANG HOẠT ĐỘNG.
 *
 * Giữ access token sống khi user còn dùng app → giảm 401 và tránh bị
 * middleware (`proxy.ts`) đá ra login khi hard-reload/điều hướng sau khi
 * access hết hạn. KHÔNG thay thế reactive 401 flow — chỉ bổ trợ.
 *
 * Chống hai tab cùng POST **không** thuộc về hook này. Việc đó nằm ở nhật ký
 * dùng chung (`lib/api/refresh-coordination/`), nơi đúng một tab giành được
 * lease cho mỗi lần làm mới. Hook chỉ còn hai việc:
 *  - CHỈ tab `visible` mới thử (giảm số lần gọi vô ích).
 *  - ĐỌC `qlts_last_refresh_at` để khỏi gọi lại quá dày.
 *
 * 🔑 Mốc đó biểu diễn **"lần làm mới đã CHỨNG MINH thành công gần nhất"**, nên
 * chỉ `refresh.ts` được ghi, và chỉ khi có bằng chứng thế hệ mới. Bản trước ghi
 * ngay trước `await` ("claim slot") để thu hẹp cửa sổ đua — nhưng khi cửa sổ đua
 * đã do nhật ký lo, việc ghi sớm chỉ còn một tác dụng: một lần thử **hỏng** vẫn
 * kịp đặt mốc, và mọi tab bị hoãn 12 phút vì một lần refresh chưa từng thành
 * công. Rollback CAS sinh ra để chữa đúng chỗ đó, và nó biến mất cùng nguyên
 * nhân.
 *
 * Refresh hỏng → KHÔNG logout; reactive 401 của request kế tiếp sẽ xử lý.
 */
export function useProactiveTokenRefresh(enabled: boolean) {
  const runningRef = useRef(false);

  useEffect(() => {
    if (!enabled) return;
    if (typeof window === "undefined") return;

    let cancelled = false;

    const maybeRefresh = async () => {
      // Chỉ tab đang xem mới refresh (guard đồng-thời multi-tab chính).
      if (document.visibilityState !== "visible") return;
      if (isApiLoggedOut()) return;
      if (runningRef.current) return; // tránh chồng trong cùng tab

      // KHÔNG còn kiểm cooldown ở đây: cooldown nay nằm trong nhật ký dùng
      // chung giữa các tab, và `refreshAccessToken()` tự dừng trước khi chạm
      // mạng khi chưa tới `retryAt`. Giữ một bản sao cooldown cục bộ ở hook là
      // tạo nguồn thứ hai, và hai nguồn sẽ trôi lệch nhau.
      // 🔑 Hook chỉ ĐỌC mốc. Nơi duy nhất GHI là `refresh.ts`, sau khi POST đã
      // chứng minh thành công — mốc này biểu diễn "lần làm mới thành công gần
      // nhất", không phải "lần thử gần nhất".
      //
      // Bản trước ghi trước `await` để thu hẹp cửa sổ đua cross-tab; nay cửa sổ
      // đó do nhật ký dùng chung lo (`refresh-coordination/`), nên ghi sớm chỉ
      // còn tác dụng phụ: một lần thử HỎNG cũng đặt mốc và hoãn mọi tab 12 phút.
      const prev = readThrottleAt();
      if (prev !== null) {
        const elapsed = Date.now() - prev;
        // `elapsed < 0` = mốc nằm ở tương lai (lệch đồng hồ / bị sửa). KHÔNG
        // coi là "vừa refresh": làm thế thì throttle kẹt vĩnh viễn.
        if (elapsed >= 0 && elapsed < MIN_REFRESH_GAP_MS) {
          return; // tab khác (hoặc chính tab này) vừa refresh → bỏ qua
        }
      }

      runningRef.current = true;
      try {
        await refreshAccessToken();
      } catch {
        // Nuốt lỗi — KHÔNG logout/redirect; reactive 401 của request kế tiếp sẽ
        // xử lý. Không còn rollback nào để làm: hook không ghi gì, nên cũng
        // chẳng có gì để hoàn tác.
      } finally {
        runningRef.current = false;
      }
    };

    const intervalId = setInterval(() => {
      void maybeRefresh();
    }, REFRESH_INTERVAL_MS);

    const onWake = () => {
      if (!cancelled) void maybeRefresh();
    };
    document.addEventListener("visibilitychange", onWake);
    window.addEventListener("focus", onWake);

    // 1 lần khi mount (cover tab mở với access token đã cũ).
    void maybeRefresh();

    return () => {
      cancelled = true;
      clearInterval(intervalId);
      document.removeEventListener("visibilitychange", onWake);
      window.removeEventListener("focus", onWake);
    };
  }, [enabled]);
}
