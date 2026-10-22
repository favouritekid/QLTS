/**
 * Kết quả "Bảo mật tài khoản" (POST /api/security/secure-account) — MỘT nguồn
 * cho hai màn hình (Cài đặt › Bảo mật, Lịch sử đăng nhập).
 *
 * Backend quyết định, FE chỉ hiển thị (thin client):
 *  - `relogin_required = false`: phiên hiện tại được GIỮ, các phiên khác bị thu
 *    hồi ⇒ chuyển sang trang cài đặt để đổi mật khẩu.
 *  - `relogin_required = true`: backend KHÔNG xác định được phiên hiện tại nên
 *    đã thu hồi MỌI phiên (kể cả phiên này) và xoá cookie xác thực ⇒ phải đăng
 *    nhập lại. Điều hướng bằng tải trang đầy đủ tới `/login?force_login=true` —
 *    đúng lối "cookie refresh đã bị xoá thật" mà `LoginForm` phân loại — để dọn
 *    sạch state phía client; KHÔNG `router.push("/settings")` (trang ấy sẽ chỉ
 *    401 rồi rơi vào lối `reauth`, vốn dành cho phiên CÒN hiệu lực).
 */
import type { SecureAccountResponse } from "@/types/security";
import { buildLoginRedirect } from "./login-redirect";

export interface SecureAccountOutcome {
  /** Câu báo thành công hiển thị cho người dùng. */
  message: string;
  /** Đích điều hướng sau khi báo. */
  next: { kind: "settings" } | { kind: "relogin"; url: string };
}

export function secureAccountOutcome(response: SecureAccountResponse): SecureAccountOutcome {
  if (response.relogin_required) {
    return {
      message:
        `Tài khoản đã được bảo mật. Mọi phiên (${response.sessions_revoked}) đã bị thu hồi, kể cả phiên này. ` +
        "Đang chuyển đến trang đăng nhập...",
      next: { kind: "relogin", url: buildLoginRedirect(null, { forceLogin: true }) },
    };
  }
  return {
    message:
      `Tài khoản đã được bảo mật. ${response.sessions_revoked} phiên đã bị thu hồi. ` +
      "Đang chuyển đến trang đổi mật khẩu...",
    next: { kind: "settings" },
  };
}
