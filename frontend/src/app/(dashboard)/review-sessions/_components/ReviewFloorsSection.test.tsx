/**
 * GĐ2-B F2 — M3 "Điểm sàn" (xem theo E3; soạn theo E10, lưu qua E4), dựng qua ĐÚNG `[sessionId]/page.tsx` (máy chủ giả MSW theo HĐ4
 * §3.1 + phụ lục E10 §1.4; QueryClient mang mặc định thật của ứng dụng). Máy chủ S1 KHÔNG có trong nhánh này — giả theo phụ lục.
 *
 * Khoá (thiết kế §3.4, §6.2 F2; phụ lục E10; đính chính 2; owner G2 / G10):
 *  - xem: MỘT dòng chung "lưu lần cuối bởi … lúc …" (G2), không cột người sửa; chỉ tiêu `null` ≠ `0`; chế độ xem không gọi E10;
 *  - thin client: nhóm "Cần nhập sàn" theo CỜ `floor_applicable`, ô nhập theo CỜ `floor_accepted`, nút soạn / lưu theo
 *    `available_actions` (E3 mở bộ soạn, E10 cho lưu) — dữ liệu thử cố ý cho cờ NGƯỢC với `state` / `is_deleted`;
 *  - dạng điểm: hiện mức đang lưu "15,00"; "15,5" ⇒ "15.50"; ô trống KHÔNG thành 0; sai dạng ⇒ khoá; gửi TOÀN BỘ + `session_version`
 *    của E10; rỗng ⇒ hỏi lại; > 500 dòng ⇒ khoá;
 *  - lỗi E4: 409 STALE giữ bản soạn + bảng so + gửi `version` mới; 409 NOT_DRAFT rời chế độ soạn; 400 `bad_member` câu máy chủ + tô
 *    đúng id; 422 tô theo `loc`; đóng băng / mất kết nối giữ bản soạn; E10 tải lỗi ⇒ hiện lỗi, không vẽ bảng cũ;
 *  - ca tổ hợp bắt buộc: sửa điểm → E4 409 STALE → E3 tải lại lỗi 429 → lỗi mạng → thành công ⇒ bản soạn CÒN, gửi `version` mới.
 * Dữ liệu giả.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { toast } from "sonner"
import { afterEach, describe, expect, it, vi } from "vitest"

import { formatDateTimeVN } from "@/lib/document-review/messages"
import {
  FLOORS_BAD_MEMBER_HINT,
  FLOORS_CONFIRM_EMPTY,
  FLOORS_CONFIRM_EMPTY_NO,
  FLOORS_INVALID_422,
  FLOORS_NOT_EDITABLE,
  FLOORS_SAVED,
  FROZEN_MESSAGE,
  RATE_LIMITED_MESSAGE,
  READ_NETWORK_MESSAGE,
  WRITE_UNCERTAIN_MESSAGE,
  floorDroppedNote,
  floorsLastSaved,
  floorsSaveLabel,
  floorsTooMany,
} from "@/lib/review-sessions/messages"
import { server } from "@/test/mocks/server"
import { chanRequestRo } from "@/test/review-sessions-msw"
import {
  E4_BAD_MEMBER_BODY,
  RS,
  floorCandidateGia,
  floorCandidatesGia,
  floorGia,
  sessionDaHuyGia,
  sessionGia,
} from "@/test/mocks/review-sessions-data"
import { renderApp } from "@/test/review-sessions-render"
import { resolveServerTree } from "@/test/server-component"

import ReviewSessionDetailPage from "../[sessionId]/page"

const { push, replace, notFound } = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND")
  }),
}))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/review-sessions/3",
  notFound,
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

afterEach(() => server.resetHandlers())

type Tra = () => Response | Promise<Response>
const json = (body: Record<string, unknown>, status = 200): Tra => () => HttpResponse.json(body, { status })

/** GET giả: lần gọi thứ n trả `chuoi[n-1]` (hết chuỗi ⇒ phần tử cuối). Trả bộ đếm. */
function mayChuGet(url: string, chuoi: Tra[]): { lan: number } {
  const dem = { lan: 0 }
  server.use(
    http.get(url, () => {
      dem.lan += 1
      return chuoi[Math.min(dem.lan, chuoi.length) - 1]()
    }),
  )
  return dem
}
const mayChuE3 = (chuoi: Tra[]) => mayChuGet(`${RS}/3`, chuoi)
const mayChuE10 = (chuoi: Tra[]) => mayChuGet(`${RS}/3/floor-candidates`, chuoi)

