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
