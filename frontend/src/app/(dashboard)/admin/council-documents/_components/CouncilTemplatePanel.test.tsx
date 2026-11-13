/**
 * Văn bản Hội đồng — kho mẫu: LỆNH GHI `POST /templates` (hợp đồng thân yêu cầu mục 1, Codex lần 20 câu 2).
 *
 * Máy chủ giả ÁP LUẬT THẬT (`council-luat-may-chu.ts` → `luatTaiMau`): loại ∈ 3 loại; `hieu_luc_tu` là NGÀY KÝ mà mẫu bắt đầu áp cho văn bản
 * ký từ đó (KHÔNG phải ngày tải); ghi chú ≤ 500 ký tự; cùng (loại, ngày hiệu lực) ⇒ 409 DUPLICATE_RESOURCE (không ghi đè), cùng loại
 * KHÁC ngày ⇒ được. Giá trị phân biệt: mẫu quyết định đã có hiệu lực từ 2026-09-08; mẫu mới hiệu lực 2027-01-01 (≠ hôm nay).
 */
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { server } from "@/test/mocks/server"
import { dap, luatTaiMau } from "@/test/mocks/council-luat-may-chu"
import { COUNCIL_DOCUMENTS_PREFIX as P } from "@/lib/api/council-documents"

import { CouncilTemplatePanel } from "./CouncilTemplatePanel"
import { nhanLoaiMau } from "./hien-thi"

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const API = "http://localhost:8000"

interface Mau {
  id: number
  loai: string
  hieu_luc_tu: string
  sha256: string
  kich_thuoc: number
  nguoi_tai_id: number | null
  tai_luc: string
  ghi_chu: string | null
}
let kho: Mau[] = []
let thanGui: Array<{ loai: FormDataEntryValue | null; hieu_luc_tu: FormDataEntryValue | null; ghi_chu: FormDataEntryValue | null }> = []

function dung() {
  server.use(
    http.get(`${API}${P}/templates`, () => HttpResponse.json(kho)),
    http.post(`${API}${P}/templates`, async ({ request }) => {
      const form = await request.formData()
      thanGui.push({ loai: form.get("loai"), hieu_luc_tu: form.get("hieu_luc_tu"), ghi_chu: form.get("ghi_chu") })
      const sai = dap(await luatTaiMau(form, kho))
      if (sai) return sai
      const moi: Mau = {
        id: kho.length + 1,
        loai: String(form.get("loai")),
        hieu_luc_tu: String(form.get("hieu_luc_tu")),
        sha256: "a".repeat(64),
        kich_thuoc: 12,
        nguoi_tai_id: 1,
        tai_luc: "2026-11-13T01:00:00Z",
        ghi_chu: typeof form.get("ghi_chu") === "string" ? String(form.get("ghi_chu")) : null,
      }
      kho.push(moi)
      return HttpResponse.json(moi, { status: 201 })
    }),
  )
}

function ve() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <CouncilTemplatePanel canUpload />
    </QueryClientProvider>,
  )
}

beforeAll(() => {
  // Radix Select trong jsdom: thiếu các hàm con trỏ / cuộn
  const ep = Element.prototype as unknown as Record<string, unknown>
  ep.hasPointerCapture ??= () => false
  ep.setPointerCapture ??= () => undefined
  ep.releasePointerCapture ??= () => undefined
  ep.scrollIntoView ??= () => undefined
})

beforeEach(() => {
  kho = [
    { id: 1, loai: "quyet_dinh", hieu_luc_tu: "2026-09-08", sha256: "b".repeat(64), kich_thuoc: 10, nguoi_tai_id: 1, tai_luc: "2026-09-01T01:00:00Z", ghi_chu: null },
  ]
  thanGui = []
  vi.spyOn(console, "error").mockImplementation(() => undefined)
})

const docx = () => new File(["PK\u0003\u0004 gia"], "mau.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" })

