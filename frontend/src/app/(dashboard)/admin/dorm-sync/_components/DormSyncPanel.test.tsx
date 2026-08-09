/**
 * Màn đồng bộ ký túc xá — thin client.
 *
 * 🔴 Bất biến trung tâm: giao diện tin `next_action`, `can_apply`, `outcome`,
 * `ledger_saved` — những thứ backend đã tính. Suy lại bất kỳ thứ nào trong số
 * đó là dựng một định nghĩa thứ hai, và bản lệch sẽ là bản người dùng NHÌN
 * THẤY.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  act,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AxiosError } from "axios"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useDormSync } from "@/hooks/admin/useDormSync"

import { DormSyncPanel } from "./DormSyncPanel"

const { mockGet, mockPost } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
}))

vi.mock("@/lib/api/client", () => ({
  api: { get: mockGet, post: mockPost },
}))

const { mockHandleApiError, mockToastError } = vi.hoisted(() => ({
  mockHandleApiError: vi.fn(),
  mockToastError: vi.fn(),
}))

vi.mock("sonner", () => ({
  toast: { error: mockToastError, success: vi.fn(), info: vi.fn() },
}))

vi.mock("@/lib/error-handler", () => ({
  handleApiError: mockHandleApiError,
}))

function boc(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const BOI_CANH = { open_academic_years: [2026, 2025], default_academic_year: 2026 }

function preview(ghiDe: Record<string, unknown> = {}) {
  return {
    academic_year: 2026,
    source_count: 566,
    can_apply: true,
    blocked_reason: null,
    counts: {
      khong_ro_gioi_tinh: 1,
      chua_chot_nganh: 0,
      chua_ro_trinh_do: 2,
      ho_so_dang_xet: 0,
      khong_co_so_lien_he: 3,
      co_so_phu: 98,
      so_bi_bo_vi_qua_dai: 0,
    },
    warnings: [],
    source_hash: "a".repeat(64),
    target_fingerprint: "c".repeat(32),
    snapshot_hash: "b".repeat(64),
    snapshot_version: 1,
    preview_token: "phieu-hop-le",
    expires_at: 2_000_000,
    ...ghiDe,
  }
}

function loiChan(operationStatus: string, nextAction: string) {
  const loi = new AxiosError("409")
  loi.response = {
    data: {
      detail: "Câu chữ này KHÔNG được dùng để rẽ nhánh.",
      error_code: "DORM_SYNC_OPERATION_BLOCKED",
      operation_status: operationStatus,
      next_action: nextAction,
    },
    status: 409,
    statusText: "Conflict",
    headers: {},
    config: {} as never,
  }
  return loi
}

let canhBaoConsole: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  vi.clearAllMocks()
  mockGet.mockResolvedValue({ data: BOI_CANH })
  // React cảnh báo key trùng qua `console.error`; giữ lại để ca key soi được.
  canhBaoConsole = vi.spyOn(console, "error").mockImplementation(() => {})
})

afterEach(() => {
  canhBaoConsole.mockRestore()
})

/**
 * Bấm Ghi = mở hộp xác nhận RỒI bấm nút xác nhận.
 *
 * 🔴 Click đầu KHÔNG được gửi request. Đây là thao tác hạ cờ đủ-điều-kiện của
 * cả một khoá học và không có đường lùi.
 */
async function bamGhi() {
  await userEvent.click(screen.getByTestId("nut-ghi"))
  await userEvent.click(await screen.findByRole("button", { name: "Ghi" }))
}

async function xemTruocXong(du_lieu = preview()) {
  mockPost.mockResolvedValueOnce({ data: du_lieu })
  boc(<DormSyncPanel now={() => 1_000_000_000} />)
  await userEvent.click(await screen.findByTestId("nut-xem-truoc"))
  return screen.findByTestId("ket-qua-xem-truoc")
}

