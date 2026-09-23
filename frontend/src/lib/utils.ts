// src/lib/utils.ts
/**
 * Utility functions for the application
 */
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { API_BASE_URL } from "@/lib/api/client";

/**
 * Merge class names with Tailwind CSS
 * Combines clsx and tailwind-merge for optimal class name handling
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Sanitize CSS color code to prevent XSS attacks
 * Only allows valid CSS color formats: hex, rgb, rgba, hsl, hsla, named colors
 *
 * ⚠️ SECURITY: Never pass unsanitized user input directly to style attributes
 *
 * @param colorCode - The color code from backend
 * @param fallback - Fallback color if invalid (default: "#6B7280" gray-500)
 * @returns Safe CSS color string
 */
export function sanitizeColorCode(
  colorCode: string | null | undefined,
  fallback: string = "#6B7280"
): string {
  if (!colorCode || typeof colorCode !== "string") {
    return fallback;
  }

  const trimmed = colorCode.trim();

  // Hex colors: #RGB, #RRGGBB, #RRGGBBAA
  if (/^#(?:[0-9A-Fa-f]{3}){1,2}(?:[0-9A-Fa-f]{2})?$/.test(trimmed)) {
    return trimmed;
  }

  // RGB/RGBA: rgb(r, g, b) or rgba(r, g, b, a)
  if (/^rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(?:,\s*(?:0|1|0?\.\d+)\s*)?\)$/.test(trimmed)) {
    return trimmed;
  }

  // HSL/HSLA: hsl(h, s%, l%) or hsla(h, s%, l%, a)
  if (/^hsla?\(\s*\d{1,3}\s*,\s*\d{1,3}%\s*,\s*\d{1,3}%\s*(?:,\s*(?:0|1|0?\.\d+)\s*)?\)$/.test(trimmed)) {
    return trimmed;
  }

  // Named CSS colors (common subset for performance)
  const namedColors = new Set([
    "transparent", "inherit", "currentcolor",
    "black", "white", "red", "green", "blue", "yellow", "orange", "purple",
    "pink", "gray", "grey", "cyan", "magenta", "lime", "maroon", "navy",
    "olive", "teal", "aqua", "fuchsia", "silver"
  ]);

  if (namedColors.has(trimmed.toLowerCase())) {
    return trimmed.toLowerCase();
  }

  // Invalid color - return fallback
  return fallback;
}

/** Nền ảo để phân giải đường dẫn tương đối — KHÔNG phụ thuộc `window`. */
const PLACEHOLDER_ORIGIN = "https://placeholder.invalid";

/** Ranh giới dải điều khiển ASCII: C0 là 0x00–0x1F, DEL là 0x7F. */
const C0_MAX = 0x1f;
const DEL = 0x7f;

/**
 * Chuỗi có chứa ký tự điều khiển ASCII thô không.
 *
 * URL parser của WHATWG **XOÁ** mọi TAB/CR/LF (0x09/0x0A/0x0D) TRƯỚC khi phân
 * giải, nên chuỗi ta nhìn thấy khác chuỗi trình duyệt thật sự dùng:
 * `"/<TAB>/evil.example"` đi qua mọi phép kiểm tiền tố rồi biến thành
 * `"//evil.example"` lúc parse — tức đổi origin.
 *
 * Duyệt bằng `charCodeAt` thay vì regex: viết dải điều khiển vào regex literal
 * đòi hoặc ký tự thô trong tệp nguồn (dễ mất khi sao chép), hoặc escape kèm
 * `eslint-disable no-control-regex`.
 */
function hasControlChar(value: string): boolean {
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    if (code <= C0_MAX || code === DEL) return true;
  }
  return false;
}

