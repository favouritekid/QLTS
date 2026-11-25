/**
 * CHỈ cho test GĐ2-B lần xét (F0–F4) dùng máy chủ giả MSW — chặn "request rò" (lượt 3, quyết định điều phối 25-11, cách (a)).
 *
 * Vì sao: đối chiếu CI F4 lượt 1 (`fe-f4\KET-QUA-DOI-CHIEU-CI-FE-F4-2026-11-24.md`): một request KHÔNG có handler đi qua chiến lược "warn"
 * ra mạng thật ⇒ tiến trình worker vitest sập (`uv__stream_destroy`). Lượt 2 (`fe-f4\KET-QUA-DOI-CHIEU-CI-FE-F4-LAN2-2026-11-25.md`) đo
 * ba lỗi của cách cũ — xác nhận bằng đọc mã nguồn:
 *  - gọi `server.listen()` lần hai ⇒ MSW gắn THÊM một listener "request" ⇒ mọi request đi qua handler HAI lần
 *    (msw 2.12.7 `SetupServerCommonApi.listen()` → `init()`);
 *  - `print.error()` ném `InternalError` ⇒ MSW ném lại ⇒ request không được trả lời rồi bị gửi ra mạng thật
 *    (`@mswjs/interceptors` 0.40.0 `XMLHttpRequestController`: chưa trả lời ⇒ gửi như thường);
 *  - `afterEach` kiểm đăng ký SAU CÙNG ⇒ với `sequence.hooks` "stack" (mặc định vitest 4.1.8) nó chạy TRƯỚC; khi nó ném, mọi `afterEach`
 *    còn lại (dọn cây React, `resetHandlers`) bị bỏ qua ⇒ cây của ca đỏ còn lại làm nhiễm ca sau.
 *
 * Cách làm — một nguồn, `server.listen()` chỉ ở `src/test/setup.ts` (ĐÚNG MỘT lần, `onUnhandledRequest: xuLyRequestKhongHandler`):
 *  - tệp CHƯA bật ⇒ y như chiến lược "warn" cũ (bỏ qua tệp tĩnh thông dụng, in cảnh báo MSW, request đi tiếp);
 *  - tệp ĐÃ bật (`chanRequestRo()` ở cấp tệp) ⇒ GHI LẠI request rồi ném `Error` THƯỜNG ⇒ máy giả trả 500 cho request ấy: lời gọi thất bại
 *    ngay, không treo, không ra mạng (`@mswjs/interceptors` `handleRequest` → `createServerErrorResponse`);
 *  - `afterEach` của `setup.ts` (tệp đã bật): dọn cây React → chờ request đang bay → `kiemRequestRoCuoiCa()` → `resetHandlers` (luôn chạy)
 *    ⇒ ca phát ra request rò ĐỎ, và ca đỏ không để lại cây / handler cho ca sau.
 * Mỗi tệp test là một ngữ cảnh module riêng (vitest cô lập theo tệp) ⇒ cờ chỉ áp cho tệp gọi `chanRequestRo()`.
 * Ca kiểm chính cơ chế: `src/test/review-sessions-msw.test.ts`; test tĩnh khoá danh sách tệp phải gọi: `review-sessions.static.test.ts`.
 */
import { isCommonAssetRequest, type UnhandledRequestCallback } from "msw"
import { afterAll, beforeAll, expect } from "vitest"

/** Hẹn giờ THẬT, lấy lúc nạp tệp (trước mọi ca) — ca bật `vi.useFakeTimers()` không làm treo bước chờ cuối ca. */
const henGioThat = globalThis.setTimeout.bind(globalThis)

let dangChan = false
const requestRo: string[] = []

/** Tệp hiện tại đã bật chặn request rò chưa (`setup.ts` đọc để chọn cách dọn / kiểm cuối ca). */
export function dangChanRequestRo(): boolean {
  return dangChan
}

/** Xem (KHÔNG xoá) danh sách request rò đã ghi. */
export function xemRequestRo(): string[] {
  return [...requestRo]
}

/** Lấy và XOÁ danh sách request rò đã ghi (ca kiểm cơ chế dùng để "nhận" request rò cố ý của nó). */
export function layRequestRo(): string[] {
  return requestRo.splice(0)
}

/** `onUnhandledRequest` DUY NHẤT của máy chủ giả (truyền ở `setup.ts`). */
export const xuLyRequestKhongHandler: UnhandledRequestCallback = (request, print) => {
  if (!dangChan) {
    // Giữ nguyên hành vi chiến lược "warn" cũ cho mọi tệp chưa bật (msw 2.12.7 `onUnhandledRequest`: chiến lược dựng sẵn bỏ qua tệp tĩnh).
    if (!isCommonAssetRequest(request)) print.warning()
    return
  }
  requestRo.push(`${request.method} ${request.url}`)
  // Lỗi THƯỜNG, KHÔNG `print.error()` (ném InternalError ⇒ request treo rồi ra mạng thật).
  throw new Error(`[test lần xét] request rò — không có handler máy chủ giả: ${request.method} ${request.url}`)
}

/** Chờ vài lượt hàng đợi để request đã gửi kịp tới máy giả và được ghi lại (đường XHR → MSW đi bằng microtask; 3 lượt là dư — chưa đo). */
async function choRequestDangBay(): Promise<void> {
  for (let i = 0; i < 3; i += 1) {
    await new Promise<void>((xong) => henGioThat(() => xong(), 0))
  }
}

/** Phép kiểm cuối ca (tệp đã bật): chờ request đang bay rồi đòi danh sách request rò RỖNG; danh sách luôn được xoá, đỏ hay xanh. */
export async function kiemRequestRoCuoiCa(): Promise<void> {
  await choRequestDangBay()
  expect(layRequestRo(), "request rò ở ca này — thêm handler máy chủ giả (không nới onUnhandledRequest)").toEqual([])
}

/** Gọi MỘT lần ở cấp tệp (sau các `import`): bật chặn request rò cho tệp này. KHÔNG gọi `server.listen()` — `setup.ts` đã gọi đúng một lần. */
export function chanRequestRo(): void {
  beforeAll(() => {
    dangChan = true
  })
  afterAll(() => {
    dangChan = false
  })
}