describe("payload request chính xác", () => {
  it("xem trước gửi ĐÚNG { academic_year }", async () => {
    await xemTruocXong()

    expect(mockPost).toHaveBeenCalledWith("/api/v2/admin/dorm-sync/preview", {
      academic_year: 2026,
    })
  })

  it("ghi gửi ĐÚNG { preview_token } — không kèm năm học hay operation_id", async () => {
    // Backend khai `extra="forbid"`: gửi kèm `academic_year` sẽ nhận 422, và
    // đó là chủ ý — năm học đã nằm trong phiếu do server ký.
    await xemTruocXong()
    mockPost.mockResolvedValueOnce({
      data: {
        operation_id: "op-1",
        academic_year: 2026,
        outcome: "completed",
        message: "Đã đồng bộ xong.",
        ktx_run_id: 42,
        upserted: 566,
        blocked: 0,
        deactivated: 0,
        ledger_saved: true,
      },
    })

    await bamGhi()

    await waitFor(() =>
      expect(mockPost).toHaveBeenLastCalledWith("/api/v2/admin/dorm-sync/apply", {
        preview_token: "phieu-hop-le",
      }),
    )
  })
})

describe("ba next_action", () => {
  it.each([
    ["running", "wait"],
    ["outcome_unknown", "manual_reconcile"],
  ])(
    "%s → %s: khoá MỌI thao tác, không mời thử lại",
    async (trangThai, hanhDong) => {
      await xemTruocXong()
      mockPost.mockRejectedValueOnce(loiChan(trangThai, hanhDong))

      await bamGhi()

      await screen.findByTestId(`chan-${hanhDong}`)
      // Nút Xem trước cũng bị khoá — `wait` nghĩa là chờ, không phải làm lại.
      expect(screen.getByTestId("nut-xem-truoc")).toBeDisabled()
      // Phiếu cũ đã bị xoá nên không còn nút Ghi để bấm nhầm.
      expect(screen.queryByTestId("nut-ghi")).not.toBeInTheDocument()
    },
  )

  it("failed → preview_again: CHO phép xem trước lại", async () => {
    await xemTruocXong()
    mockPost.mockRejectedValueOnce(loiChan("failed", "preview_again"))

    await bamGhi()

    await screen.findByTestId("chan-preview_again")
    expect(screen.getByTestId("nut-xem-truoc")).toBeEnabled()
  })

  it("manual_reconcile hiện cảnh báo đối soát nổi bật", async () => {
    await xemTruocXong()
    mockPost.mockRejectedValueOnce(loiChan("outcome_unknown", "manual_reconcile"))

    await bamGhi()

    expect(await screen.findByTestId("canh-bao-doi-soat")).toBeInTheDocument()
  })

  it("KHÔNG suy trạng thái từ operation_status hay câu detail", async () => {
    // 🔴 `operation_status` nói "running" nhưng `next_action` nói
    // "preview_again". Giao diện phải nghe `next_action`.
    //
    // Tổ hợp này không xảy ra ở backend hôm nay — và đó chính là lý do ca này
    // tồn tại: nó chứng minh nguồn quyết định là trường nào, chứ không phải
    // chứng minh hai trường luôn khớp.
    await xemTruocXong()
    mockPost.mockRejectedValueOnce(loiChan("running", "preview_again"))

    await bamGhi()

    await screen.findByTestId("chan-preview_again")
    expect(screen.getByTestId("nut-xem-truoc")).toBeEnabled()
  })
})

