/**
 * CHỈ cho test GĐ2-B lần xét (F0–F4) dùng máy chủ giả MSW — chặn "request rò".
 *
 * Vì sao: đối chiếu CI F4 (`fe-f4\KET-QUA-DOI-CHIEU-CI-FE-F4-2026-11-24.md`): một request KHÔNG có handler (E9 ở các ca M5 cũ) đi qua
 * chiến lược chung `onUnhandledRequest: "warn"` (`src/test/setup.ts`) ra mạng thật ⇒ tiến trình worker vitest sập
 * (`uv__stream_destroy`) ⇒ 8–10 ca không chạy ở MỌI lượt. Quyết định điều phối 25-11: tệp test lần xét đặt chiến lược "error"; KHÔNG nới lại
 * thành "warn".
 *
 * `chanRequestRo()` — gọi MỘT lần ở cấp tệp (sau các `import`):
 *  - `beforeAll`: đặt lại `onUnhandledRequest` của máy chủ giả cho tệp này theo chiến lược "error" — in câu lỗi MSW (`print.error()`) rồi NÉM
 *    ⇒ MSW KHÔNG cho request đi tiếp ra mạng (máy giả trả lỗi cho request ấy);
 *  - ghi lại từng request rò; `afterEach` làm ĐỎ ca có request rò — ca đi qua dữ liệu máy chủ thì phải có handler.
 * Mỗi tệp test là một ngữ cảnh module riêng (vitest cô lập theo tệp) ⇒ thay đổi chỉ áp cho tệp gọi hàm này.
 * Ca kiểm chính cơ chế này: `src/test/review-sessions-msw.test.ts`; test tĩnh khoá danh sách tệp phải gọi: `review-sessions.static.test.ts`.
 */
import { afterEach, beforeAll, expect } from "vitest"

import { server } from "@/test/mocks/server"

const requestRo: string[] = []

/** Lấy và XOÁ danh sách request rò đã ghi (ca kiểm cơ chế dùng để "nhận" request rò cố ý của nó). */
export function layRequestRo(): string[] {
  return requestRo.splice(0)
}

export function chanRequestRo(): void {
  beforeAll(() => {
    server.listen({
      onUnhandledRequest(request, print) {
        requestRo.push(`${request.method} ${request.url}`)
        print.error()
        throw new Error(`[test lần xét] request rò — không có handler máy chủ giả: ${request.method} ${request.url}`)
      },
    })
  })
  afterEach(() => {
    expect(layRequestRo(), "request rò ở ca này — thêm handler máy chủ giả (không nới onUnhandledRequest)").toEqual([])
  })
}
