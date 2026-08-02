// src/hooks/useProactiveTokenRefresh.ts
"use client";

import { useEffect, useRef } from "react";
import { refreshAccessToken, isRefreshFailure } from "@/lib/api/refresh";
import { isApiLoggedOut } from "@/lib/api/client";

// Access token sống 15' (backend). Refresh chủ động mỗi 13' để luôn còn
// biên an toàn ~2'. Ngưỡng 12' chặn refresh quá dày khi nhiều tab / nhiều
// sự kiện focus liên tiếp.
const REFRESH_INTERVAL_MS = 13 * 60 * 1000;
const MIN_REFRESH_GAP_MS = 12 * 60 * 1000;
const LAST_REFRESH_KEY = "qlts_last_refresh_at";

/**
 * Proactive token refresh cho tab ĐANG HOẠT ĐỘNG.
 *
 * Giữ access token sống khi user còn dùng app → giảm 401 và tránh bị
 * middleware (`proxy.ts`) đá ra login khi hard-reload/điều hướng sau khi
 * access hết hạn. KHÔNG thay thế reactive 401 flow — chỉ bổ trợ.
 *
 * Multi-tab guard (token rotation backend → 2 refresh đồng thời có thể bị
 * reuse-detection → logout oan):
 *  - CHỈ tab `visible` mới refresh (thường chỉ 1 tab visible tại 1 thời điểm).
 *  - `localStorage[qlts_last_refresh_at]` (chia sẻ giữa tab) + ghi-trước-await
 *    (claim slot) để thu hẹp cửa sổ đua xuống sub-ms.
 *  - Refresh fail → KHÔNG logout (để reactive 401 xử lý); rollback timestamp
 *    theo CAS (chỉ khi slot vẫn là của lần gọi này) để cho phép thử lại sớm.
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
      const now = Date.now();
      const prevRaw = window.localStorage.getItem(LAST_REFRESH_KEY);
      const prevNum = prevRaw ? Number(prevRaw) : 0;
      // Sanitize: corrupt/NaN → 0 (coi như chưa refresh). Clamp elapsed>=0 để
      // timestamp future-dated (clock-skew/tamper) KHÔNG kẹt throttle vĩnh viễn.
      const prev = Number.isFinite(prevNum) ? prevNum : 0;
      const elapsed = now - prev;
      if (elapsed >= 0 && elapsed < MIN_REFRESH_GAP_MS) {
        return; // tab khác (hoặc chính tab này) vừa refresh → bỏ qua
      }

      // Claim slot TRƯỚC khi await (thu hẹp race cross-tab xuống sub-ms).
      const stamp = String(now);
      window.localStorage.setItem(LAST_REFRESH_KEY, stamp);
      runningRef.current = true;
      try {
        await refreshAccessToken();
      } catch (error) {
        // Nuốt lỗi — KHÔNG logout/redirect (reactive 401 của request kế
        // tiếp sẽ xử lý). Rollback CAS: chỉ khôi phục nếu slot vẫn là `stamp`
        // mình vừa ghi (chưa tab/lần khác ghi đè) → cho phép thử lại sớm
        // sau lỗi mạng tạm, KHÔNG đạp lên refresh thành công của tab khác.
        //
        // NGOẠI LỆ: rate limit thì KHÔNG rollback. Rollback sẽ xoá luôn
        // throttle 12 phút, mà `onWake` gắn với cả `visibilitychange` lẫn
        // `focus` → mười lần alt-tab là mười POST /auth/refresh nữa vào đúng
        // cái bucket vừa cạn. Giữ nguyên timestamp = tôn trọng throttle.
        //
        // Đọc thẳng `outcome` đã phân loại thay vì hỏi lại một hàm trạng thái:
        // outcome đi kèm chính lần thử này, không thể trôi lệch.
        if (
          isRefreshFailure(error) &&
          error.outcome.kind === "safe-retryable"
        ) {
          return;
        }
        if (window.localStorage.getItem(LAST_REFRESH_KEY) === stamp) {
          // Khôi phục prev hợp lệ; nếu prev corrupt/null → xoá (lần sau coi như
          // chưa refresh, tự lành sau 1 refresh thành công).
          if (prevRaw !== null && Number.isFinite(Number(prevRaw))) {
            window.localStorage.setItem(LAST_REFRESH_KEY, prevRaw);
          } else {
            window.localStorage.removeItem(LAST_REFRESH_KEY);
          }
        }
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