describe("ba outcome", () => {
  it.each(["completed", "failed", "outcome_unknown"])(
    "%s hiện đúng khối kết quả kèm mã lượt",
    async (outcome) => {
      await xemTruocXong()
      mockPost.mockResolvedValueOnce({
        data: {
          operation_id: "op-1",
          academic_year: 2026,
          outcome,
          message: "thông điệp từ backend",
          ktx_run_id: 42,
          upserted: 5,
          blocked: 0,
          deactivated: outcome === "completed" ? 2 : 0,
          ledger_saved: true,
        },
      })

      await bamGhi()

      await screen.findByTestId(`ket-qua-${outcome}`)
      // Mã lượt phải luôn có — nó là thứ duy nhất để đối soát tay.
      expect(screen.getByTestId("ma-luot")).toHaveTextContent("42")
      expect(screen.queryByTestId("so-chua-ghi")).not.toBeInTheDocument()
    },
  )

  it("phản hồi ghi có TRƯỜNG LẠ thì từ chối, không nhận bừa", async () => {
    // 🔴 `.strict()`. Backend khai `extra="forbid"` cho cùng hình dạng này;
    // để frontend nhận thêm trường là mở lại đúng khoảng lệch bên kia vừa
    // đóng — và nó lệch âm thầm, vì một trường thừa không làm gì hỏng cho tới
    // lúc ai đó đọc nhầm nó.
    await xemTruocXong()
    mockPost.mockResolvedValueOnce({
      data: {
        operation_id: "op-1",
        academic_year: 2026,
        outcome: "completed",
        message: "Đã đồng bộ xong.",
        ktx_run_id: 42,
        upserted: 5,
        blocked: 0,
        deactivated: 2,
        ledger_saved: true,
        preview_token: "PHIEU-KHONG-DUOC-QUAY-LAI",
      },
    })

    await bamGhi()

    // Không có khối kết quả nào được dựng từ một phản hồi sai hình dạng.
    await waitFor(() =>
      expect(screen.queryByTestId("ket-qua-completed")).not.toBeInTheDocument(),
    )
  })

  it("ledger_saved=false hiện cảnh báo mà KHÔNG mời bấm lại", async () => {
    // Hệ KTX ĐÃ đổi; chỉ sổ đối soát là thiếu.
    await xemTruocXong()
    mockPost.mockResolvedValueOnce({
      data: {
        operation_id: "op-1",
        academic_year: 2026,
        outcome: "completed",
        message: "Đã đồng bộ xong.",
        ktx_run_id: 42,
        upserted: 5,
        blocked: 0,
        deactivated: 2,
        ledger_saved: false,
      },
    })

    await bamGhi()

    expect(await screen.findByTestId("so-chua-ghi")).toBeInTheDocument()
    expect(screen.getByTestId("ma-luot")).toHaveTextContent("42")
    expect(screen.queryByTestId("nut-ghi")).not.toBeInTheDocument()
  })
})

describe("phiếu và năm học", () => {
  it("phiếu HẾT HẠN thì khoá nút Ghi", async () => {
    // ⚠️ Đọc `expires_at` TRỰC TIẾP, không giải mã `exp` trong phiếu.
    mockPost.mockResolvedValueOnce({ data: preview({ expires_at: 1_500 }) })
    // Đồng hồ giả: 2000 giây > 1500 giây.
    boc(<DormSyncPanel now={() => 2_000_000} />)
    await userEvent.click(await screen.findByTestId("nut-xem-truoc"))

    await screen.findByTestId("ket-qua-xem-truoc")
    expect(screen.getByTestId("nut-ghi")).toBeDisabled()
  })

  it("phiếu CÒN HẠN thì mở nút Ghi — vế đảo", async () => {
    mockPost.mockResolvedValueOnce({ data: preview({ expires_at: 3_000 }) })
    boc(<DormSyncPanel now={() => 2_000_000} />)
    await userEvent.click(await screen.findByTestId("nut-xem-truoc"))

    await screen.findByTestId("ket-qua-xem-truoc")
    expect(screen.getByTestId("nut-ghi")).toBeEnabled()
  })

  it("đổi năm học thì XOÁ phiếu cũ", async () => {
    // Phiếu ký cho năm A mà bấm Ghi ở màn hình đang hiện năm B là người bấm
    // duyệt một thứ, hệ thống ghi một thứ khác.
    await xemTruocXong()
    expect(screen.getByTestId("nut-ghi")).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByTestId("chon-nam"), "2025")

    expect(screen.queryByTestId("ket-qua-xem-truoc")).not.toBeInTheDocument()
  })

  it("can_apply=false dù CÒN hồ sơ ở nguồn — tin backend, không tự suy", async () => {
    // 🔴 Ca tách `can_apply` khỏi `source_count`.
    //
    // Backend còn chặn vì những lý do frontend KHÔNG thấy: năm học vừa bị đóng
    // sổ bên KTX, cấu hình thiếu, phiếu chưa cấp được. Suy `source_count > 0`
    // thành "được ghi" là dựng một định nghĩa thứ hai — và nó sẽ mở nút Ghi ở
    // đúng những ca backend vừa khoá.
    // ⚠️ Phiếu CÒN nguyên và còn hạn — chỉ `can_apply` nói không.
    //
    // Backend hôm nay luôn để `preview_token=null` khi `can_apply=false`, nên
    // hai trường trùng nhau và một ca "bình thường" KHÔNG phân biệt được UI
    // đang nghe trường nào. Ca này tách chúng ra để chỉ còn một câu trả lời
    // đúng: nghe `can_apply`.
    await xemTruocXong(
      preview({
        can_apply: false,
        source_count: 566,
        preview_token: "phieu-van-con",
        expires_at: 2_000_000,
        blocked_reason: "Năm học 2026 không còn mở ở hệ ký túc xá.",
      }),
    )

    expect(screen.getByTestId("so-nguon")).toHaveTextContent("566")
    expect(screen.getByTestId("nut-ghi")).toBeDisabled()
    expect(screen.getByTestId("ly-do-khoa")).toHaveTextContent("không còn mở")
  })

  it("can_apply=false thì khoá nút Ghi và nêu lý do", async () => {
    await xemTruocXong(
      preview({
        can_apply: false,
        preview_token: null,
        expires_at: null,
        counts: null,
        source_count: 0,
        blocked_reason: "Nguồn QLTS không có hồ sơ nào đủ điều kiện cho năm 2026.",
      }),
    )

    expect(screen.getByTestId("nut-ghi")).toBeDisabled()
    expect(screen.getByTestId("ly-do-khoa")).toHaveTextContent("không có hồ sơ nào")
  })

  it("KHÔNG có năm nào mở thì không tự điền năm hiện tại", async () => {
    mockGet.mockResolvedValueOnce({
      data: { open_academic_years: [], default_academic_year: null },
    })
    boc(<DormSyncPanel now={() => 1_000_000_000} />)

    expect(await screen.findByTestId("khong-co-nam-mo")).toBeInTheDocument()
    expect(screen.getByTestId("nut-xem-truoc")).toBeDisabled()
  })
})

