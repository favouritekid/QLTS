// src/lib/auth/forced-password-change.ts
/**
 * F128 / F131 — người dùng BỊ BUỘC đổi mật khẩu (`password_reset_required`).
 *
 * MỘT nguồn cho mọi lối dẫn tới form đổi mật khẩu: interceptor Axios
 * (`client.ts`), SSR (`server.ts`), sau đăng nhập (`useAuth`), sau "Không phải
 * tôi" (`secure-account-outcome.ts`) và thông báo cắt socket (`socket/client.ts`).
 *
 * Backend là nguồn sự thật: mọi API trừ `POST /api/auth/change-password` và
 * `GET /api/users/me` trả 403 `detail.code = PASSWORD_CHANGE_REQUIRED`. Form
 * nằm ở `/settings` (trang gốc của Cài đặt) — route `/settings/change-password`
 * mà bản cũ trỏ tới KHÔNG tồn tại.
 *
 * Runtime-agnostic (dùng được ở cả Server Component lẫn trình duyệt): không
 * `window`, không API riêng của Node.
 */

export const PASSWORD_CHANGE_REQUIRED_CODE = "PASSWORD_CHANGE_REQUIRED";

/** Trang có `ChangePasswordForm`. */
export const FORCED_PASSWORD_CHANGE_PATH = "/settings";

/** Đích điều hướng; `forced=true` bật cảnh báo trên form. */
export const FORCED_PASSWORD_CHANGE_URL = `${FORCED_PASSWORD_CHANGE_PATH}?forced=true`;

/** Tên sự kiện Socket.IO server gửi NGAY TRƯỚC khi cắt socket vì cờ này. */
export const PASSWORD_CHANGE_REQUIRED_SOCKET_EVENT = "password_change_required";

/** Lý do `revalidate_auth` trả về khi từ chối vì cờ này. */
export const PASSWORD_CHANGE_REQUIRED_SOCKET_REASON = "Password change required";

/**
 * Thân phản hồi lỗi có phải 403 "phải đổi mật khẩu" của backend không:
 * `{"detail": {"code": "PASSWORD_CHANGE_REQUIRED", ...}}`.
 */
export function isPasswordChangeRequiredBody(body: unknown): boolean {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return false;
  }
  const detail = (body as { detail: unknown }).detail;
  return (
    typeof detail === "object" &&
    detail !== null &&
    "code" in detail &&
    (detail as { code: unknown }).code === PASSWORD_CHANGE_REQUIRED_CODE
  );
}

/**
 * Đang ở chính trang form chưa. Ở đó KHÔNG điều hướng nữa: khung dashboard
 * (thông báo, sidebar…) vẫn gọi API nghiệp vụ và nhận 403 — mỗi lần chuyển
 * trang lại tải khung ấy, tức vòng lặp tải lại vô hạn.
 */
export function isOnForcedPasswordChangePage(pathname: string | null | undefined): boolean {
  return pathname === FORCED_PASSWORD_CHANGE_PATH;
}
