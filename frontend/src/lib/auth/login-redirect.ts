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
const AUTH_PATHS = [
  "/login",
  "/register",
  "/forgot-password",
  "/reset-password",
  // Trang bootstrap làm mới phiên: nó NHẬN return-url của trang khác, nên bản
  // thân nó không được làm return-url (`?redirect=/session-refresh` = vòng lặp).
  "/session-refresh",
];

/** Ranh giới dải điều khiển ASCII: C0 là 0x00–0x1F, DEL là 0x7F. */
const C0_MAX = 0x1f;
const DEL = 0x7f;

/**
 * Chuỗi có chứa ký tự điều khiển ASCII (C0 hoặc DEL) không.
 *
 * URL parser của WHATWG XOÁ mọi TAB/CR/LF (0x09, 0x0A, 0x0D) TRƯỚC khi phân
 * giải, nên chuỗi ta nhìn thấy khác chuỗi trình duyệt thật sự dùng:
 * `"/<TAB>//evil.com"` lọt qua cả `startsWith("//")` lẫn mọi kiểm tra
 * path-part bên dưới, rồi `new URL(...)` cho ra `https://evil.com/`. Đường tới
 * đây là `?redirect=%2F%09%2F%2Fevil.com` — `URLSearchParams` tự giải mã nên
 * hàm này nhận TAB THẬT, không phải chuỗi `"%09"` (một test viết literal
 * `"%09"` sẽ xanh mà không hề chạm tới lỗ hổng).
 *
 * Quét TOÀN chuỗi (không riêng path-part) vì ranh giới `?`/`#` mà ta tự cắt
 * cũng hết đáng tin một khi trong chuỗi có ký tự sẽ bốc hơi lúc parse. Một
 * return-url hợp lệ không bao giờ chứa ký tự điều khiển THÔ — chúng phải được
 * percent-encode.
 *
 * Duyệt bằng `charCodeAt` thay vì regex literal: viết dải điều khiển vào một
 * regex đòi hoặc ký tự thô trong tệp nguồn (dễ mất khi sao chép, làm tệp thành
 * binary với `grep`), hoặc escape kèm `eslint-disable no-control-regex`. Vòng
 * lặp này không cần cả hai.
 */
function hasControlChar(value: string): boolean {
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    if (code <= C0_MAX || code === DEL) return true;
  }
  return false;
}

export function isValidRedirect(
  url: string | null | undefined,
): url is string {
  if (!url) return false;
  if (hasControlChar(url)) return false;
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

/**
 * Gỡ `_rsc` khỏi một return-url.
 *
 * ⚠️ Bắt buộc dùng `URLSearchParams.delete`, KHÔNG regex: `_rsc` có thể xuất
 * hiện **không kèm `=`** (`?a=1&_rsc`), nên `_rsc=[^&]*` bỏ sót đúng dạng đó và
 * ta mang một tham số nội bộ của RSC vào URL người dùng nhìn thấy.
 *
 * Đặt ở đây — cạnh `isValidRedirect` — vì cả `proxy.ts` (middleware) lẫn
 * `lib/api/server.ts` (Server Component) đều cần. Hai bản sao là hai chỗ sẽ
 * lệch nhau đúng ở khâu lọc return-url.
 */
export function stripRsc(target: string): string {
  try {
    const url = new URL(target, "https://placeholder.invalid");
    url.searchParams.delete("_rsc");
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return target;
  }
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