describe("danh sách cảnh báo", () => {
  it("phản hồi HỎNG có hàng trùng qlts_profile_id vẫn hiện đủ", async () => {
    // ⚠️ Dữ liệu ca này TRÁI ràng buộc bên KTX, và đó là chủ ý.
    //
    // `students.qlts_profile_id` là `not null unique`, và
    // `uq_active_assignment_per_student` cấm một người giữ hai hàng
    // `active`/`cho_duyet` cùng lúc — nên hai dòng dưới đây KHÔNG thể ra từ một
    // database lành. Ca này canh cách màn hình cư xử khi phản hồi hỏng, không
    // canh một trạng thái nghiệp vụ hợp lệ.
    //
    // Vì sao vẫn đáng canh: nuốt mất một dòng cảnh báo là mất đúng thông tin
    // người ta đang dùng để quyết, và React nuốt nó ÂM THẦM — chỉ ghi một dòng
    // vào console.
    await xemTruocXong(
      preview({
        warnings: [
          {
            qlts_profile_id: 138,
            full_name: "Trần Thị Bình",
            building_name: "Toà B",
            room_code: "B305",
            bed_no: 13,
            status: "active",
          },
          {
            qlts_profile_id: 138,
            full_name: "Trần Thị Bình",
            building_name: "Toà B",
            room_code: "B307",
            bed_no: 4,
            status: "cho_duyet",
          },
        ],
      }),
    )

    const muc = screen.getByTestId("danh-sach-canh-bao").querySelectorAll("li")
    expect(muc).toHaveLength(2)
    // 🔴 Số lượng phần tử là CHƯA ĐỦ: React vẫn vẽ đủ hai `li` khi key trùng,
    // nó chỉ CẢNH BÁO. Bắt đúng cảnh báo ấy mới chứng minh key phân biệt được
    // hai hàng — nếu không, dùng riêng `qlts_profile_id` làm key vẫn xanh.
    const loiConsole = canhBaoConsole
      .mock.calls.map((c: unknown[]) => String(c[0]))
      .join(" ")
    expect(loiConsole).not.toMatch(/two children with the same key/i)
    expect(muc[0]).toHaveTextContent("B305")
    expect(muc[1]).toHaveTextContent("B307")
    expect(muc[1]).toHaveTextContent("cho_duyet")
  })

  it("hiển thị số liệu khuyến cáo backend đã tính", async () => {
    await xemTruocXong()

    const so = screen.getByTestId("so-lieu-khuyen-cao")
    expect(so).toHaveTextContent("Không rõ giới tính: 1")
    expect(so).toHaveTextContent("Chưa rõ trình độ: 2")
    expect(so).toHaveTextContent("Có số phụ: 98")
  })
})