/** E4 giả: lần gọi thứ n trả `chuoi[n-1]`; ghi lại từng thân gửi lên. */
function mayChuE4(chuoi: Tra[]): unknown[] {
  const than: unknown[] = []
  server.use(
    http.put(`${RS}/3/floors`, async ({ request }) => {
      than.push(await request.json())
      return chuoi[Math.min(than.length, chuoi.length) - 1]()
    }),
  )
  return than
}

const STALE_409 = json(
  {
    reason_code: "review_session_stale",
    current_version: 5,
    detail: "Lần xét đã được sửa ở nơi khác sau khi bạn mở — hãy tải lại rồi làm lại.",
    error_code: "REVIEW_SESSION_STALE",
  },
  409,
)

async function moChiTiet() {
  return renderApp(await resolveServerTree(ReviewSessionDetailPage({ params: Promise.resolve({ sessionId: "3" }) })))
}

/** Mở chế độ soạn và chờ bảng E10 hiện. */
async function moSoan() {
  fireEvent.click(await screen.findByTestId("nut-edit_floors"))
  await screen.findByTestId("san-soan")
}

const go = (id: number, s: string) => fireEvent.change(screen.getByTestId(`san-o-${id}`), { target: { value: s } })

// ═══════════════════════════════════════ chế độ xem ═══════════════════════════════════════
// Chặn request rò (đối chiếu CI F4; quyết định điều phối 25-11): request không handler ⇒ in lỗi MSW, KHÔNG ra mạng, ca ĐỎ.
chanRequestRo()