/** Chọn loại qua Select của Radix (jsdom không có PointerEvent ⇒ mở bằng PHÍM Enter; chọn mục bằng click), điền ngày hiệu lực + tệp (+ ghi chú), bấm Tải mẫu lên. */
async function tai(loai: "bien_ban" | "quyet_dinh" | "danh_sach", ngayHieuLuc: string, ghiChu?: string) {
  fireEvent.keyDown(await screen.findByTestId("upload-loai"), { key: "Enter" })
  fireEvent.click(await screen.findByRole("option", { name: nhanLoaiMau(loai) }))
  fireEvent.change(screen.getByTestId("upload-hieu-luc"), { target: { value: ngayHieuLuc } })
  fireEvent.change(screen.getByTestId("upload-file"), { target: { files: [docx()] } })
  if (ghiChu !== undefined) fireEvent.change(screen.getByTestId("upload-ghi-chu"), { target: { value: ghiChu } })
  fireEvent.click(screen.getByTestId("upload-template-submit"))
}

describe("tải mẫu mới — hieu_luc_tu là ngày KÝ áp mẫu (hợp đồng mục 1)", () => {
  it("gửi ĐÚNG ngày người dùng chọn (2027-01-01 — ngày bắt đầu áp cho văn bản KÝ), không phải ngày tải; mẫu xuất hiện trong kho", async () => {
    dung()
    ve()
    await screen.findByTestId("template-list")
    await tai("quyet_dinh", "2027-01-01")
    await waitFor(() => expect(thanGui).toHaveLength(1))
    expect(thanGui[0].hieu_luc_tu).toBe("2027-01-01")
    expect(thanGui[0].hieu_luc_tu).not.toBe(new Date().toISOString().slice(0, 10)) // ≠ ngày tải (hôm nay)
    expect(thanGui[0].loai).toBe("quyet_dinh")
    await waitFor(() => expect(screen.getByTestId("template-row-2").textContent).toContain("01/01/2027"))
  })

  it("trùng (loại, ngày hiệu lực) với mẫu đã có ⇒ 409; hiện câu máy chủ, KHÔNG thêm mẫu; cùng loại KHÁC ngày ⇒ được", async () => {
    dung()
    ve()
    await screen.findByTestId("template-list")
    await tai("quyet_dinh", "2026-09-08") // trùng mẫu id 1
    expect((await screen.findByTestId("upload-template-error")).textContent).toContain("2026-09-08")
    expect(kho).toHaveLength(1)
    fireEvent.change(screen.getByTestId("upload-hieu-luc"), { target: { value: "2027-01-01" } })
    fireEvent.change(screen.getByTestId("upload-file"), { target: { files: [docx()] } })
    fireEvent.click(screen.getByTestId("upload-template-submit"))
    await waitFor(() => expect(kho).toHaveLength(2))
    expect(thanGui.map((t) => t.hieu_luc_tu)).toEqual(["2026-09-08", "2027-01-01"])
  })

  it("KHÁC loại cùng ngày hiệu lực (biên bản 2026-09-08) ⇒ được (khoá trùng là theo CẶP loại + ngày)", async () => {
    dung()
    ve()
    await screen.findByTestId("template-list")
    await tai("bien_ban", "2026-09-08")
    await waitFor(() => expect(kho).toHaveLength(2))
    expect(kho[1].loai).toBe("bien_ban")
  })

  it("ghi chú: 501 ký tự ⇒ 400 hiện câu máy chủ; 500 ký tự ⇒ được", async () => {
    dung()
    ve()
    await screen.findByTestId("template-list")
    await tai("danh_sach", "2027-02-01", "a".repeat(501))
    expect((await screen.findByTestId("upload-template-error")).textContent).toContain("dài quá 500 ký tự")
    expect(kho).toHaveLength(1)
    fireEvent.change(screen.getByTestId("upload-ghi-chu"), { target: { value: "a".repeat(500) } })
    fireEvent.change(screen.getByTestId("upload-file"), { target: { files: [docx()] } })
    fireEvent.click(screen.getByTestId("upload-template-submit"))
    await waitFor(() => expect(kho).toHaveLength(2))
  })
})
