// src/lib/auth/sr-marker.ts
/**
 * Marker `_sr` — bộ đếm vòng của đường cứu phiên.
 *
 * Dùng chung cho cả EDGE (`proxy.ts`, middleware) lẫn BROWSER
 * (`SessionRefreshBootstrap.tsx`, `"use client"`). Vì vậy module này PHẢI
 * runtime-agnostic: chỉ `URL`/`URLSearchParams`/`String` — KHÔNG `next/server`,
 * không `window`, không API riêng của Node. Cùng lý do và cùng tiền lệ với
 * `lib/auth/login-redirect.ts`.
 *
 * 🔴 Không được để bootstrap import thẳng `proxy.ts`: tệp đó import
 * `next/server`, nên một lần import từ client kéo cả mã middleware vào bundle
 * trình duyệt.
 *
 * Và không được chép lại bốn hàm này ở phía client: nắp chỉ có nghĩa khi HAI
 * phía đọc-ghi CÙNG một cách. Một bản sao lệch `Math.min` là một nắp đóng sai
 * chỗ — hoặc sớm (người dùng bị đá về `/login` khi phiên vẫn cứu được), hoặc
 * không bao giờ.
 */

// Dùng CHUNG vị từ an toàn với tầng canonical. `login-redirect.ts` cũng
// runtime-agnostic (chỉ URL/URLSearchParams/String) nên import này không kéo
// `next/server` hay `window` vào bundle client, và không tạo vòng import:
// `login-redirect.ts` không import ngược lại module này.
import { SAFE_PATH, isInternalPath } from "./login-redirect";

/**
 * Đi qua vòng cứu phiên tối đa mấy lần trước khi bắt đăng nhập lại.
 *
 * `2` là con số nhỏ nhất còn cho phép một lần thử lại hợp lệ (vòng 0 → 1), và
 * đủ để một endpoint SSR luôn trả 401 không quay mãi.
 */
export const SR_MAX = 2;

/**
 * Nền ảo dùng để phân giải đường dẫn tương đối — PHẢI trùng với nền mà
 * `login-redirect.ts` dùng, nếu không thì tầng lọc và tầng điều hướng lại
 * chuẩn hoá khác nhau, đúng cái khe đã đẻ ra open redirect.
 */
const PLACEHOLDER_ORIGIN = "https://placeholder.invalid";

/** Đếm số vòng đã đi qua `/session-refresh`, đọc TỪ TRONG target. */
export function parseSr(target: string): number {
  try {
    const url = new URL(target, "https://placeholder.invalid");
    const all = url.searchParams.getAll("_sr");
    // Khoá trùng ⇒ không tin được cái nào ⇒ coi như chưa đi vòng nào. Đây là
    // phía an toàn: nắp vẫn đóng ở vòng sau, còn tin nhầm thì mất nắp.
    if (all.length !== 1) return 0;
    const n = Number(all[0]);
    if (!Number.isInteger(n) || n < 0) return 0;
    return Math.min(n, SR_MAX);
  } catch {
    return 0;
  }
}

/**
 * CHẶN CUỐI cho `withSr`.
 *
 * `url.pathname` đã BỎ DOT-SEGMENT, nên `/..//evil.example` ra `//evil.example`
 * — URL protocol-relative, `location.replace` sẽ rời khỏi site. Tầng canonical
 * (`normalizeInternalTarget`) đã chặn từ đầu; đây là lớp thứ hai cho trường hợp
 * một chỗ nào đó quên gọi guard.
 *
 * ⚠️ Fallback PHẢI GIỮ `_sr`. Trả trơ `/` là mất bộ đếm vòng: vòng sau
 * `parseSr` đọc ra 0, nắp `SR_MAX` không bao giờ đóng, và ta đổi một lỗ hổng
 * lấy đúng cái vòng lặp đang phải chữa.
 */
function clampToSafePathKeepingSr(path: string, n: number): string {
  if (isInternalPath(path)) return path;
  return `${SAFE_PATH}?_sr=${Math.min(n, SR_MAX)}`;
}

/** Ghi lại số vòng vào target — `delete` rồi `set`, không `append`. */
export function withSr(target: string, n: number): string {
  try {
    const url = new URL(target, PLACEHOLDER_ORIGIN);
    url.searchParams.delete("_sr");
    url.searchParams.set("_sr", String(Math.min(n, SR_MAX)));
    return clampToSafePathKeepingSr(
      `${url.pathname}${url.search}${url.hash}`,
      n,
    );
  } catch {
    return clampToSafePathKeepingSr(target, n);
  }
}

/**
 * Gỡ marker `_sr` — dùng khi rời khỏi vòng cứu phiên.
 *
 * Cùng khuôn `new URL(...).pathname` nên cùng lỗ; và đầu ra của nó cũng đi
 * thẳng vào `location.replace` ở `SessionRefreshBootstrap`. Ở đây rơi về `/`
 * trơn là đúng: hàm này vốn có nhiệm vụ gỡ `_sr`.
 */
export function stripSr(target: string): string {
  try {
    const url = new URL(target, PLACEHOLDER_ORIGIN);
    url.searchParams.delete("_sr");
    const result = `${url.pathname}${url.search}${url.hash}`;
    return isInternalPath(result) ? result : SAFE_PATH;
  } catch {
    return isInternalPath(target) ? target : SAFE_PATH;
  }
}