// =============================================================================
// Năm contract của vòng review
// =============================================================================

describe("xác nhận trước khi ghi", () => {
  it("click ĐẦU chỉ mở hộp xác nhận, KHÔNG gửi request", async () => {
    await xemTruocXong()
    const truoc = mockPost.mock.calls.length

    await userEvent.click(screen.getByTestId("nut-ghi"))

    expect(await screen.findByRole("alertdialog")).toBeInTheDocument()
    expect(mockPost).toHaveBeenCalledTimes(truoc)
  })

  it("huỷ hộp xác nhận thì KHÔNG gửi gì", async () => {
    await xemTruocXong()
    const truoc = mockPost.mock.calls.length

    await userEvent.click(screen.getByTestId("nut-ghi"))
    await userEvent.click(await screen.findByRole("button", { name: "Huỷ" }))

    expect(mockPost).toHaveBeenCalledTimes(truoc)
    // Phiếu còn nguyên — người bấm đổi ý, không mất gì.
    expect(screen.getByTestId("nut-ghi")).toBeEnabled()
  })

  it("xác nhận gửi ĐÚNG MỘT lần", async () => {
    await xemTruocXong()
    const truoc = mockPost.mock.calls.length
    mockPost.mockResolvedValueOnce({
      data: {
        operation_id: "op-1",
        academic_year: 2026,
        outcome: "completed",
        message: "Đã đồng bộ xong.",
        ktx_run_id: 42,
        upserted: 5,
        blocked: 0,
        deactivated: 0,
        ledger_saved: true,
      },
    })

    await bamGhi()

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(truoc + 1))
  })
})

describe("phiếu TỰ hết hạn", () => {
  it("đang hợp lệ rồi TỰ tắt khi qua mốc, không cần render thủ công", async () => {
    // 🔴 `useMemo` chỉ tính lại khi có thứ gì kích render. Một màn hình mở sẵn,
    // người bấm đi họp mười phút rồi quay lại — không render nào xảy ra giữa
    // chừng, nên nút vẫn mở và request vẫn được gửi với một phiếu đã chết.
    //
    // Ca này đi QUA ranh giới bằng đồng hồ giả, KHÔNG render lại bằng tay.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const batDau = 1_000_000
      mockPost.mockResolvedValueOnce({
        data: preview({ expires_at: (batDau + 300_000) / 1000 }),
      })
      boc(<DormSyncPanel now={() => batDau} />)

      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      await user.click(await screen.findByTestId("nut-xem-truoc"))
      await screen.findByTestId("ket-qua-xem-truoc")

      // Còn hạn.
      expect(screen.getByTestId("nut-ghi")).toBeEnabled()

      // Đi qua mốc — không chạm gì khác.
      await vi.advanceTimersByTimeAsync(300_001)

      await waitFor(() => expect(screen.getByTestId("nut-ghi")).toBeDisabled())
    } finally {
      vi.useRealTimers()
    }
  })
})