/**
 * Đầu vào có phải đường NỘI BỘ không — quyết định từ CHÍNH CHUỖI VÀO.
 *
 * 🔴 KHÔNG suy phân loại từ kết quả parse. Bản đầu hỏi
 * `resolved.origin === PLACEHOLDER_ORIGIN` để suy ra "tương đối"; phép ấy sai
 * vì nền ảo là một origin THẬT với URL parser, nên một đầu vào trỏ ĐÍCH DANH
 * tới chính nó cũng thoả. Đo (node v20.20.0): `//placeholder.invalid/x` và
 * `https://placeholder.invalid/x` đều cho origin `https://placeholder.invalid`
 * ⇒ bị xếp nhầm là "tương đối". Biến thể viết HOA và kèm cổng mặc định cũng
 * trùng khít sau khi URL parser chuẩn hoá host.
 *
 * Nền ảo có nhiệm vụ DUY NHẤT là cho `new URL` một gốc để phân giải đường dẫn
 * tương đối. Nó không được mang thêm nghĩa "đây là đường nội bộ" — chọn tên
 * miền nào cũng vậy, vì tên nào cũng gõ vào đầu vào được.
 *
 * Hai điều kiện, và chỉ hai:
 *   - bắt đầu bằng `/` — loại mọi scheme tường minh (scheme phải mở đầu bằng
 *     chữ cái) và mọi đường dẫn trần;
 *   - KHÔNG bắt đầu bằng `//` — `//host/x` là protocol-relative, tức ĐỔI origin.
 *
 * Ký tự điều khiển và `\` đã bị chặn TRƯỚC khi gọi hàm này, nên chuỗi ở đây
 * không còn thứ sẽ "bốc hơi" lúc parse và làm hai phép nhìn thấy hai chuỗi
 * khác nhau.
 */
function laDuongNoiBo(raw: string): boolean {
  return raw.startsWith("/") && !raw.startsWith("//");
}

/**
 * Chuẩn hoá một URL do máy chủ cung cấp thành ĐÍCH ĐIỀU HƯỚNG an toàn, hoặc
 * `null` nếu không an toàn.
 *
 * 🔴 VÌ SAO TRẢ ĐÍCH CHỨ KHÔNG TRẢ `boolean`:
 * một vị từ `boolean` chỉ nói "chuỗi này ổn", rồi nơi gọi lại điều hướng bằng
 * **chuỗi gốc**. Đó đúng là khe "kiểm một chuỗi, điều hướng chuỗi khác" —
 * cùng loại lỗi đã đẻ ra open redirect ở đường cứu phiên. Ở đây phép kiểm và
 * phép điều hướng buộc phải dùng **một giá trị duy nhất**: cái hàm này trả về.
 *
 * Bản trước (`isSafeUrl`) hỏng ở HAI chỗ độc lập:
 *   1. `url.trim()` chỉ cắt HAI ĐẦU, nên TAB/CR/LF **nội bộ** sống sót tới
 *      `startsWith('/')` rồi bốc hơi lúc parse ⇒ `/<TAB>/evil.example` thoát
 *      site. Dấu `\` cũng vậy: WHATWG coi `\` như `/` trong scheme đặc biệt.
 *   2. so **TIỀN TỐ CHUỖI** chứ không so **ORIGIN**, và không có ranh giới ⇒
 *      `https://<origin>.evil.com` và `https://<origin>@evil.com` đều lọt.
 *
 * ⚠️ Dot-segment — HAI ca khác hẳn nhau, đừng gộp:
 *   - với **chuỗi GỐC** thì `/..//x` vô hại: trình duyệt rút gọn `..` trong
 *     phần path và **giữ nguyên host**;
 *   - nhưng hàm này trả bản **ĐÃ CHUẨN HOÁ**, mà `URL.pathname` đã bỏ
 *     dot-segment ⇒ `/..//x` thành `//x`, một URL protocol-relative.
 * Vì thế: chuẩn hoá xong mà tụt xuống `//` ⇒ **CHẶN** (chặn cuối bên dưới);
 * chuẩn hoá xong vẫn là đường nội bộ (`/a/../b` → `/b`) ⇒ **CHO QUA**.
 * `utils.test.ts` khoá CẢ HAI chiều, để bản vá sau không siết nhầm thành
 * "cấm mọi dấu chấm" — luật đó vừa chặn oan, vừa không giải quyết `%2e`.
 *
 * Không đọc `window`: nền phân giải là hằng, nên server và client cho **cùng**
 * kết quả — tránh lệch hydrate ở các `<Link>` render phía máy chủ.
 *
 * 🔒 HỢP ĐỒNG ĐẦU VÀO — đúng MỘT dạng được nhận, ngoài ra trả `null`:
 *   chuỗi bắt đầu bằng `/`, KHÔNG bắt đầu bằng `//`, và sau chuẩn hoá vẫn là
 *   đường nội bộ.
 *
 * Bị TỪ CHỐI, không ngoại lệ:
 *   - **mọi URL tuyệt đối** — kể cả trùng app origin, kể cả trùng API origin;
 *   - đường dẫn trần không có `/` đầu (`leads`, `?q=x`, `#x`, `./x`, `../x`),
 *     dù `new URL` phân giải được chúng thành đường nội bộ;
 *   - `//host/x` (protocol-relative) và mọi scheme khác `http`/`https`.
 *
 * ⚖️ Trước đây hàm còn một nhánh nhận URL tuyệt đối khi origin trùng origin
 * của API. Nhánh ấy đã GỠ. Hai lý do kỹ thuật, đọc được từ chính mã và test:
 *   1. **fail-closed** — chỉ một hình dạng đầu vào hợp lệ thì không còn ngách
 *      nào để một phép phân loại sai lọt qua;
 *   2. **xoá phụ thuộc vào cấu hình origin** — hành vi của guard không còn đổi
 *      theo `NEXT_PUBLIC_API_URL`. Trước đây, API origin trùng hay khác app
 *      origin cho ra hai hành vi khác nhau ở cùng một đầu vào; nay chỉ còn một.
 *      `utils.test.ts` (biến RỖNG) và `utils.api-origin.test.ts` (biến khác
 *      rỗng) chạy cùng hợp đồng — đó là phép đo của lý do thứ hai.
 *
 * @returns đường dẫn tương đối (`/path?query#hash`) để điều hướng, hoặc `null`.
 */
