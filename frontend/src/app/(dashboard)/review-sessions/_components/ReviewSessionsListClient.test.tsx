/**
 * GĐ2-B F1 — M1 danh sách lần xét, dựng qua ĐÚNG `page.tsx` (trang chờ `searchParams` trong `<Suspense>`; `resolveServerTree` dựng
 * như máy chủ), máy chủ giả MSW theo hình HĐ4 §3.2, QueryClient mang mặc định thật của ứng dụng.
 *
 * Khoá (thiết kế §6.2 F1):
 *  - bộ lọc trên URL ⇒ đúng tham số E2; URL sai dạng ⇒ không gửi năm / trạng thái, trang 1;
 *  - đổi bộ lọc / lật trang ⇒ ghi lên URL (về trang 1 khi đổi bộ lọc);
 *  - dòng hiện "Lần số N" + năm + đợt + trạng thái (lạ ⇒ chữ máy chủ) + nhãn "Cấu hình đã đổi" theo cờ máy chủ;
 *  - đính chính 2 §1: tải lại lỗi (429) sau khi đã có dữ liệu ⇒ hiện LỖI, KHÔNG vẽ bảng cũ;
 *  - 403 ⇒ câu "Chỉ Admin …", không lộ câu Casbin.
 * Biến thể phá dự kiến ghi ở từng ca. Dữ liệu giả.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  FORBIDDEN_MESSAGE,
  LIST_EMPTY,
  RATE_LIMITED_MESSAGE,
} from "@/lib/review-sessions/messages"
import type { PageSearchParams } from "@/lib/utils/search-params"
import { server } from "@/test/mocks/server"
import { RS, listItemGia, pageGia, runSummaryGia } from "@/test/mocks/review-sessions-data"
import { renderApp } from "@/test/review-sessions-render"
import { resolveServerTree } from "@/test/server-component"

import ReviewSessionsPage from "../page"

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/review-sessions",
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

afterEach(() => server.resetHandlers())

async function moTrang(sp: PageSearchParams = {}) {
  return renderApp(await resolveServerTree(ReviewSessionsPage({ searchParams: Promise.resolve(sp) })))
}

/** E2 giả: `tra(lần gọi thứ n)`; trả danh sách URL đã gọi (đọc tham số). */
function mayChuE2(tra: (lan: number) => Response): URL[] {
  const urls: URL[] = []
  server.use(
    http.get(RS, ({ request }) => {
      urls.push(new URL(request.url))
      return tra(urls.length)
    }),
  )
  return urls
}

describe("M1 — bộ lọc trên URL ⇒ đúng tham số E2", () => {
  it("?nam=2026&trang-thai=cancelled&trang=2 ⇒ academic_year, status, page, page_size gửi đúng", async () => {
    // Biến thể phá: trang bỏ `searchParams` (truyền bộ lọc rỗng) ⇒ thiếu academic_year / status ⇒ ĐỎ.
    const urls = mayChuE2(() => HttpResponse.json(pageGia([listItemGia()], { page: 2, total: 21, total_pages: 2 })))
    await moTrang({ nam: "2026", "trang-thai": "cancelled", trang: "2" })
    await screen.findByTestId("ds-lan-xet")
    expect(Object.fromEntries(urls[0].searchParams)).toEqual({
      academic_year: "2026",
      status: "cancelled",
      page: "2",
      page_size: "20",
    })
  })

  it("URL sai dạng (nam=abc, trạng thái lạ, trang=0) ⇒ không gửi năm / trạng thái, trang 1 (không để máy chủ 422)", async () => {
    const urls = mayChuE2(() => HttpResponse.json(pageGia([listItemGia()])))
    await moTrang({ nam: "abc", "trang-thai": "locked", trang: "0" })
    await screen.findByTestId("ds-lan-xet")
    expect(Object.fromEntries(urls[0].searchParams)).toEqual({ page: "1", page_size: "20" })
  })

  it("đổi bộ lọc ⇒ ghi lên URL, về trang 1", async () => {
    mayChuE2(() => HttpResponse.json(pageGia([listItemGia()], { page: 3, total: 41, total_pages: 3 })))
    await moTrang({ nam: "2026", trang: "3" })
    await screen.findByTestId("ds-lan-xet")
    fireEvent.change(screen.getByTestId("loc-trang-thai"), { target: { value: "cancelled" } })
    expect(replace).toHaveBeenLastCalledWith("/review-sessions?nam=2026&trang-thai=cancelled")
    fireEvent.change(screen.getByTestId("loc-nam"), { target: { value: "" } })
    expect(replace).toHaveBeenLastCalledWith("/review-sessions")
    const namNay = String(new Date().getFullYear())
    fireEvent.change(screen.getByTestId("loc-nam"), { target: { value: namNay } })
    expect(replace).toHaveBeenLastCalledWith(`/review-sessions?nam=${namNay}`)
  })

  it("lật trang giữ bộ lọc; trang 1 không ghi lên URL", async () => {
    mayChuE2(() => HttpResponse.json(pageGia([listItemGia()], { page: 2, total: 45, total_pages: 3 })))
    await moTrang({ nam: "2026", trang: "2" })
    expect(await screen.findByTestId("trang-hien-tai")).toHaveTextContent("Trang 2 / 3")
    fireEvent.click(screen.getByTestId("trang-sau"))
    expect(replace).toHaveBeenLastCalledWith("/review-sessions?nam=2026&trang=3")
    fireEvent.click(screen.getByTestId("trang-truoc"))
    expect(replace).toHaveBeenLastCalledWith("/review-sessions?nam=2026")
  })
})