describe("phiếu hết hạn TRONG LÚC hộp xác nhận đang mở", () => {
  it("mở hộp khi còn hạn, qua mốc rồi xác nhận ⇒ KHÔNG gửi thêm request", async () => {
    // 🔴 Đường hỏng mà ca fake-timer cũ KHÔNG bắt được: nó chỉ quan sát nút
    // NỀN. Nhưng nút xác nhận nằm TRONG hộp thoại, và hộp vẫn mở sau khi phiếu
    // chết — người bấm mở hộp, đọc lại danh sách cảnh báo, rồi xác nhận sau mốc
    // năm phút.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const batDau = 1_000_000
      mockPost.mockResolvedValueOnce({
        data: preview({ expires_at: (batDau + 300_000) / 1000 }),
      })
      boc(<DormSyncPanel now={() => batDau} />)

      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      await user.click(await screen.findByTestId("nut-xem-truoc"))
      await screen.findByTestId("ket-qua-xem-truoc")

      // Mở hộp xác nhận trong lúc phiếu CÒN hạn.
      await user.click(screen.getByTestId("nut-ghi"))
      expect(await screen.findByRole("alertdialog")).toBeInTheDocument()
      const truoc = mockPost.mock.calls.length

      // Đi qua mốc trong khi hộp đang mở.
      await vi.advanceTimersByTimeAsync(300_001)

      // Hộp phải tự đóng — không còn nút nào để bấm nhầm.
      await waitFor(() =>
        expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
      )
      expect(mockPost).toHaveBeenCalledTimes(truoc)
    } finally {
      vi.useRealTimers()
    }
  })

  it("ghi() tự chặn khi mất quyền — gọi THẲNG qua hook", async () => {
    // 🔴 Vế thứ hai của cùng hàng rào, và phải gọi THẲNG `ghi()`.
    //
    // Bấm nút không kiểm được điều này: nút đang `disabled` nên trình duyệt
    // KHÔNG kích handler, và gỡ `choPhepGhi` khỏi `ghi()` vẫn cho ca xanh —
    // đã đo. Chỉ `renderHook` mới chạm được vào hàng rào bên trong.
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const boc2 = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    )

    mockPost.mockResolvedValueOnce({
      data: preview({ can_apply: false, preview_token: "phieu-van-con" }),
    })
    const { result } = renderHook(() => useDormSync(() => 1_000_000_000), {
      wrapper: boc2,
    })

    await act(async () => {
      result.current.xemTruoc(2026)
    })
    await waitFor(() => expect(result.current.preview).not.toBeNull())

    expect(result.current.choPhepGhi).toBe(false)
    const truoc = mockPost.mock.calls.length

    await act(async () => {
      result.current.ghi()
    })

    expect(mockPost).toHaveBeenCalledTimes(truoc)
  })
})

