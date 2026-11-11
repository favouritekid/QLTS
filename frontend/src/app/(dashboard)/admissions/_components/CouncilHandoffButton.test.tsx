/**
 * Nút "Dựng văn bản Hội đồng" ở thanh hàng loạt của "Hồ sơ tuyển sinh" (đặc tả 5.1, bản 2 mục 5.1).
 * Khoá: hiện theo CỜ máy chủ; chỉ ĐẨY id + năm sang store RIÊNG rồi chuyển trang; hỏi trước khi ghi đè danh sách khác;
 * khoá khi chưa có năm học (lệch đặc tả có chủ ý — DTO nhẹ không có academic_year).
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { server } from "@/test/mocks/server"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"
import { NO_COUNCIL_PERMISSIONS } from "@/hooks/admin/useCouncilDocuments"
import { useCouncilSelectionStore } from "@/lib/stores/council-selection.store"

import { CouncilHandoffButton, DUONG_DAN_DUNG_VAN_BAN } from "./CouncilHandoffButton"

const { push } = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: push }) }))

const API = "http://localhost:8000"
const quyen = (co: Record<string, boolean>) =>
  server.use(http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: { ...NO_COUNCIL_PERMISSIONS, ...co } })))

function ve(props: { namHoc: number | undefined; idHoSo: number[]; disabled?: boolean }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <CouncilHandoffButton {...props} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  push.mockClear()
  useCouncilSelectionStore.getState().lamSach()
})

describe("CouncilHandoffButton", () => {
  it("thiếu cờ kiem_truoc (máy chủ chưa trả) ⇒ không hiện nút", async () => {
    quyen({ tao_bo: true })
    const { container } = ve({ namHoc: 2026, idHoSo: [1] })
    await new Promise((r) => setTimeout(r, 50))
    expect(container.querySelector("[data-testid='dung-van-ban-hoi-dong']")).toBeNull()
  })

  it("thiếu cờ tim_ho_so (luồng chưa đủ route) ⇒ không hiện nút", async () => {
    quyen({ tao_bo: true, kiem_truoc: true })
    const { container } = ve({ namHoc: 2026, idHoSo: [1] })
    await new Promise((r) => setTimeout(r, 50))
    expect(container.querySelector("[data-testid='dung-van-ban-hoi-dong']")).toBeNull()
  })

  it("thiếu cờ tao_bo ⇒ không hiện nút (theo cờ, không theo vai)", async () => {
    quyen({ kiem_truoc: true, tim_ho_so: true })
    const { container } = ve({ namHoc: 2026, idHoSo: [1] })
    await new Promise((r) => setTimeout(r, 50))
    expect(container.querySelector("[data-testid='dung-van-ban-hoi-dong']")).toBeNull()
  })

  it("bấm ⇒ ĐẨY năm + id sang store Hội đồng rồi chuyển trang /admin/council-documents/moi", async () => {
    quyen({ tao_bo: true, kiem_truoc: true, tim_ho_so: true })
    ve({ namHoc: 2026, idHoSo: [5, 3, 5] })
    fireEvent.click(await screen.findByTestId("dung-van-ban-hoi-dong"))
    expect(push).toHaveBeenCalledWith(DUONG_DAN_DUNG_VAN_BAN)
    expect(DUONG_DAN_DUNG_VAN_BAN).toBe("/admin/council-documents/moi")
    expect(useCouncilSelectionStore.getState().namHoc).toBe(2026)
    expect(useCouncilSelectionStore.getState().idHoSo).toEqual([5, 3]) // bỏ trùng, giữ thứ tự
  })

  it("không chọn hồ sơ nào ⇒ nút khoá", async () => {
    quyen({ tao_bo: true, kiem_truoc: true, tim_ho_so: true })
    ve({ namHoc: 2026, idHoSo: [] })
    expect(((await screen.findByTestId("dung-van-ban-hoi-dong")) as HTMLButtonElement).disabled).toBe(true)
  })

  it("'Tất cả năm' (không có năm học) ⇒ nút khoá, nói cần chọn năm học ở bộ lọc; bấm không làm gì", async () => {
    quyen({ tao_bo: true, kiem_truoc: true, tim_ho_so: true })
    ve({ namHoc: undefined, idHoSo: [1, 2] })
    const nut = (await screen.findByTestId("dung-van-ban-hoi-dong")) as HTMLButtonElement
    expect(nut.disabled).toBe(true)
    expect(nut.getAttribute("title")).toBe("Chọn một năm học ở bộ lọc trước")
    fireEvent.click(nut)
    expect(push).not.toHaveBeenCalled()
    expect(useCouncilSelectionStore.getState().idHoSo).toEqual([])
  })

  it("trang Hội đồng đang giữ danh sách KHÁC ⇒ hỏi 'Thay danh sách đang chọn?'; giữ cũ ⇒ không đổi; đồng ý ⇒ thay", async () => {
    quyen({ tao_bo: true, kiem_truoc: true, tim_ho_so: true })
    useCouncilSelectionStore.getState().thayThe(2026, [9])
    ve({ namHoc: 2026, idHoSo: [1, 2] })
    fireEvent.click(await screen.findByTestId("dung-van-ban-hoi-dong"))
    expect(await screen.findByTestId("thay-danh-sach-dialog")).toBeTruthy()
    expect(push).not.toHaveBeenCalled()
    expect(useCouncilSelectionStore.getState().idHoSo).toEqual([9])

    fireEvent.click(screen.getByText("Giữ danh sách cũ"))
    await waitFor(() => expect(screen.queryByTestId("thay-danh-sach-dialog")).toBeNull())
    expect(useCouncilSelectionStore.getState().idHoSo).toEqual([9])
    expect(push).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId("dung-van-ban-hoi-dong"))
    fireEvent.click(await screen.findByTestId("thay-danh-sach-dong-y"))
    await waitFor(() => expect(push).toHaveBeenCalledWith(DUONG_DAN_DUNG_VAN_BAN))
    expect(useCouncilSelectionStore.getState().idHoSo).toEqual([1, 2])
  })

  it("danh sách đang giữ TRÙNG danh sách mới ⇒ không hỏi, chuyển trang luôn", async () => {
    quyen({ tao_bo: true, kiem_truoc: true, tim_ho_so: true })
    useCouncilSelectionStore.getState().thayThe(2026, [2, 1])
    ve({ namHoc: 2026, idHoSo: [1, 2] })
    fireEvent.click(await screen.findByTestId("dung-van-ban-hoi-dong"))
    expect(screen.queryByTestId("thay-danh-sach-dialog")).toBeNull()
    expect(push).toHaveBeenCalledWith(DUONG_DAN_DUNG_VAN_BAN)
  })

  it("không dùng chung lựa chọn với màn Hồ sơ tuyển sinh: nút KHÔNG chạm vào rowSelection / storage", async () => {
    quyen({ tao_bo: true, kiem_truoc: true, tim_ho_so: true })
    ve({ namHoc: 2026, idHoSo: [1] })
    fireEvent.click(await screen.findByTestId("dung-van-ban-hoi-dong"))
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).toBe("{}")
  })
})
