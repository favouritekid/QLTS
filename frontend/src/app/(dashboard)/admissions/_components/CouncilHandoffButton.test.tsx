/**
 * Nút "Dựng văn bản Hội đồng" ở thanh hàng loạt của "Hồ sơ tuyển sinh" (đặc tả 5.1, bản 2 mục 5.1).
 * Khoá: hiện theo CỜ máy chủ; chỉ ĐẨY id + năm sang store RIÊNG rồi chuyển trang; hỏi trước khi ghi đè danh sách khác.
 * Năm học CHUNG lấy từ `academic_year` của CÁC DÒNG đang chọn (máy chủ `083a428d`) — không từ bộ lọc: nhiều năm khác nhau
 * hoặc có dòng chưa rõ năm ⇒ khoá và nói lý do.
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { server } from "@/test/mocks/server"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"
import { NO_COUNCIL_PERMISSIONS } from "@/hooks/admin/useCouncilDocuments"
import { useCouncilSelectionStore } from "@/lib/stores/council-selection.store"

import { CouncilHandoffButton, BUILD_DOCUMENT_PATH, commonYearOf, type SelectedProfile } from "./CouncilHandoffButton"

const { push } = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: push }) }))

const API = "http://localhost:8000"
const quyen = (co: Record<string, boolean>) =>
  server.use(http.get(`${API}${P}/quyen`, () => HttpResponse.json({ permissions: { ...NO_COUNCIL_PERMISSIONS, ...co } })))

/** Các dòng đang chọn: mỗi id kèm năm học (mặc định 2026). */
const hs = (ids: number[], nam: number | null | undefined = 2026): SelectedProfile[] => ids.map((id) => ({ id, academic_year: nam }))

function ve(props: { profile: SelectedProfile[]; disabled?: boolean }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <CouncilHandoffButton {...props} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  push.mockClear()
  useCouncilSelectionStore.getState().reset()
})