describe("ý định xác nhận KHÔNG sống sót qua lần xem trước sau", () => {
  it("hết hạn khi hộp đang mở, xem trước lại ⇒ hộp KHÔNG tự mở", async () => {
    // 🔴 Đường hỏng mà hai ca hết-hạn ở trên KHÔNG bắt được.
    //
    // Chúng chỉ chứng minh hộp BIẾN MẤT khi mất quyền ghi. Nhưng `open={hoiLai
    // && choPhepGhi}` chỉ ẩn — `hoiLai` vẫn `true`. Phiếu mới về, `choPhepGhi`
    // bật lại, và hộp xác nhận TỰ MỞ trên một danh sách người đó chưa kịp đọc,
    // nút Ghi sẵn dưới ngón tay. Thao tác này không có đường lùi.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const batDau = 1_000_000
      mockPost
        .mockResolvedValueOnce({
          data: preview({ expires_at: (batDau + 300_000) / 1000 }),
        })
        // Phiếu thứ hai còn hạn dài hơn — số hồ sơ KHÁC, để thấy rõ đây là một
        // danh sách mới cần đọc lại chứ không phải màn hình cũ.
        //
        // ⚠️ `preview_token` cố ý GIỮ NGUYÊN chuỗi cũ. Server thật ký kèm
        // `iat` nên hai phiếu không trùng mã, nhưng bám vào điều đó là mượn
        // một giả định của phía bên kia để giữ an toàn cho phía này. Ca này
        // dựng đúng trường hợp giả định ấy sai, và màn hình vẫn phải đứng
        // vững — nó nhận ra phiếu mới bằng danh tính đối tượng, không bằng
        // chuỗi. Bản so `preview_token` đã ĐỎ ở đây, đúng như phải vậy.
        .mockResolvedValueOnce({
          data: preview({
            source_count: 601,
            expires_at: (batDau + 900_000) / 1000,
          }),
        })
      boc(<DormSyncPanel now={() => batDau} />)

      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      await user.click(await screen.findByTestId("nut-xem-truoc"))
      await screen.findByTestId("ket-qua-xem-truoc")

      await user.click(screen.getByTestId("nut-ghi"))
      expect(await screen.findByRole("alertdialog")).toBeInTheDocument()

      // Phiếu chết trong lúc hộp đang mở.
      await vi.advanceTimersByTimeAsync(300_001)
      await waitFor(() =>
        expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
      )

      // Người bấm làm đúng thứ giao diện mời: xem trước lại.
      await user.click(screen.getByTestId("nut-xem-truoc"))
      await waitFor(() =>
        expect(screen.getByTestId("so-nguon")).toHaveTextContent("601"),
      )

      // ⚠️ Vế này phải khẳng định TRƯỚC: quyền ghi đã bật lại thật. Thiếu nó,
      // ca vẫn xanh khi hộp không mở chỉ vì `choPhepGhi` còn `false` — xanh vì
      // lý do khác với thứ đang cần chứng minh.
      await waitFor(() => expect(screen.getByTestId("nut-ghi")).toBeEnabled())

      // Quyền có, nhưng Ý ĐỊNH thì không: hộp chỉ mở khi người đó bấm lại.
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe("lỗi lạ không bị nuốt", () => {
  it("lỗi KHÔNG nhận diện được đi qua handleApiError", async () => {
    // Bản trước chỉ ghi chú "để component xử" rồi không ai xử: một lỗi mạng
    // im lặng tuyệt đối, và người vận hành nhìn nút quay về trạng thái thường
    // như chưa có gì xảy ra.
    await xemTruocXong()
    const loiLa = new AxiosError("Network Error")

    mockPost.mockRejectedValueOnce(loiLa)
    await bamGhi()

    await waitFor(() => expect(mockHandleApiError).toHaveBeenCalledTimes(1))
    expect(mockHandleApiError.mock.calls[0][0]).toBe(loiLa)
  })

  it("phản hồi SAI HÌNH DẠNG (không phải AxiosError) vẫn báo ra màn hình", async () => {
    // 🔴 Lỗi Zod parse KHÔNG phải `AxiosError`. Bản trước ép kiểu bằng `as`
    // rồi đưa thẳng cho `handleApiError` — `tsc` đỏ, và ở runtime nó rơi vào
    // một nhánh không dành cho nó. Người vận hành không thấy gì.
    await xemTruocXong()
    mockPost.mockResolvedValueOnce({ data: { khong_dung_hinh_dang: true } })

    await bamGhi()

    await waitFor(() => expect(mockToastError).toHaveBeenCalledTimes(1))
    expect(String(mockToastError.mock.calls[0][0])).toMatch(/không đọc được/i)
    // Không phải lỗi HTTP nên KHÔNG đi qua handler chung.
    expect(mockHandleApiError).not.toHaveBeenCalled()
  })

  it("lỗi dorm-sync CÓ KIỂU vẫn xử riêng, KHÔNG rơi vào handler chung", async () => {
    // Handler chung cố ý che `detail` của mã CONFLICT; để lỗi này rơi vào đó
    // là mất sạch `next_action`.
    await xemTruocXong()
    mockPost.mockRejectedValueOnce(loiChan("outcome_unknown", "manual_reconcile"))

    await bamGhi()

    await screen.findByTestId("chan-manual_reconcile")
    expect(mockHandleApiError).not.toHaveBeenCalled()
  })
})

describe("payload chặn SAI HÌNH DẠNG vẫn phải khoá", () => {
  // Mã ĐÚNG của ta, nhưng phần mô tả hỏng. Ba dạng hỏng thật sự gặp: thiếu
  // trường, sai giá trị enum, và sai kiểu.
  const HONG: Array<[string, Record<string, unknown>]> = [
    [
      "thiếu next_action",
      {
        detail: "Lượt trước chưa rõ kết cục.",
        error_code: "DORM_SYNC_OPERATION_BLOCKED",
        operation_status: "outcome_unknown",
      },
    ],
    [
      "next_action lạ (backend thêm giá trị mới)",
      {
        detail: "Lượt trước chưa rõ kết cục.",
        error_code: "DORM_SYNC_OPERATION_BLOCKED",
        operation_status: "outcome_unknown",
        next_action: "retry_later",
      },
    ],
    [
      "next_action sai kiểu",
      {
        detail: "Lượt trước chưa rõ kết cục.",
        error_code: "DORM_SYNC_OPERATION_BLOCKED",
        operation_status: "running",
        next_action: null,
      },
    ],
  ]

  it.each(HONG)("%s ⇒ khoá MỌI thao tác, đòi đối soát tay", async (_ten, than) => {
    // 🔴 Đây là ca FAIL-OPEN đắt nhất của màn hình.
    //
    // Bản trước trả `null` khi payload không parse được, đẩy lỗi sang
    // `handleApiError` chung. Nhánh đó không biết gì về sổ cái: không dựng
    // `TrangThaiChan`, nên `khoaMoiThaoTac` giữ `false` và nút quay về trạng
    // thái thường. Người vận hành bấm lại — chồng một lượt ghi lên một lượt có
    // thể đang sống bên KTX.
    //
    // Server đã nói "chặn"; chỉ phần mô tả là không đọc được. Vế chắc chắn
    // phải được giữ, vế còn lại hạ xuống mức an toàn nhất.
    const loi = new AxiosError("409")
    loi.response = {
      data: than,
      status: 409,
      statusText: "Conflict",
      headers: {},
      config: {} as never,
    }
    await xemTruocXong()
    mockPost.mockRejectedValueOnce(loi)

    await bamGhi()

    // Rơi vào nhánh an toàn nhất, không phải nhánh "cho thử lại".
    expect(await screen.findByTestId("chan-manual_reconcile")).toBeInTheDocument()
    expect(screen.getByTestId("canh-bao-doi-soat")).toBeInTheDocument()

    // Khoá CẢ nút xem trước — `manual_reconcile` không cho chạy lượt mới.
    await waitFor(() =>
      expect(screen.getByTestId("nut-xem-truoc")).toBeDisabled(),
    )

    // Và KHÔNG được rơi vào handler chung: nó sẽ trả nút về trạng thái thường.
    expect(mockHandleApiError).not.toHaveBeenCalled()
  })

  it("payload ĐỦ hình dạng vẫn đi đúng next_action của nó — vế đảo", async () => {
    // Vế đảo: nếu hạ tất cả xuống `manual_reconcile` thì ca trên xanh mà hàng
    // rào lại quá tay — `failed` phải cho xem trước lại.
    await xemTruocXong()
    mockPost.mockRejectedValueOnce(loiChan("failed", "preview_again"))

    await bamGhi()

    expect(await screen.findByTestId("chan-preview_again")).toBeInTheDocument()
    expect(screen.queryByTestId("canh-bao-doi-soat")).not.toBeInTheDocument()
    expect(screen.getByTestId("nut-xem-truoc")).toBeEnabled()
  })
})

describe("làm mới bối cảnh sau khi ghi", () => {
  it("mutation còn pending cho tới khi invalidate xong", async () => {
    // 🔴 Không `return` promise invalidate thì nút mở lại trong khi bối cảnh
    // còn là bản cũ, và người bấm nhìn một màn hình đã lỗi thời ngay sau thao
    // tác nặng nhất của hệ.
    await xemTruocXong()

    // ⚠️ Bọc trong object: gán bên trong closure thì TS thu hẹp biến `let`
    // xuống `null` và `thaBoiCanh?.()` báo "not callable".
    const tha: { fn: (() => void) | null } = { fn: null }
    mockGet.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          tha.fn = () => resolve({ data: BOI_CANH })
        }),
    )
    mockPost.mockResolvedValueOnce({
      data: {
        operation_id: "op-1",
        academic_year: 2026,
        outcome: "completed",
        message: "Đã đồng bộ xong.",
        ktx_run_id: 42,
        upserted: 5,
        blocked: 0,
        deactivated: 0,
        ledger_saved: true,
      },
    })

    await bamGhi()

    // Bối cảnh đang được làm mới ⇒ mutation CHƯA xong.
    //
    // ⚠️ Khẳng định vào `dangGhi`, KHÔNG vào khối kết quả: `setKetQua` chạy
    // đồng bộ trong `onSuccess` nên kết quả hiện ngay, còn thứ phải kéo dài
    // tới hết invalidation là trạng thái `pending` của mutation.
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2))
    expect(screen.getByTestId("dang-ghi")).toBeInTheDocument()

    tha.fn?.()
    await waitFor(() =>
      expect(screen.queryByTestId("dang-ghi")).not.toBeInTheDocument(),
    )
    expect(screen.getByTestId("ket-qua-completed")).toBeInTheDocument()
  })
})