describe("M3 — chế độ xem (E3)", () => {
  it("owner G2: MỘT dòng 'lưu lần cuối bởi … lúc …', không cột người sửa; chỉ tiêu null ≠ 0; điểm dấu phẩy; 'Đã xoá'; KHÔNG gọi E10", async () => {
    // Biến thể phá: thêm cột "Người sửa" từng dòng ⇒ đếm "Người dùng #" trong thẻ > 1 ⇒ ĐỎ.
    const luc = "2026-11-24T02:05:00Z"
    mayChuE3([
      json(
        sessionGia({
          floors: [
            floorGia({ offering_academic_info_id: 41, annual_admission_quota: 30, floor_score: "15.00", updated_at: luc }),
            floorGia({ offering_academic_info_id: 44, annual_admission_quota: 0, floor_score: "16.50", is_deleted: true, updated_at: luc }),
            floorGia({ offering_academic_info_id: 45, annual_admission_quota: null, floor_score: "0.00", updated_at: luc }),
          ],
        }),
      ),
    ])
    const e10 = mayChuE10([json(floorCandidatesGia())])
    await moChiTiet()
    const the = await screen.findByTestId("san")
    expect(within(the).getByTestId("san-luu-lan-cuoi")).toHaveTextContent(floorsLastSaved("Người dùng #1", formatDateTimeVN(luc)))
    expect(within(the).getAllByText(/Người dùng #/)).toHaveLength(1)
    expect(within(the).queryByText(/Người sửa|Lúc sửa/)).toBeNull()
    expect(screen.getByTestId("san-xem-chi-tieu-41")).toHaveTextContent("30")
    expect(screen.getByTestId("san-xem-chi-tieu-44")).toHaveTextContent("0 — đóng tuyệt đối")
    expect(screen.getByTestId("san-xem-chi-tieu-45")).toHaveTextContent("Chưa cấu hình")
    expect(screen.getByTestId("san-xem-diem-41")).toHaveTextContent("15,00")
    expect(screen.getByTestId("san-xem-diem-45")).toHaveTextContent("0,00")
    expect(screen.getByTestId("san-xem-44")).toHaveTextContent("Đã xoá")
    expect(screen.queryByTestId("san-o-41")).toBeNull()
    expect(e10.lan).toBe(0)
  })
})

// ═══════════════════════════════════════ thin client ═══════════════════════════════════════
describe("M3 — soạn: nhóm / ô nhập theo CỜ máy chủ (FE không tự suy)", () => {
  it("nhóm 'Cần nhập sàn' theo floor_applicable — state 'ok' mà cờ false KHÔNG vào; state 'quota_closed' mà cờ true VÀO", async () => {
    // Biến thể phá: suy nhóm từ `state ∈ {ok, floor_missing}` ⇒ 42 vào, 43 ra ⇒ ĐỎ.
    mayChuE3([json(sessionGia())])
    mayChuE10([
      json(
        floorCandidatesGia({
          items: [
            floorCandidateGia({ offering_academic_info_id: 41 }),
            floorCandidateGia({ offering_academic_info_id: 42, state: "ok", floor_applicable: false }),
            floorCandidateGia({ offering_academic_info_id: 43, state: "quota_closed", annual_admission_quota: 0, floor_applicable: true }),
            floorCandidateGia({
              offering_academic_info_id: 44,
              state: "quota_closed",
              annual_admission_quota: 0,
              floor_applicable: false,
              floor_score: null,
            }),
            floorCandidateGia({
              offering_academic_info_id: 45,
              state: "quota_not_configured",
              annual_admission_quota: null,
              group_id: null,
              group_code: null,
              floor_applicable: false,
              floor_score: null,
            }),
          ],
        }),
      ),
    ])
    await moChiTiet()
    await moSoan()
    const can = screen.getByTestId("san-nhom-needs_floor")
    expect(within(can).getByTestId("san-dong-41")).toBeInTheDocument()
    expect(within(can).getByTestId("san-dong-43")).toBeInTheDocument()
    expect(within(can).queryByTestId("san-dong-42")).toBeNull()
    expect(screen.getByTestId("san-nhom-needs_floor-tieu-de")).toHaveTextContent("Cần nhập sàn (2)")
    expect(within(screen.getByTestId("san-nhom-closed")).getByTestId("san-dong-44")).toBeInTheDocument()
    expect(within(screen.getByTestId("san-nhom-not_reviewable")).getByTestId("san-dong-45")).toBeInTheDocument()
    expect(within(screen.getByTestId("san-nhom-other")).getByTestId("san-dong-42")).toBeInTheDocument()
    // chỉ tiêu null ≠ 0 ở bộ soạn
    expect(screen.getByTestId("san-chi-tieu-44")).toHaveTextContent("0 — đóng tuyệt đối")
    expect(screen.getByTestId("san-chi-tieu-45")).toHaveTextContent("Chưa cấu hình")
    // trạng thái hiện NGUYÊN nhãn của state máy chủ
    expect(screen.getByTestId("san-trang-thai-45")).toHaveTextContent("Chưa có chỉ tiêu")
  })

  it("ô nhập CHỈ ở dòng floor_accepted — không theo is_deleted / state; dòng không nhận được mà còn mức ⇒ 'sẽ bỏ khi lưu'", async () => {
    // Biến thể phá: hiện ô theo `!is_deleted` (hoặc theo state) ⇒ 46 mất ô / 47 có ô ⇒ ĐỎ.
    mayChuE3([json(sessionGia())])
    mayChuE10([
      json(
        floorCandidatesGia({
          items: [
            floorCandidateGia({
              offering_academic_info_id: 46,
              state: "deleted",
              is_deleted: true,
              floor_applicable: false,
              floor_accepted: true,
              floor_score: null,
            }),
            floorCandidateGia({ offering_academic_info_id: 47, state: "ok", floor_accepted: false, floor_score: "12.00" }),
            floorCandidateGia({
              offering_academic_info_id: 48,
              state: "deleted",
              is_deleted: true,
              floor_applicable: false,
              floor_accepted: false,
              floor_score: null,
            }),
          ],
        }),
      ),
    ])
    await moChiTiet()
    await moSoan()
    expect(screen.getByTestId("san-o-46")).toBeInTheDocument()
    expect(screen.queryByTestId("san-o-47")).toBeNull()
    expect(screen.queryByTestId("san-o-48")).toBeNull()
    expect(screen.getByTestId("san-bo-khi-luu-47")).toHaveTextContent(floorDroppedNote("12,00"))
  })

  it("E3 cho soạn nhưng E10 (ảnh chụp mới hơn) không còn edit_floors ⇒ câu 'không còn sửa được', ô và nút Lưu khoá", async () => {
    // Biến thể phá: cho lưu theo `available_actions` của E3, hoặc tự suy từ `session_status === "draft"` ⇒ nút Lưu mở ⇒ ĐỎ.
    // Dữ liệu cố ý: trạng thái VẪN nháp mà máy chủ không trả `edit_floors` — giao diện theo cờ hành động, không theo trạng thái.
    mayChuE3([json(sessionGia())])
    mayChuE10([json(floorCandidatesGia({ session_status: "draft", available_actions: ["run_evaluate"] }))])
    await moChiTiet()
    await moSoan()
    expect(screen.getByTestId("san-khong-sua-duoc")).toHaveTextContent(FLOORS_NOT_EDITABLE)
    expect(screen.getByTestId("san-o-41")).toBeDisabled()
    expect(screen.getByTestId("san-luu")).toBeDisabled()
  })

  it("không có edit_floors ở E3 ⇒ không nút 'Sửa điểm sàn', không bộ soạn", async () => {
    mayChuE3([json(sessionGia({ available_actions: ["run_evaluate", "cancel"] }))])
    const e10 = mayChuE10([json(floorCandidatesGia())])
    await moChiTiet()
    await screen.findByTestId("san")
    expect(screen.queryByTestId("nut-edit_floors")).toBeNull()
    expect(screen.queryByTestId("san-soan")).toBeNull()
    expect(e10.lan).toBe(0)
  })
})

// ═══════════════════════════════════════ dạng điểm + thân gửi ═══════════════════════════════════════
describe("M3 — dạng điểm, gửi TOÀN BỘ danh sách", () => {
  it("hiện mức đang lưu '15,00'; '15,5' ⇒ '15.50'; ô xoá trắng KHÔNG thành 0; gửi TOÀN BỘ + session_version của E10; dòng không nhận được bỏ ra", async () => {
    // Biến thể phá: gửi `version` của E3 (2) thay vì `session_version` của E10 (7) ⇒ ĐỎ; ô trống ⇒ "0.00" ⇒ ĐỎ.
    mayChuE3([json(sessionGia({ version: 2 })), json(sessionGia({ version: 8 }))])
    mayChuE10([
      json(
        floorCandidatesGia({
          session_version: 7,
          items: [
            floorCandidateGia({ offering_academic_info_id: 41, floor_score: "15.00" }),
            floorCandidateGia({ offering_academic_info_id: 42, floor_score: null, state: "floor_missing" }),
            floorCandidateGia({ offering_academic_info_id: 43, floor_score: "14.00" }),
            floorCandidateGia({ offering_academic_info_id: 47, floor_accepted: false, floor_score: "12.00" }),
          ],
        }),
      ),
    ])
    const than = mayChuE4([json(sessionGia({ version: 8 }))])
    await moChiTiet()
    await moSoan()
    expect(screen.getByTestId("san-o-41")).toHaveValue("15,00")
    expect(screen.getByTestId("san-o-42")).toHaveValue("")
    go(42, "15,5")
    go(43, "")
    expect(screen.getByTestId("san-luu")).toHaveTextContent(floorsSaveLabel(2))
    fireEvent.click(screen.getByTestId("san-luu"))
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({
      version: 7,
      floors: [
        { offering_academic_info_id: 41, floor_score: "15.00" },
        { offering_academic_info_id: 42, floor_score: "15.50" },
      ],
    })
    // thành công ⇒ rời chế độ soạn, báo đã lưu
    await waitFor(() => expect(screen.queryByTestId("san-soan")).toBeNull())
    expect(vi.mocked(toast.success)).toHaveBeenCalledWith(FLOORS_SAVED)
  })

  it("ô sai dạng ⇒ câu dạng + khoá Lưu; sửa đúng ⇒ mở lại", async () => {
    mayChuE3([json(sessionGia())])
    mayChuE10([json(floorCandidatesGia())])
    await moChiTiet()
    await moSoan()
    expect(screen.getByTestId("san-luu")).toBeEnabled()
    go(41, "15,555")
    expect(screen.getByTestId("san-o-loi-41")).toBeInTheDocument()
    expect(screen.getByTestId("san-luu")).toBeDisabled()
    go(41, "1000")
    expect(screen.getByTestId("san-luu")).toBeDisabled()
    go(41, "15")
    expect(screen.queryByTestId("san-o-loi-41")).toBeNull()
    expect(screen.getByTestId("san-luu")).toBeEnabled()
  })

  it("danh sách rỗng ⇒ hỏi lại 'Xoá hết điểm sàn…'; 'Không' ⇒ không gửi; 'Xoá hết' ⇒ gửi floors []", async () => {
    mayChuE3([json(sessionGia())])
    mayChuE10([json(floorCandidatesGia())])
    const than = mayChuE4([json(sessionGia({ version: 3, floors: [] }))])
    await moChiTiet()
    await moSoan()
    go(41, "")
    expect(screen.getByTestId("san-luu")).toHaveTextContent(floorsSaveLabel(0))
    fireEvent.click(screen.getByTestId("san-luu"))
    expect(await screen.findByTestId("san-xac-nhan-xoa-het")).toHaveTextContent(FLOORS_CONFIRM_EMPTY)
    fireEvent.click(screen.getByRole("button", { name: FLOORS_CONFIRM_EMPTY_NO }))
    await waitFor(() => expect(screen.queryByTestId("san-xac-nhan-xoa-het")).toBeNull())
    expect(than).toHaveLength(0)

    fireEvent.click(screen.getByTestId("san-luu"))
    fireEvent.click(await screen.findByTestId("san-xoa-het-dong-y"))
    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ version: 2, floors: [] })
  })

  it("> 500 dòng sẽ gửi ⇒ khoá Lưu + báo số dòng; đúng 500 ⇒ mở", async () => {
    mayChuE3([json(sessionGia())])
    mayChuE10([
      json(
        floorCandidatesGia({
          items: Array.from({ length: 501 }, (_, i) => floorCandidateGia({ offering_academic_info_id: 1000 + i, floor_score: "10.00" })),
        }),
      ),
    ])
    await moChiTiet()
    await moSoan()
    expect(screen.getByTestId("san-qua-nhieu")).toHaveTextContent(floorsTooMany(501, 500))
    expect(screen.getByTestId("san-luu")).toBeDisabled()
    go(1000, "")
    expect(screen.queryByTestId("san-qua-nhieu")).toBeNull()
    expect(screen.getByTestId("san-luu")).toBeEnabled()
  })
})

