// src/lib/auth/login-redirect.ts
/**
 * Helper canonical cho luồng redirect tới /login + giữ return-url.
 *
 * Dùng chung cho cả EDGE (proxy.ts middleware) lẫn BROWSER (client.ts,
 * useAuth.ts). Vì vậy module này PHẢI runtime-agnostic: chỉ dùng
 * URLSearchParams/String — KHÔNG `window`, không API riêng của Node.
 */

/**
 * Một chuỗi redirect có an toàn để điều hướng nội bộ không.
 *
 * CHỈ validate PHẦN PATH (đoạn trước `?`/`#`) — query/hash để TỰ DO,
 * cho phép giá trị filter/timestamp/text chứa `:` hoặc encoded slash
 * (vd `/finance?from=2026-06-24T10:00:00`, `/leads?q=a:b`). An toàn vì
 * path đã chắc chắn internal (bắt đầu `/`, không `//`, không protocol),
 * và `router.push`/`new URL(x, origin)` không thể đổi origin từ query.
 *
 * Cũng reject các public auth path (/login, /register, ...) làm return-url —
 * tránh vòng lặp redirect về chính trang đăng nhập.
 */
const AUTH_PATHS = ["/login", "/register", "/forgot-password", "/reset-password"];

export function isValidRedirect(
  url: string | null | undefined,
): url is string {
  if (!url) return false;
  if (!url.startsWith("/")) return false;
  if (url.startsWith("//")) return false;
  // Chỉ xét path-part (đoạn trước query/hash).
  const pathPart = url.split(/[?#]/, 1)[0];
  if (pathPart.includes(":")) return false; // protocol-like
  if (pathPart.includes("\\")) return false; // backslash
  if (/%2f|%5c/i.test(pathPart)) return false; // encoded slash/backslash
  // Không return-url về trang auth (tránh loop /login?redirect=/login).
  if (AUTH_PATHS.some((p) => pathPart === p || pathPart.startsWith(`${p}/`)))
    return false;
  return true;
}

export interface BuildLoginRedirectOptions {
  /** Thêm `force_login=true` (proxy middleware sẽ xoá cookie cũ). */
  forceLogin?: boolean;
  /** Thêm `reason=<...>` (chỉ để hiển thị/debug ở trang login). */
  reason?: string;
}

/**
 * Build URL tương đối `/login?...` cho luồng redirect-do-hết-phiên.
 *
 * Param theo THỨ TỰ CỐ ĐỊNH `force_login, reason, redirect` (test
 * `client.test.ts` assert mảng keys chính xác). Chỉ đính `redirect` khi
 * `currentPath` hợp lệ (internal). Trả `/login` khi không có param.
 */
export function buildLoginRedirect(
  currentPath: string | null | undefined,
  opts: BuildLoginRedirectOptions = {},
): string {
  const params = new URLSearchParams();
  if (opts.forceLogin) params.set("force_login", "true");
  if (opts.reason) params.set("reason", opts.reason);
  if (isValidRedirect(currentPath)) params.set("redirect", currentPath);
  const qs = params.toString();
  return qs ? `/login?${qs}` : "/login";
}
