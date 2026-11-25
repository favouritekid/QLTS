/**
 * Kiểm CHÍNH cơ chế chặn request rò của test lần xét (`src/test/review-sessions-msw.ts` + `src/test/setup.ts`) — đo ở đúng tầng nó
 * sống (máy chủ giả MSW đang chạy, client axios thật của ứng dụng), không qua spy. Ba ca, mỗi ca canh MỘT bất biến (lượt 3, quyết định
 * điều phối 25-11):
 *  1. request CÓ handler ⇒ handler chạy ĐÚNG 1 lần (bắt `server.listen()` lần hai: MSW gắn thêm listener ⇒ handler chạy hai lần);
 *  2. request rò ⇒ lời gọi THẤT BẠI NHANH với 500 của máy giả (bắt `print.error()` / chiến lược làm request treo hoặc đi ra mạng);
 *  3. request rò ⇒ được GHI LẠI và phép kiểm cuối ca ĐỎ (bắt việc bỏ ghi lại).
 * Ca 2 và 3 tự "nhận" request rò cố ý của mình để phép kiểm cuối ca trong `setup.ts` không làm đỏ nhầm.
 */
import { http, HttpResponse } from "msw"
import { describe, expect, it, vi } from "vitest"

import { api } from "@/lib/api/client"
import { RS } from "@/test/mocks/review-sessions-data"
import { server } from "@/test/mocks/server"

import { chanRequestRo, kiemRequestRoCuoiCa, layRequestRo, xemRequestRo } from "./review-sessions-msw"

chanRequestRo()

const GOC = "/api/admission-config/review-sessions/999999"

describe("hạ tầng test lần xét — chặn request rò (quyết định điều phối 25-11, lượt 3)", () => {
  it("1. request CÓ handler ⇒ handler chạy ĐÚNG 1 lần (máy giả chỉ nghe một lần)", async () => {
    // Biến thể phá: gọi `server.listen()` lần hai ⇒ thêm listener "request" ⇒ handler chạy 2 lần ⇒ ĐỎ.
    let lan = 0
    server.use(
      http.get(`${RS}/999999/co-handler-kiem-co-che`, () => {
        lan += 1
        return HttpResponse.json({})
      }),
    )
    await api.get(`${GOC}/co-handler-kiem-co-che`)
    expect(lan).toBe(1)
  })

  it("2. request rò ⇒ lời gọi THẤT BẠI NHANH với 500 của máy giả (không treo, không ra mạng)", async () => {
    // Biến thể phá: `print.error()` thay cho ném lỗi thường ⇒ MSW ném InternalError ⇒ request treo / bị gửi ra mạng thật ⇒ quá hạn
    // 2 s của ca hoặc không có response 500 ⇒ ĐỎ.
    await expect(api.get(`${GOC}/khong-handler-that-bai-nhanh`)).rejects.toMatchObject({ response: { status: 500 } })
    layRequestRo() // nhận request rò cố ý của ca này — việc GHI LẠI do ca 3 kiểm
  }, 2000)

  it("3. request rò ⇒ được GHI LẠI và phép kiểm cuối ca ĐỎ", async () => {
    // Biến thể phá: bỏ ghi request rò ⇒ không thấy bản ghi ⇒ ĐỎ. Không chờ lời gọi kết thúc — ca này không kiểm việc thất bại.
    const duong = `${GOC}/khong-handler-ghi-lai`
    void api.get(duong).catch(() => undefined)
    await vi.waitFor(() => expect(xemRequestRo().some((r) => r.startsWith("GET ") && r.endsWith(duong))).toBe(true))
    await expect(kiemRequestRoCuoiCa()).rejects.toThrow(/request rò ở ca này/)
  })
})