// ═══════════════════════════════════════ lỗi E4 ═══════════════════════════════════════
describe("M3 — lỗi E4", () => {
  it("409 STALE ⇒ GIỮ bản soạn, câu máy chủ, E3 + E10 tải lại; bảng so 'đang soạn ↔ vừa lưu'; 'Lưu bản của tôi đè lên' gửi version MỚI", async () => {
    // Biến thể phá: xoá bản soạn khi E4 lỗi ⇒ ô 41 về "15,50" ⇒ ĐỎ; làm mới chỉ ở onSuccess ⇒ E10 không tải lại ⇒ gửi version 2 ⇒ ĐỎ.
    const e3 = mayChuE3([json(sessionGia({ version: 2 })), json(sessionGia({ version: 5 }))])
    const e10 = mayChuE10([
      json(floorCandidatesGia({ items: [floorCandidateGia({ offering_academic_info_id: 41 }), floorCandidateGia({ offering_academic_info_id: 42 })] })),
      json(
        floorCandidatesGia({
          session_version: 5,
          items: [
            floorCandidateGia({ offering_academic_info_id: 41, floor_score: "15.50" }),
            floorCandidateGia({ offering_academic_info_id: 42, floor_score: "13.00" }),
          ],
        }),
      ),
    ])
    const than = mayChuE4([STALE_409, json(sessionGia({ version: 6 }))])
    await moChiTiet()
    await moSoan()
    go(41, "16")
    fireEvent.click(screen.getByTestId("san-luu"))
    expect(await screen.findByTestId("san-loi")).toHaveTextContent(
      "Lần xét đã được sửa ở nơi khác sau khi bạn mở — hãy tải lại rồi làm lại.",
    )
    await waitFor(() => expect({ e3: e3.lan, e10: e10.lan }).toEqual({ e3: 2, e10: 2 }))
    expect(await screen.findByTestId("san-xung-dot")).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId("san-so-vua-luu-41")).toHaveTextContent("15,50"))
    expect(screen.getByTestId("san-o-41")).toHaveValue("16")
    expect(screen.getByTestId("san-so-cua-toi-41")).toHaveTextContent("16,00")
    // dòng không sửa lấy mức vừa lưu, không vào bảng so
    expect(screen.getByTestId("san-o-42")).toHaveValue("13,00")
    expect(screen.queryByTestId("san-so-42")).toBeNull()

    await waitFor(() => expect(screen.getByTestId("san-luu-de")).toBeEnabled())
    fireEvent.click(screen.getByTestId("san-luu-de"))
    await waitFor(() => expect(than).toHaveLength(2))
    expect(than[1]).toEqual({
      version: 5,
      floors: [
        { offering_academic_info_id: 41, floor_score: "16.00" },
        { offering_academic_info_id: 42, floor_score: "13.00" },
      ],
    })
  })

  it("409 STALE ⇒ 'Dùng bản mới (bỏ thay đổi của tôi)' ⇒ ô về mức vừa lưu, bảng so tắt, nút Lưu trở lại", async () => {
    mayChuE3([json(sessionGia({ version: 2 })), json(sessionGia({ version: 5 }))])
    mayChuE10([
      json(floorCandidatesGia()),
      json(floorCandidatesGia({ session_version: 5, items: [floorCandidateGia({ floor_score: "15.50" })] })),
    ])
    mayChuE4([STALE_409])
    await moChiTiet()
    await moSoan()
    go(41, "16")
    fireEvent.click(screen.getByTestId("san-luu"))
    await screen.findByTestId("san-xung-dot")
    await waitFor(() => expect(screen.getByTestId("san-dung-ban-moi")).toBeEnabled())
    await waitFor(() => expect(screen.getByTestId("san-so-vua-luu-41")).toHaveTextContent("15,50"))
    fireEvent.click(screen.getByTestId("san-dung-ban-moi"))
    expect(screen.getByTestId("san-o-41")).toHaveValue("15,50")
    expect(screen.queryByTestId("san-xung-dot")).toBeNull()
    expect(screen.getByTestId("san-luu")).toBeInTheDocument()
  })

  it("409 REVIEW_SESSION_NOT_DRAFT ⇒ rời chế độ soạn, toast câu máy chủ; E3 tải lại (đã huỷ ⇒ không còn nút soạn)", async () => {
    const detail = "Lần xét không còn ở trạng thái nháp — không sửa điểm sàn, không chạy kiểm hồ sơ và không huỷ được nữa."
    mayChuE3([json(sessionGia()), json(sessionDaHuyGia())])
    mayChuE10([json(floorCandidatesGia())])
    mayChuE4([json({ reason_code: "review_session_not_draft", status: "cancelled", detail, error_code: "REVIEW_SESSION_NOT_DRAFT" }, 409)])
    await moChiTiet()
    await moSoan()
    go(41, "16")
    fireEvent.click(screen.getByTestId("san-luu"))
    await waitFor(() => expect(screen.queryByTestId("san-soan")).toBeNull())
    expect(vi.mocked(toast.error)).toHaveBeenCalledWith(detail)
    await waitFor(() => expect(screen.getByTestId("lan-xet-trang-thai")).toHaveTextContent("Đã huỷ"))
    expect(screen.queryByTestId("nut-edit_floors")).toBeNull()
  })

  it("400 review_floor_bad_member ⇒ câu máy chủ + gợi ý; tô ĐÚNG dòng máy chủ chỉ ra; bản soạn còn", async () => {
    // Biến thể phá: bỏ tô theo `offering_academic_info_ids` ⇒ ĐỎ.
    mayChuE3([json(sessionGia())])
    mayChuE10([
      json(floorCandidatesGia({ items: [floorCandidateGia({ offering_academic_info_id: 41 }), floorCandidateGia({ offering_academic_info_id: 42 })] })),
    ])
    mayChuE4([json(E4_BAD_MEMBER_BODY, 400)])
    await moChiTiet()
    await moSoan()
    go(42, "17")
    fireEvent.click(screen.getByTestId("san-luu"))
    const loi = await screen.findByTestId("san-loi")
    expect(loi).toHaveTextContent("Có học vụ không thuộc năm 2026 (không tồn tại, đã xoá, hoặc khác năm).")
    expect(loi).toHaveTextContent(FLOORS_BAD_MEMBER_HINT)
    await waitFor(() => expect(screen.getByTestId("san-dong-41")).toHaveAttribute("data-flagged", "true"))
    expect(screen.getByTestId("san-dong-42")).not.toHaveAttribute("data-flagged")
    expect(screen.getByTestId("san-o-42")).toHaveValue("17")
  })

  it("422 ⇒ 'Điểm sàn chưa đúng dạng.' + tô dòng theo chỉ số trong loc", async () => {
    mayChuE3([json(sessionGia())])
    mayChuE10([
      json(floorCandidatesGia({ items: [floorCandidateGia({ offering_academic_info_id: 41 }), floorCandidateGia({ offering_academic_info_id: 42 })] })),
    ])
    mayChuE4([
      json(
        {
          detail: "Request validation failed",
          error_code: "VALIDATION_ERROR",
          errors: [{ loc: ["body", "floors", 1, "floor_score"], msg: "x", type: "value_error" }],
        },
        422,
      ),
    ])
    await moChiTiet()
    await moSoan()
    fireEvent.click(screen.getByTestId("san-luu"))
    expect(await screen.findByTestId("san-loi")).toHaveTextContent(FLOORS_INVALID_422)
    await waitFor(() => expect(screen.getByTestId("san-dong-42")).toHaveAttribute("data-flagged", "true"))
    expect(screen.getByTestId("san-dong-41")).not.toHaveAttribute("data-flagged")
  })

  it.each([
    { ten: "503 đóng băng", tra: json({ detail: "Admission frozen", code: "ADMISSION_FROZEN", frozen_prefix: "/api/admission-config" }, 503), cau: FROZEN_MESSAGE },
    { ten: "mất kết nối (chưa rõ đã ghi)", tra: (() => HttpResponse.error()) as Tra, cau: WRITE_UNCERTAIN_MESSAGE },
  ])("$ten ⇒ câu §5, GIỮ bản soạn, vẫn ở chế độ soạn; E3 + E10 tải lại", async ({ tra, cau }) => {
    const e3 = mayChuE3([json(sessionGia())])
    const e10 = mayChuE10([json(floorCandidatesGia())])
    mayChuE4([tra])
    await moChiTiet()
    await moSoan()
    go(41, "16")
    fireEvent.click(screen.getByTestId("san-luu"))
    expect(await screen.findByTestId("san-loi")).toHaveTextContent(cau)
    await waitFor(() => expect({ e3: e3.lan, e10: e10.lan }).toEqual({ e3: 2, e10: 2 }))
    expect(screen.getByTestId("san-soan")).toBeInTheDocument()
    expect(screen.getByTestId("san-o-41")).toHaveValue("16")
  })
})

