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
 * `router.push`/`new URL(x, origin)` không thể đổi origin từ query.
 *
 * Cũng reject các public auth path (/login, /register, ...) làm return-url —
 * tránh vòng lặp redirect về chính trang đăng nhập.
 *
 * 🔴 BẢN TRƯỚC NÓI SAI một vế, và đó chính là lỗ hổng:
 *   «path đã chắc chắn internal (bắt đầu `/`, không `//`, không protocol)».
 * Câu đó chỉ đúng với CHUỖI THÔ. Nhưng mọi người tiêu thụ — `withSr`,
 * `stripSr`, `stripRsc` — đều đi qua `new URL(x, nền).pathname`, tức CHUẨN HOÁ
 * dot-segment TRƯỚC khi điều hướng. `/..//evil.example` qua được hết phép lọc
 * thô rồi chuẩn hoá thành `//evil.example` — URL protocol-relative, rời khỏi
 * site. `%2f` bị chặn nhưng `%2e` thì không, mà WHATWG URL coi `%2e` là `.`
 * khi bỏ dot-segment, nên `/%2e%2e//evil.example` là cùng lỗ viết khác đi.
 *
 * Cách đóng: CHUẨN HOÁ TRƯỚC RỒI MỚI LỌC — xem `normalizeInternalTarget`.
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

/**
 * Nền ảo để phân giải đường dẫn tương đối.
 *
 * Phải là MỘT hằng dùng chung: `withSr`/`stripSr`/`stripRsc` và hàm lọc này
 * bắt buộc chuẩn hoá bằng CÙNG một phép, nếu không thì cái lọc và cái điều
 * hướng lại nhìn thấy hai chuỗi khác nhau — đúng cái khe đã đẻ ra lỗ hổng.
 */
const PLACEHOLDER_ORIGIN = "https://placeholder.invalid";

/**
 * Đường rơi về khi một hàm chuẩn hoá phát hiện đầu ra đã thoát khỏi site.
 *
 * Chọn `/` chứ không phải chuỗi rỗng: chuỗi rỗng đưa vào `location.replace`
 * nghĩa là "tải lại chính trang hiện tại", tức có thể quay lại đúng vòng lặp
 * đang phải chữa.
 */
export const SAFE_PATH = "/";

/**
 * Một đường dẫn (đã chuẩn hoá hay chưa) có còn là đường NỘI BỘ không.
 *
 * Export vì `sr-marker.ts` cần ĐÚNG định nghĩa này cho chặn cuối của nó. Hai
 * bản sao của một vị từ an toàn là hai bản sẽ lệch nhau, và chỗ lệch nằm đúng
 * ở ca không ai nghĩ tới — xem `feedback_single_source_of_truth_shared_helper`.
 */
export function isInternalPath(path: string): boolean {
  if (!path.startsWith("/")) return false;
  // `//host` là URL protocol-relative: trình duyệt hiểu là ĐỔI ORIGIN.
  if (path.startsWith("//")) return false;
  return true;
}

/**
 * Chuẩn hoá return-url về ĐÚNG dạng cuối cùng trình duyệt sẽ dùng, rồi kiểm
 * LẠI trên bản đã chuẩn hoá. Trả `null` nếu không an toàn.
 *
 * Hai lượt kiểm, KHÔNG phải một:
 *
 *  1. trên chuỗi THÔ — bắt ký tự điều khiển và `%2f`/`%5c`, những thứ sẽ BỐC
 *     HƠI hoặc đổi nghĩa khi parse nên sau chuẩn hoá không còn thấy được;
 *  2. trên chuỗi ĐÃ CHUẨN HOÁ — bắt `//` sinh ra do bỏ dot-segment, và bắt
 *     auth path giấu sau `..` (vd `/a/../login`).
 *
 * ⚠️ KHÔNG hạ xuống thành "cấm mọi dấu chấm": `/a/../b` chuẩn hoá ra `/b`,
 * hoàn toàn nội bộ và hợp lệ. Một luật thô như thế vừa chặn nhầm đường lành,
 * vừa KHÔNG giải quyết `%2e` — tức tệ hơn về cả hai phía.
 */
export function normalizeInternalTarget(
  url: string | null | undefined,
): string | null {
  if (!url) return null;
  if (hasControlChar(url)) return null;
  if (!isInternalPath(url)) return null;

  // --- Lượt 1: trên chuỗi THÔ ------------------------------------------
  const rawPath = url.split(/[?#]/, 1)[0];
  if (rawPath.includes(":")) return null; // protocol-like
  if (rawPath.includes("\\")) return null; // backslash
  if (/%2f|%5c/i.test(rawPath)) return null; // encoded slash/backslash

  // --- Chuẩn hoá bằng CHÍNH phép mà tầng điều hướng sẽ dùng --------------
  let normalized: string;
  try {
    const u = new URL(url, PLACEHOLDER_ORIGIN);
    normalized = `${u.pathname}${u.search}${u.hash}`;
  } catch {
    return null;
  }

  // --- Lượt 2: trên chuỗi ĐÃ CHUẨN HOÁ ----------------------------------
  if (!isInternalPath(normalized)) return null;
  const normalizedPath = normalized.split(/[?#]/, 1)[0];
  if (normalizedPath.includes(":")) return null;
  if (normalizedPath.includes("\\")) return null;
  // Không return-url về trang auth (tránh loop /login?redirect=/login).
  if (AUTH_PATHS.some((p) => normalizedPath === p || normalizedPath.startsWith(`${p}/`)))
    return null;

  return normalized;
}

export function isValidRedirect(
  url: string | null | undefined,
): url is string {
  return normalizeInternalTarget(url) !== null;
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
    const url = new URL(target, PLACEHOLDER_ORIGIN);
    url.searchParams.delete("_rsc");
    const result = `${url.pathname}${url.search}${url.hash}`;
    // CHẶN CUỐI. `url.pathname` đã bỏ dot-segment, nên `/..//evil.example` ra
    // `//evil.example`. Hàm này cùng khuôn với `withSr`/`stripSr` và đầu ra của
    // nó cũng đi thẳng vào redirect, nên nó cũng phải có chặn cuối — vá một
    // nhánh mà bỏ ba nhánh anh em là tái tạo lỗ ở chỗ khác.
    return isInternalPath(result) ? result : SAFE_PATH;
  } catch {
    return isInternalPath(target) ? target : SAFE_PATH;
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