export function resolveSafeUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (hasControlChar(url)) return null;

  const trimmed = url.trim();
  if (!trimmed) return null;
  // `\` tương đương `/` với scheme đặc biệt ⇒ `/\evil.example` thành `//evil…`.
  if (trimmed.includes("\\")) return null;

  // 🔒 CỔNG HÌNH DẠNG ĐẦU VÀO — **không phải** cổng an toàn duy nhất.
  //
  // Chỉ đường nội bộ `/…` được đi tiếp. Phép này loại: mọi URL tuyệt đối
  // (scheme phải mở đầu bằng chữ cái, nên không bao giờ khớp `/`), mọi
  // `//host` protocol-relative, và mọi đường dẫn trần. Đặt TRƯỚC `new URL` để
  // hàm không bao giờ phải suy ngược từ kết quả parse — nguồn của lỗi phân
  // loại nền-ảo đã chữa.
  //
  // ⚠️ NÓ KHÔNG GIỮ BẤT BIẾN "đích không rời site". Bất biến ấy do chặn cuối
  // bên dưới giữ, và hai phép canh HAI THỜI ĐIỂM khác nhau nên không thay nhau
  // được: phép này nhìn chuỗi GỐC, chặn cuối nhìn chuỗi ĐÃ CHUẨN HOÁ. `/..//x`
  // đi qua trót lọt ở đây (bắt đầu `/`, không phải `//`) rồi mới tụt thành
  // `//x` khi `URL.pathname` bỏ dot-segment. Gỡ chặn cuối ⇒ **6 ca đỏ** (đo
  // bằng đột biến) — đừng đọc dòng này thành "gỡ dòng kia là vô hại".
  if (!laDuongNoiBo(trimmed)) return null;

  let resolved: URL;
  try {
    resolved = new URL(trimmed, PLACEHOLDER_ORIGIN);
  } catch {
    return null;
  }

  // Chặn `javascript:`, `data:`, `vbscript:`, `mailto:`… bằng ALLOWLIST scheme,
  // không bằng danh sách cấm — danh sách cấm luôn thiếu một mục.
  if (resolved.protocol !== "http:" && resolved.protocol !== "https:") {
    return null;
  }

  const target = `${resolved.pathname}${resolved.search}${resolved.hash}`;

  // 🔴 CHẶN CUỐI — đừng bỏ.
  //
  // `resolved.pathname` đã BỎ dot-segment, nên `/..//evil.example` ra
  // `//evil.example`: một URL **protocol-relative**. Trả chuỗi đó về cho nơi
  // gọi là TỰ TAY tạo ra lỗ hổng mà hàm này sinh ra để chặn — chuỗi gốc thì
  // vô hại (trình duyệt phân giải `/..//x` thành cùng origin), nhưng bản ĐÃ
  // CHUẨN HOÁ thì không.
  //
  // Bộ ca `utils.test.ts` bắt được đúng chỗ này khi bản vá đầu tiên thiếu nó.
  //
  // ⭐ ĐO 22-09 — DÒNG NÀY LÀ LỚP CHỊU LỰC, không phải lớp trang trí. Hàm chỉ
  // trả `pathname+search+hash`, tức origin của chuỗi vào bị VỨT BỎ; nên thứ
  // thật sự giữ bất biến "đích không rời site" là đúng phép kiểm dưới đây, chứ
  // không phải các lớp lọc ở trên. Gỡ nó ⇒ 6 ca đỏ (đo bằng đột biến).
  //
  // Vẫn cần dù `laDuongNoiBo` đã đòi `/` và cấm `//` trên chuỗi GỐC: phép đó
  // chạy TRƯỚC chuẩn hoá, còn `/..//x` chỉ tụt thành `//x` SAU khi `URL.pathname`
  // bỏ dot-segment. Hai phép canh hai thời điểm khác nhau — không thay nhau được.
  if (!target.startsWith("/") || target.startsWith("//")) return null;

  return target;
}