// ═══════════════════════════════ E10 tải lỗi — không vẽ bảng cũ; bản soạn còn ═══════════════════════════════
describe("M3 — E10 tải lỗi (đính chính 2 §1)", () => {
  it("E10 tải lại bị 429 sau khi đã có dữ liệu ⇒ hiện LỖI, KHÔNG vẽ bảng cũ; tải lại được ⇒ ô đã gõ còn NGUYÊN", async () => {
    // Biến thể phá: bộ soạn đọc `data` trước `isError` ⇒ bảng cũ còn ⇒ ĐỎ; hook E10 bỏ `gcTime: 0` / có placeholder ⇒ (mức hook) ĐỎ.
    mayChuE3([json(sessionGia())])
    const e10 = mayChuE10([json(floorCandidatesGia()), json({ detail: "Rate limit exceeded" }, 429), json(floorCandidatesGia())])
    mayChuE4([() => HttpResponse.error()])
    await moChiTiet()
    await moSoan()
    go(41, "16")
    fireEvent.click(screen.getByTestId("san-luu"))
    expect(await screen.findByTestId("san-tai-loi")).toHaveTextContent(RATE_LIMITED_MESSAGE)
    expect(screen.queryByTestId("san-o-41")).toBeNull()
    expect(screen.queryByTestId("san-dong-41")).toBeNull()

    await waitFor(() => expect(screen.getByTestId("san-tai-lai")).toBeEnabled())
    fireEvent.click(screen.getByTestId("san-tai-lai"))
    await waitFor(() => expect(screen.getByTestId("san-o-41")).toHaveValue("16"))
    expect(e10.lan).toBe(3)
  })
})