describe("M1 — dòng danh sách (hiện nguyên số / cờ máy chủ)", () => {
  it("hiện 'Lần số N' + năm + đợt + trạng thái + số sàn + người tạo; liên kết sang chi tiết", async () => {
    mayChuE2(() => HttpResponse.json(pageGia([listItemGia()])))
    await moTrang()
    const dong = await screen.findByTestId("lan-xet-3")
    const o = within(dong)
    expect(o.getByText("2026")).toBeInTheDocument()
    expect(o.getByTestId("lan-xet-3-mo")).toHaveTextContent("Lần số 3")
    expect(o.getByTestId("lan-xet-3-mo")).toHaveAttribute("href", "/review-sessions/3")
    expect(dong).toHaveTextContent("Đợt 2 (D2)")
    expect(o.getByTestId("lan-xet-3-trang-thai")).toHaveTextContent("Nháp")
    expect(dong).toHaveTextContent("14")
    expect(dong).toHaveTextContent("Người dùng #1")
    expect(o.getByTestId("lan-xet-3-luot")).toHaveTextContent("Đạt — máy đề xuất 120")
  })

  it("trạng thái lạ (GĐ2-C) ⇒ hiện nguyên chữ máy chủ", async () => {
    mayChuE2(() => HttpResponse.json(pageGia([listItemGia({ status: "trang_thai_moi" })])))
    await moTrang()
    expect(await screen.findByTestId("lan-xet-3-trang-thai")).toHaveTextContent("trang_thai_moi")
  })

  it("nhãn 'Cấu hình đã đổi' CHỈ theo cờ máy chủ; chưa có lượt ⇒ 'Chưa chạy'", async () => {
    mayChuE2(() =>
      HttpResponse.json(
        pageGia([
          listItemGia({ id: 3, latest_run: runSummaryGia({ config_changed_since_run: true }) }),
          listItemGia({ id: 4, seq_no: 2, latest_run: runSummaryGia({ config_changed_since_run: false }) }),
          listItemGia({ id: 5, seq_no: 1, latest_run: null, floor_count: 0 }),
        ]),
      ),
    )
    await moTrang()
    expect(await screen.findByTestId("lan-xet-3-luot-cau-hinh-doi")).toHaveTextContent("Cấu hình đã đổi")
    expect(screen.queryByTestId("lan-xet-4-luot-cau-hinh-doi")).toBeNull()
    expect(screen.getByTestId("lan-xet-5-luot")).toHaveTextContent("Chưa chạy")
  })

  it("rỗng ⇒ câu 'Chưa có lần xét nào cho bộ lọc này.'", async () => {
    mayChuE2(() => HttpResponse.json(pageGia([])))
    await moTrang({ nam: "2030" })
    expect(await screen.findByTestId("ds-lan-xet-rong")).toHaveTextContent(LIST_EMPTY)
  })
})

describe("M1 — lỗi", () => {
  it("đính chính 2 §1: tải lại bị 429 sau khi đã có dữ liệu ⇒ hiện LỖI, KHÔNG vẽ bảng cũ", async () => {
    // Biến thể phá: thành phần đọc `data` trước `isError` (vẽ bảng khi còn dữ liệu cũ) ⇒ ĐỎ.
    mayChuE2((lan) =>
      lan === 1
        ? HttpResponse.json(pageGia([listItemGia()]))
        : HttpResponse.json({ detail: "Rate limit exceeded" }, { status: 429 }),
    )
    await moTrang()
    await screen.findByTestId("ds-lan-xet")
    fireEvent.click(screen.getByTestId("ds-lan-xet-tai-lai"))
    expect(await screen.findByTestId("ds-lan-xet-loi")).toHaveTextContent(RATE_LIMITED_MESSAGE)
    expect(screen.queryByTestId("ds-lan-xet")).toBeNull()
    expect(screen.queryByTestId("lan-xet-3")).toBeNull()
  })

  it("403 ⇒ 'Chỉ Admin …', không lộ câu Casbin; nút 'Tạo lần xét' vẫn hiện (máy chủ là chốt)", async () => {
    mayChuE2(() => HttpResponse.json({ detail: "Permission denied by policy", error_code: "PERMISSION_DENIED" }, { status: 403 }))
    await moTrang()
    const loi = await screen.findByTestId("ds-lan-xet-loi")
    expect(loi).toHaveTextContent(FORBIDDEN_MESSAGE)
    expect(loi).not.toHaveTextContent("Permission denied")
    expect(screen.getByTestId("nut-tao-lan-xet")).toBeInTheDocument()
  })

  it("đang tải ⇒ không có bảng; xong ⇒ có bảng (không mượn dữ liệu nào khác)", async () => {
    mayChuE2(() => HttpResponse.json(pageGia([listItemGia()])))
    await moTrang()
    expect(screen.getByTestId("ds-lan-xet-dang-tai")).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId("ds-lan-xet")).toBeInTheDocument())
  })
})