/**
 * Vị từ tương thích ngược cho mã cũ.
 *
 * ⚠️ Mã MỚI hãy dùng `resolveSafeUrl` và điều hướng bằng ĐÚNG giá trị nó trả
 * về. Gọi hàm này rồi điều hướng bằng chuỗi gốc là tái tạo lại đúng lỗ hổng.
 */
export function isSafeUrl(url: string): boolean {
  return resolveSafeUrl(url) !== null;
}

/**
 * Validate a file path from API for document viewing.
 * Only allows relative paths (no protocol, no traversal).
 */
export function isSafeFilePath(filePath: string): boolean {
  if (!filePath) return false;
  // Block any protocol handler
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(filePath)) return false;
  // Block protocol-relative URLs
  if (filePath.startsWith('//')) return false;
  // Block path traversal
  if (filePath.includes('..')) return false;
  return true;
}

/**
 * Convert relative avatar URL to absolute URL with backend base URL
 * This is necessary because Next.js dev server runs on different port than FastAPI
 * @param avatarUrl - The avatar URL from backend (can be relative or absolute)
 * @returns Absolute URL pointing to backend server or empty string
 */
export function getAvatarUrl(avatarUrl?: string | null): string | undefined {
  if (!avatarUrl) return undefined;

  // If already absolute URL, return as is
  if (avatarUrl.startsWith("http://") || avatarUrl.startsWith("https://")) {
    return avatarUrl;
  }

  // Convert relative URL to absolute using backend base URL
  // Remove leading slash if present to avoid double slashes
  const cleanPath = avatarUrl.startsWith("/") ? avatarUrl.slice(1) : avatarUrl;
  return `${API_BASE_URL}/${cleanPath}`;
}