// ═══════════════════════ ca tổ hợp bắt buộc — bản soạn sống qua 409 + E3 tải lại lỗi (khuôn F01-4) ═══════════════════════
describe("M3 — bản soạn điểm sàn sống qua lỗi / tải lại (khuôn F01-4)", () => {
  it("sửa điểm → E4 409 STALE → E3 tải lại lỗi 429 → lỗi mạng → thành công ⇒ bộ soạn hiện lại, ô đã gõ còn NGUYÊN, gửi version MỚI", async () => {
    // Biến thể phá: bản soạn là state của BỘ SOẠN (không ở màn cha) ⇒ nhánh lỗi E3 tháo bộ soạn ⇒ mất ô đã gõ ⇒ ĐỎ ở `toHaveValue`.
    const e3 = mayChuE3([
      json(sessionGia({ version: 2 })),
      json({ detail: "Rate limit exceeded" }, 429),
      () => HttpResponse.error(),
      json(sessionGia({ version: 5 })),
    ])
    mayChuE10([
      json(floorCandidatesGia({ session_version: 2 })),
      json(floorCandidatesGia({ session_version: 5, items: [floorCandidateGia({ floor_score: "15.50" })] })),
    ])
    const than = mayChuE4([STALE_409, json(sessionGia({ version: 6 }))])
    await moChiTiet()
    await moSoan()
    go(41, "16")
    fireEvent.click(screen.getByTestId("san-luu"))

    // E4 409 ⇒ làm mới E3 ⇒ 429 ⇒ nhánh lỗi THÁO cả màn (và bộ soạn).
    expect(await screen.findByTestId("lan-xet-loi")).toHaveTextContent(RATE_LIMITED_MESSAGE)
    expect(screen.queryByTestId("san-soan")).toBeNull()
    expect(screen.queryByTestId("san-o-41")).toBeNull()
    expect(e3.lan).toBe(2)

    // Tải lại ⇒ lỗi mạng (vẫn nhánh lỗi).
    await waitFor(() => expect(screen.getByTestId("lan-xet-tai-lai")).toBeEnabled())
    fireEvent.click(screen.getByTestId("lan-xet-tai-lai"))
    await waitFor(() => expect(screen.getByTestId("lan-xet-loi")).toHaveTextContent(READ_NETWORK_MESSAGE))
    expect(e3.lan).toBe(3)

    // Tải lại ⇒ thành công ⇒ bộ soạn hiện lại (máy chủ vẫn trả edit_floors) với NGUYÊN ô đã gõ + bảng so.
    await waitFor(() => expect(screen.getByTestId("lan-xet-tai-lai")).toBeEnabled())
    fireEvent.click(screen.getByTestId("lan-xet-tai-lai"))
    expect(await screen.findByTestId("san-soan")).toBeInTheDocument()
    expect(e3.lan).toBe(4)
    await waitFor(() => expect(screen.getByTestId("san-o-41")).toHaveValue("16"))
    expect(screen.getByTestId("san-xung-dot")).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId("san-so-vua-luu-41")).toHaveTextContent("15,50"))

    // Gửi lại dùng version MỚI (E10 mới) + đúng mức đã gõ.
    await waitFor(() => expect(screen.getByTestId("san-luu-de")).toBeEnabled())
    fireEvent.click(screen.getByTestId("san-luu-de"))
    await waitFor(() => expect(than).toHaveLength(2))
    expect(than[1]).toEqual({ version: 5, floors: [{ offering_academic_info_id: 41, floor_score: "16.00" }] })
  })

  it("'Bỏ thay đổi' ⇒ rời chế độ soạn, xoá bản soạn (mở lại thấy mức đang lưu)", async () => {
    mayChuE3([json(sessionGia())])
    mayChuE10([json(floorCandidatesGia())])
    await moChiTiet()
    await moSoan()
    go(41, "16")
    fireEvent.click(screen.getByTestId("san-bo"))
    await waitFor(() => expect(screen.queryByTestId("san-soan")).toBeNull())
    await moSoan()
    expect(screen.getByTestId("san-o-41")).toHaveValue("15,00")
  })
})
