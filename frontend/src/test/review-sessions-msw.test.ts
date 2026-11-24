/**
 * Kiểm CHÍNH cơ chế chặn request rò của test lần xét (`src/test/review-sessions-msw.ts`) — đo ở đúng tầng nó sống (máy chủ giả MSW đang
 * chạy), không qua spy: một request KHÔNG có handler phải (1) bị GHI LẠI bởi chiến lược "error" của tệp và (2) bị CHẶN (lời gọi thất bại,
 * không đi ra mạng). Nếu chiến lược vẫn là "warn" của setup chung, danh sách ghi lại rỗng ⇒ ĐỎ.
 * Ca tự "nhận" request rò cố ý của nó (`layRequestRo`) để `afterEach` của cơ chế không làm đỏ nhầm.
 */
import { describe, expect, it } from "vitest"

import { api } from "@/lib/api/client"

import { chanRequestRo, layRequestRo } from "./review-sessions-msw"

chanRequestRo()

describe("hạ tầng test lần xét — chặn request rò (quyết định điều phối 25-11)", () => {
  it("request không có handler ⇒ bị GHI LẠI và bị CHẶN (lời gọi thất bại, không ra mạng)", async () => {
    // Biến thể phá: chiến lược không ghi / không ném (như "warn") ⇒ danh sách rỗng ⇒ ĐỎ.
    const duong = "/api/admission-config/review-sessions/999999/khong-co-handler-kiem-co-che"
    await expect(api.get(duong)).rejects.toBeDefined()
    const ro = layRequestRo()
    expect(ro.some((r) => r.startsWith("GET ") && r.endsWith(duong))).toBe(true)
  })
})
