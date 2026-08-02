// src/lib/api/session-flags.ts
/**
 * Cờ phiên ở mức cửa sổ — tách khỏi `client.ts` để KHÔNG ai phải kéo cả axios
 * client về chỉ vì cần đọc một boolean.
 *
 * `refresh.ts` bị cấm import `client.ts` (xem chú thích contract ở đầu
 * `refresh.ts`): chúng phụ thuộc ngược lại, và một vòng import ở đúng đường
 * làm-mới-phiên là loại lỗi chỉ lộ ra khi build production. Tệp này là chỗ
 * trung lập cho những cờ mà cả hai phía đều cần.
 *
 * Cờ nằm trên `window` chứ không phải biến module: Turbopack HMR nạp lại
 * module trong lúc dev sẽ dựng một biến mới và làm mất trạng thái, còn
 * `window` thì sống qua mọi lần nạp lại.
 */

const LOGGED_OUT_KEY = "__qlts_logged_out";

/**
 * Người dùng đã chủ động thoát (hoặc phiên vừa bị kết luận là chết) ⇒ chặn mọi
 * request tiếp theo, kể cả những request đang xếp hàng chờ refresh.
 */
export function isApiLoggedOut(): boolean {
  return (
    typeof window !== "undefined" &&
    !!(window as unknown as Record<string, unknown>)[LOGGED_OUT_KEY]
  );
}

export function setApiLoggedOut(value: boolean) {
  if (typeof window !== "undefined") {
    (window as unknown as Record<string, unknown>)[LOGGED_OUT_KEY] = value;
  }
}

// ---------------------------------------------------------------------------
// Throttle của hook proactive
// ---------------------------------------------------------------------------

const THROTTLE_KEY = "qlts_last_refresh_at";

/**
 * ⚖️ **Throttle fail-OPEN — NGƯỢC chiều với nhật ký refresh.**
 *
 * Nhật ký (`refresh-coordination/`) fail-closed vì nó là hàng rào chống hai tab
 * cùng POST. Throttle thì chỉ là **tối ưu** để đỡ POST thừa; cho nó fail-closed
 * nghĩa là một trình duyệt chặn `localStorage` (private mode, cookie/site-data
 * bị tắt) sẽ **không bao giờ** được refresh chủ động — đúng triệu chứng mà cả
 * kế hoạch này sinh ra để chữa. Hàng rào thật vẫn là nhật ký, và nó có đường
 * fail-closed riêng.
 *
 * 🔴 Cả hai chiều đều phải bọc `try/catch`. `getItem` cũng ném được
 * (`SecurityError` khi storage bị chặn), và vì hook gọi `maybeRefresh()` bằng
 * `void`, một lần ném ở đó thành **unhandled rejection** — hook chết trước cả
 * khi kịp gọi refresh, im lặng.
 */
export function readThrottleAt(): number | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(THROTTLE_KEY);
    if (raw === null) return null;
    const value = Number(raw);
    // Rác/NaN ⇒ coi như chưa từng refresh (được phép refresh).
    return Number.isFinite(value) ? value : null;
  } catch {
    return null;
  }
}

/**
 * Ghi mốc throttle.
 *
 * 🔑 Nơi DUY NHẤT được gọi hàm này là `refresh.ts`, và chỉ **sau khi POST đã
 * chứng minh thành công**. Mốc này biểu diễn "lần làm mới THÀNH CÔNG gần nhất",
 * không phải "lần thử gần nhất" — hook chỉ ĐỌC.
 *
 * Bản trước để hook tự ghi ngay trước `await` nhằm thu hẹp cửa sổ đua cross-tab.
 * Cửa sổ đó nay thuộc nhật ký dùng chung, nên ghi sớm chỉ còn để lại một tác
 * dụng phụ: một lần thử HỎNG cũng đặt mốc và hoãn mọi tab 12 phút vì một lần
 * refresh chưa từng thành công.
 */
export function writeThrottleAt(at: number): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(THROTTLE_KEY, String(at));
  } catch {
    // Quota/private mode ⇒ mất throttle, KHÔNG chặn refresh. Xem chú thích trên.
  }
}

/** Xoá mốc — dùng ở các lối thoát phiên để lần sau không bị throttle oan. */
export function clearThrottleAt(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(THROTTLE_KEY);
  } catch {
    // ignore
  }
}