describe("CouncilHandoffButton", () => {
  it("thiếu cờ kiem_truoc (máy chủ chưa trả) ⇒ không hiện nút", async () => {
    quyen({ tao_bo: true })
    const { container } = ve({ profile: hs([1]) })
    await new Promise((r) => setTimeout(r, 50))
    expect(container.querySelector("[data-testid='dung-van-ban-hoi-dong']")).toBeNull()
  })

  it("thiếu cờ tim_ho_so (luồng chưa đủ route) ⇒ không hiện nút", async () => {
    quyen({ tao_bo: true, kiem_truoc: true })
    const { container } = ve({ profile: hs([1]) })
    await new Promise((r) => setTimeout(r, 50))
    expect(container.querySelector("[data-testid='dung-van-ban-hoi-dong']")).toBeNull()
  })

  it("thiếu cờ tao_bo ⇒ không hiện nút (theo cờ, không theo vai)", async () => {
    quyen({ kiem_truoc: true, tim_ho_so: true })
    const { container } = ve({ profile: hs([1]) })
    await new Promise((r) => setTimeout(r, 50))
    expect(container.querySelector("[data-testid='dung-van-ban-hoi-dong']")).toBeNull()
  })

  it("bấm ⇒ ĐẨY năm + id sang store Hội đồng rồi chuyển trang /admin/council-documents/moi", async () => {
    quyen({ tao_bo: true, kiem_truoc: true, tim_ho_so: true })
    ve({ profile: hs([5, 3, 5]) })
    fireEvent.click(await screen.findByTestId("dung-van-ban-hoi-dong"))
    expect(push).toHaveBeenCalledWith(BUILD_DOCUMENT_PATH)
    expect(BUILD_DOCUMENT_PATH).toBe("/admin/council-documents/moi")
    expect(useCouncilSelectionStore.getState().academicYear).toBe(2026)
    expect(useCouncilSelectionStore.getState().profileId).toEqual([5, 3]) // bỏ trùng, giữ thứ tự
  })

  it("không chọn hồ sơ nào ⇒ nút khoá", async () => {
    quyen({ tao_bo: true, kiem_truoc: true, tim_ho_so: true })
    ve({ profile: [] })
    expect(((await screen.findByTestId("dung-van-ban-hoi-dong")) as HTMLButtonElement).disabled).toBe(true)
  })

  it("năm học = năm CỦA DÒNG (không phải 2026 mặc định): mọi dòng 2025 ⇒ đẩy sang store với năm 2025", async () => {
    quyen({ tao_bo: true, kiem_truoc: true, tim_ho_so: true })
    ve({ profile: hs([4, 6], 2025) })
    fireEvent.click(await screen.findByTestId("dung-van-ban-hoi-dong"))
    expect(useCouncilSelectionStore.getState().academicYear).toBe(2025)
    expect(useCouncilSelectionStore.getState().profileId).toEqual([4, 6])
  })

  it("các dòng chọn thuộc NHIỀU năm học ⇒ nút khoá, nói lý do; bấm không làm gì (không lấy năm của dòng đầu)", async () => {
    quyen({ tao_bo: true, kiem_truoc: true, tim_ho_so: true })
    ve({ profile: [{ id: 1, academic_year: 2026 }, { id: 2, academic_year: 2025 }] })
    const nut = (await screen.findByTestId("dung-van-ban-hoi-dong")) as HTMLButtonElement
    expect(nut.disabled).toBe(true)
    expect(nut.getAttribute("title")).toBe("Các hồ sơ đang chọn thuộc nhiều năm học — chọn lại cho cùng một năm học")
    fireEvent.click(nut)
    expect(push).not.toHaveBeenCalled()
    expect(useCouncilSelectionStore.getState().profileId).toEqual([])
  })

  it.each([
    ["null (máy chủ trả hồ sơ chưa có năm)", null],
    ["vắng khoá (máy chủ cũ)", undefined],
  ])("có dòng chưa rõ năm học — %s ⇒ nút khoá, nói lý do; không đoán năm", async (_ten, nam) => {
    quyen({ tao_bo: true, kiem_truoc: true, tim_ho_so: true })
    ve({ profile: [{ id: 1, academic_year: 2026 }, { id: 2, academic_year: nam }] })
    const nut = (await screen.findByTestId("dung-van-ban-hoi-dong")) as HTMLButtonElement
    expect(nut.disabled).toBe(true)
    expect(nut.getAttribute("title")).toBe("Chưa biết năm học của một số hồ sơ đang chọn")
    fireEvent.click(nut)
    expect(push).not.toHaveBeenCalled()
  })

  it("trang Hội đồng đang giữ danh sách KHÁC ⇒ hỏi 'Thay danh sách đang chọn?'; giữ cũ ⇒ không đổi; đồng ý ⇒ thay", async () => {
    quyen({ tao_bo: true, kiem_truoc: true, tim_ho_so: true })
    useCouncilSelectionStore.getState().replace(2026, [9])
    ve({ profile: hs([1, 2]) })
    fireEvent.click(await screen.findByTestId("dung-van-ban-hoi-dong"))
    expect(await screen.findByTestId("thay-danh-sach-dialog")).toBeTruthy()
    expect(push).not.toHaveBeenCalled()
    expect(useCouncilSelectionStore.getState().profileId).toEqual([9])

    fireEvent.click(screen.getByText("Giữ danh sách cũ"))
    await waitFor(() => expect(screen.queryByTestId("thay-danh-sach-dialog")).toBeNull())
    expect(useCouncilSelectionStore.getState().profileId).toEqual([9])
    expect(push).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId("dung-van-ban-hoi-dong"))
    fireEvent.click(await screen.findByTestId("thay-danh-sach-dong-y"))
    await waitFor(() => expect(push).toHaveBeenCalledWith(BUILD_DOCUMENT_PATH))
    expect(useCouncilSelectionStore.getState().profileId).toEqual([1, 2])
  })

  it("danh sách đang giữ TRÙNG danh sách mới ⇒ không hỏi, chuyển trang luôn", async () => {
    quyen({ tao_bo: true, kiem_truoc: true, tim_ho_so: true })
    useCouncilSelectionStore.getState().replace(2026, [2, 1])
    ve({ profile: hs([1, 2]) })
    fireEvent.click(await screen.findByTestId("dung-van-ban-hoi-dong"))
    expect(screen.queryByTestId("thay-danh-sach-dialog")).toBeNull()
    expect(push).toHaveBeenCalledWith(BUILD_DOCUMENT_PATH)
  })

  it("không dùng chung lựa chọn với màn Hồ sơ tuyển sinh: nút KHÔNG chạm vào rowSelection / storage", async () => {
    quyen({ tao_bo: true, kiem_truoc: true, tim_ho_so: true })
    ve({ profile: hs([1]) })
    fireEvent.click(await screen.findByTestId("dung-van-ban-hoi-dong"))
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).toBe("{}")
  })
})

describe("namChungCua — năm học chung của các dòng đang chọn", () => {
  it("không chọn dòng nào ⇒ trong", () => {
    expect(commonYearOf([])).toEqual({ kind: "trong" })
  })
  it("mọi dòng cùng một năm ⇒ năm ấy (kể cả khi chọn nhiều dòng)", () => {
    expect(commonYearOf(hs([1, 2, 3], 2025))).toEqual({ kind: "chung", year: 2025 })
  })
  it("nhiều năm khác nhau ⇒ nhieu_nam — KHÔNG lấy năm của dòng đầu hay dòng cuối", () => {
    expect(commonYearOf([{ id: 1, academic_year: 2025 }, { id: 2, academic_year: 2026 }])).toEqual({ kind: "nhieu_nam" })
    expect(commonYearOf([{ id: 1, academic_year: 2026 }, { id: 2, academic_year: 2025 }])).toEqual({ kind: "nhieu_nam" })
  })
  it("có dòng null / vắng năm ⇒ chua_ro — kể cả khi các dòng còn lại cùng một năm", () => {
    expect(commonYearOf([{ id: 1, academic_year: 2026 }, { id: 2, academic_year: null }])).toEqual({ kind: "chua_ro" })
    expect(commonYearOf([{ id: 1 }, { id: 2, academic_year: 2026 }])).toEqual({ kind: "chua_ro" })
  })
})
