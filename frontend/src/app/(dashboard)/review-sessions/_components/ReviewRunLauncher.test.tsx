/**
 * GĐ2-B F3 — M4: nút "Kiểm hồ sơ" (E6) + theo dõi lượt kiểm (E7 / E8) + danh sách lượt kiểm, dựng qua ĐÚNG `[sessionId]/page.tsx`
 * (máy chủ giả MSW theo HĐ4 §3; QueryClient mang mặc định thật của ứng dụng). Nửa giao diện của HĐ5: client xử lý `queued` / `running`.
 *
 * Khoá (thiết kế §3.5, §6.2 F3; đính chính 1 §5 "F3"; đính chính 2 §1; HĐ4 E6):
 *  - nút theo `available_actions`; gửi `{kind: "evaluate", session_version: <version E3>}`; khoá khi đang gửi / theo dõi;
 *  - 202 `done` ⇒ mở M5 theo `id` (Location khớp); Location LỆCH ⇒ lỗi hợp đồng, không theo dõi;
 *  - 202 `queued` / `running` ⇒ hỏi E8 giãn dần, DỪNG khi xong / hỏng / lỗi / hết trần; trạng thái lạ ⇒ chưa xong (không đoán);
 *    xong ⇒ làm mới E2 / E3 / E7 / E8 / E10;
 *  - mất kết nối / 502 / 504 ⇒ tra E7 (không gửi lại E6): có lượt mới hơn mốc ⇒ theo dõi; không ⇒ cho bấm lại;
 *  - 409 `REVIEW_RUN_IN_PROGRESS` ⇒ không gửi lại; chờ có TRẦN ⇒ "Lượt của người khác chưa xong — thử lại sau.";
 *  - hỏi lại bị 429 ⇒ hiện lỗi, KHÔNG vẽ trạng thái cũ, DỪNG tự hỏi; "Kiểm tra lại";
 *  - 409 STALE / NOT_DRAFT / 503 cấu hình / 503 mức ưu tiên / đóng băng;
 *  - theo dõi sống qua lúc E3 tải lại lỗi (nhánh lỗi của màn).
 * Nhịp hỏi lại trong tệp này là bản NHỎ (vi.mock `RUN_POLL_PLAN`) để test chạy nhanh; nhịp thật khoá ở `run-tracking.test.ts`.
 * Dữ liệu giả.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react"
import { delay, http, HttpResponse } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  CONFIG_CHANGED_BADGE,
  FROZEN_MESSAGE,
  RATE_LIMITED_MESSAGE,
  RUNS_EMPTY,
  RUN_LOCATION_MISMATCH,
  RUN_NO_NEW,
  RUN_OTHER_CEILING,
  RUN_OTHER_WAITING,
  RUN_STALE,
  RUN_SUBMITTING,
  RUN_UNCERTAIN_CHECKING,
  latestDoneRunLink,
  runDoneMessage,
  runFailedMessage,
  runOtherDone,
  runTrackingLabel,
} from "@/lib/review-sessions/messages"
import { pollsUntilCeiling, type RunPollPlan } from "@/lib/review-sessions/run-tracking"
import { server } from "@/test/mocks/server"
import { RS, pageGia, runGia, runSummaryGia, sessionDaHuyGia, sessionGia } from "@/test/mocks/review-sessions-data"
import { renderApp } from "@/test/review-sessions-render"
import { resolveServerTree } from "@/test/server-component"

import ReviewSessionDetailPage from "../[sessionId]/page"

const { push, replace, notFound, keHoach } = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND")
  }),
  keHoach: { firstDelayMs: 50, factor: 1.5, maxDelayMs: 80, ownCeilingMs: 3000, otherCeilingMs: 3000 },
}))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/review-sessions/3",
  notFound,
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock("@/lib/review-sessions/run-tracking", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/review-sessions/run-tracking")>()),
  RUN_POLL_PLAN: keHoach,
}))

const KE_HOACH_THU: RunPollPlan = { firstDelayMs: 50, factor: 1.5, maxDelayMs: 80, ownCeilingMs: 3000, otherCeilingMs: 3000 }

beforeEach(() => {
  Object.assign(keHoach, KE_HOACH_THU)
})

type Tra = () => Response | Promise<Response>
const json = (body: Record<string, unknown>, status = 200): Tra => () => HttpResponse.json(body, { status })
const choLau = (ms = 150) => new Promise((r) => setTimeout(r, ms))

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
const mayChuE7 = (chuoi: Tra[]) => mayChuGet(`${RS}/3/runs`, chuoi)
const mayChuE8 = (runId: number, chuoi: Tra[]) => mayChuGet(`${RS}/3/runs/${runId}`, chuoi)

/** E6 giả: lần gọi thứ n trả `chuoi[n-1]`; ghi lại từng thân gửi lên. */
function mayChuE6(chuoi: Tra[]): unknown[] {
  const than: unknown[] = []
  server.use(
    http.post(`${RS}/3/runs`, async ({ request }) => {
      than.push(await request.json())
      return chuoi[Math.min(than.length, chuoi.length) - 1]()
    }),
  )
  return than
}

/** 202 của E6. */
const tao = (than: Record<string, unknown>, headers: Record<string, string> = {}): Tra => () =>
  HttpResponse.json(than, { status: 202, headers })
/** Lượt 12 chưa kết thúc (HĐ4 §3.3: `summary` / `quota_view` = null khi chưa `done`). */
const chay = (status: string, over: Record<string, unknown> = {}) =>
  runGia({ id: 12, status, finished_at: null, duration_ms: null, summary: null, quota_view: null, ...over })

const LOC_12 = "/api/admission-config/review-sessions/3/runs/12"
const M5_12 = "/review-sessions/3/runs/12"
const CAU_DANG_CHAY = "Lần xét này đang có một lượt kiểm hồ sơ chạy — chờ lượt ấy xong rồi xem kết quả, không bấm lại."
const RUN_IN_PROGRESS_409 = { reason_code: "review_run_in_progress", detail: CAU_DANG_CHAY, error_code: "REVIEW_RUN_IN_PROGRESS" }
const STALE_409 = {
  reason_code: "review_session_stale",
  current_version: 5,
  detail: "Lần xét đã được sửa ở nơi khác sau khi bạn mở — hãy tải lại rồi làm lại.",
  error_code: "REVIEW_SESSION_STALE",
}
const CAU_NOT_DRAFT = "Lần xét không còn ở trạng thái nháp — không sửa điểm sàn, không chạy kiểm hồ sơ và không huỷ được nữa."

async function moChiTiet() {
  return renderApp(await resolveServerTree(ReviewSessionDetailPage({ params: Promise.resolve({ sessionId: "3" }) })))
}

async function bamKiem() {
  fireEvent.click(await screen.findByTestId("nut-run_evaluate"))
}

// ═══════════════════════════════════════ 202 + theo dõi lượt của mình ═══════════════════════════════════════
describe("M4 — 202 và theo dõi lượt (HĐ5: queued / running)", () => {
  it("202 done, Location khớp ⇒ gửi {kind, session_version = version E3}; mở M5 theo id; KHÔNG hỏi E7 / E8; E3 làm mới", async () => {
    const e3 = mayChuE3([json(sessionGia({ version: 7 }))])
    const than = mayChuE6([tao(runGia({ id: 12 }), { Location: LOC_12 })])
    const e7 = mayChuE7([json(pageGia([runSummaryGia()]))])
    const e8 = mayChuE8(12, [json(runGia({ id: 12 }))])
    await moChiTiet()
    await bamKiem()
    await waitFor(() => expect(push).toHaveBeenCalledWith(M5_12))
    expect(than).toEqual([{ kind: "evaluate", session_version: 7 }])
    expect(screen.getByTestId("kiem-xong")).toHaveTextContent(runDoneMessage(12))
    expect(screen.getByTestId("kiem-xem-ket-qua")).toHaveAttribute("href", M5_12)
    await waitFor(() => expect(e3.lan).toBe(2))
    await choLau()
    expect({ e7: e7.lan, e8: e8.lan }).toEqual({ e7: 0, e8: 0 })
    expect(push).toHaveBeenCalledTimes(1)
  })

  it("202 có Location LỆCH id trong thân ⇒ báo lỗi hợp đồng; KHÔNG mở M5, KHÔNG theo dõi", async () => {
    // Biến thể phá: bỏ đối chiếu Location ⇒ lượt `running` được theo dõi qua E8 ⇒ ĐỎ.
    mayChuE3([json(sessionGia())])
    mayChuE6([tao(chay("running"), { Location: "/api/admission-config/review-sessions/3/runs/13" })])
    const e8 = mayChuE8(12, [json(chay("running"))])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-loi")).toHaveTextContent(RUN_LOCATION_MISMATCH)
    await choLau()
    expect(e8.lan).toBe(0)
    expect(push).not.toHaveBeenCalled()
  })

  it("202 queued ⇒ băng 'Đang chờ chạy' → E8 'Đang chạy' → E8 done ⇒ mở M5; nút khoá khi theo dõi; DỪNG hỏi; làm mới khi xong", async () => {
    // Biến thể phá: không làm mới khi lượt xong qua một lần hỏi lại ⇒ E3 dừng ở 2 lần ⇒ ĐỎ.
    const e3 = mayChuE3([json(sessionGia())])
    mayChuE6([tao(chay("queued"))])
    const e8 = mayChuE8(12, [json(chay("running")), json(runGia({ id: 12 }))])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-trang-thai-luot")).toHaveTextContent(runTrackingLabel(12, "queued"))
    expect(screen.getByTestId("nut-run_evaluate")).toBeDisabled()
    await waitFor(() => expect(screen.getByTestId("kiem-trang-thai-luot")).toHaveTextContent(runTrackingLabel(12, "running")))
    await waitFor(() => expect(push).toHaveBeenCalledWith(M5_12))
    expect(e8.lan).toBe(2)
    await waitFor(() => expect(e3.lan).toBe(3))
    await choLau()
    expect(e8.lan).toBe(2)
  })

  it("202 running → E8 failed ⇒ 'Lượt kiểm hỏng — mã: …'; DỪNG hỏi; không mở M5; nút mở lại; làm mới khi xong", async () => {
    const e3 = mayChuE3([json(sessionGia())])
    mayChuE6([tao(chay("running"))])
    const e8 = mayChuE8(12, [json(chay("failed", { error_code: "engine_error" }))])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-hong")).toHaveTextContent(runFailedMessage("engine_error"))
    await waitFor(() => expect(e3.lan).toBe(3))
    await waitFor(() => expect(screen.getByTestId("nut-run_evaluate")).toBeEnabled())
    await choLau()
    expect(e8.lan).toBe(1)
    expect(push).not.toHaveBeenCalled()
  })

  it("trạng thái LẠ ⇒ coi như chưa xong (không đoán), hiện chữ máy chủ, theo dõi tiếp tới khi máy chủ trả done", async () => {
    mayChuE3([json(sessionGia())])
    mayChuE6([tao(chay("dang_xep_hang"))])
    const e8 = mayChuE8(12, [json(chay("trang_thai_moi")), json(runGia({ id: 12 }))])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-trang-thai-luot")).toHaveTextContent("dang_xep_hang")
    await waitFor(() => expect(push).toHaveBeenCalledWith(M5_12))
    expect(e8.lan).toBe(2)
  })

  it("lượt của mình quá TRẦN ⇒ ngừng tự hỏi đúng số lần theo kế hoạch, câu 'vẫn chưa xong' (không kết luận kẹt); 'Kiểm tra lại' ⇒ done ⇒ M5", async () => {
    keHoach.ownCeilingMs = 200
    const soLan = pollsUntilCeiling(keHoach, 200)
    mayChuE3([json(sessionGia())])
    mayChuE6([tao(chay("running"))])
    const e8 = mayChuE8(12, [...Array.from({ length: soLan }, () => json(chay("running"))), json(runGia({ id: 12 }))])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-het-tran-cau", {}, { timeout: 3000 })).toHaveTextContent("vẫn chưa xong")
    expect(e8.lan).toBe(soLan)
    await choLau()
    expect(e8.lan).toBe(soLan)
    expect(push).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTestId("kiem-kiem-tra-lai"))
    await waitFor(() => expect(push).toHaveBeenCalledWith(M5_12))
    expect(e8.lan).toBe(soLan + 1)
  })

  it("TỔ HỢP: 202 running → hỏi lại bị 429 ⇒ hiện lỗi, KHÔNG vẽ trạng thái cũ, DỪNG tự hỏi → 'Kiểm tra lại' ⇒ done ⇒ mở M5", async () => {
    // Biến thể phá: lỗi hỏi lại vẫn giữ pha theo dõi (vẽ "Đang chạy" cũ / hỏi tiếp) ⇒ ĐỎ.
    mayChuE3([json(sessionGia())])
    mayChuE6([tao(chay("running"))])
    const e8 = mayChuE8(12, [json({ detail: "Rate limit exceeded" }, 429), json(runGia({ id: 12 }))])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-trang-thai-luot")).toHaveTextContent(runTrackingLabel(12, "running"))
    expect(await screen.findByTestId("kiem-loi-theo-doi")).toHaveTextContent(RATE_LIMITED_MESSAGE)
    expect(screen.queryByTestId("kiem-trang-thai-luot")).toBeNull()
    expect(screen.queryByText(/Đang chạy/)).toBeNull()
    await choLau()
    expect(e8.lan).toBe(1)
    fireEvent.click(screen.getByTestId("kiem-kiem-tra-lai"))
    await waitFor(() => expect(push).toHaveBeenCalledWith(M5_12))
    expect(e8.lan).toBe(2)
    expect(screen.getByTestId("kiem-xong")).toHaveTextContent(runDoneMessage(12))
  })

  it("theo dõi KHÔNG dừng khi E3 tải lại lỗi (nhánh lỗi của màn): băng vẫn hiện, lượt xong vẫn mở M5", async () => {
    // Biến thể phá: trạng thái theo dõi nằm trong phần chỉ vẽ khi E3 có dữ liệu ⇒ nhánh lỗi tháo nó ⇒ không mở M5 ⇒ ĐỎ.
    mayChuE3([json(sessionGia()), json({ detail: "Rate limit exceeded" }, 429)])
    mayChuE6([tao(chay("running"))])
    const e8 = mayChuE8(12, [json(chay("running")), json(runGia({ id: 12 }))])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("lan-xet-loi")).toHaveTextContent(RATE_LIMITED_MESSAGE)
    await waitFor(() => expect(push).toHaveBeenCalledWith(M5_12))
    expect(screen.getByTestId("kiem-xong")).toBeInTheDocument()
    expect(e8.lan).toBe(2)
  })

  it("đang gửi E6 ⇒ băng 'Đang kiểm hồ sơ — …', nút khoá (không gửi lần hai)", async () => {
    mayChuE3([json(sessionGia())])
    const than = mayChuE6([
      async () => {
        await delay("infinite")
        return HttpResponse.json(runGia({ id: 12 }), { status: 202 })
      },
    ])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-dang-gui")).toHaveTextContent(RUN_SUBMITTING)
    expect(screen.getByTestId("nut-run_evaluate")).toBeDisabled()
    fireEvent.click(screen.getByTestId("nut-run_evaluate"))
    await choLau(80)
    expect(than).toHaveLength(1)
  })
})

// ═══════════════════════════════════════ chưa rõ đã chạy hay chưa ═══════════════════════════════════════
describe("M4 — mất kết nối / 502 / 504 ở E6 ⇒ tra E7, không bấm lại ngay", () => {
  it.each<[string, Tra]>([
    ["mất kết nối", () => HttpResponse.error()],
    ["502", json({ detail: "Bad Gateway" }, 502)],
    ["504", json({ detail: "Gateway Timeout" }, 504)],
  ])("E6 %s ⇒ tra E7: có lượt mới hơn mốc ⇒ theo dõi qua E8 ⇒ done ⇒ mở M5; KHÔNG gửi lại E6", async (_ten, tra) => {
    mayChuE3([json(sessionGia())])
    const than = mayChuE6([tra])
    const e7 = mayChuE7([json(pageGia([runSummaryGia({ id: 12, status: "done" }), runSummaryGia({ id: 11 })]))])
    const e8 = mayChuE8(12, [json(runGia({ id: 12 }))])
    await moChiTiet()
    await bamKiem()
    await waitFor(() => expect(push).toHaveBeenCalledWith(M5_12))
    expect(than).toHaveLength(1)
    expect({ e7: e7.lan, e8: e8.lan }).toEqual({ e7: 1, e8: 1 })
  })

  it("E7 KHÔNG có lượt mới hơn mốc (latest_run của E3) ⇒ 'Chưa có lượt kiểm mới. Có thể bấm lại.'; không hỏi E8; không tự gửi lại", async () => {
    // Biến thể phá: bỏ mốc ⇒ lượt 11 (cũ) bị coi là lượt mới ⇒ ĐỎ.
    mayChuE3([json(sessionGia())])
    const than = mayChuE6([() => HttpResponse.error()])
    const e7 = mayChuE7([
      async () => {
        await delay(80)
        return HttpResponse.json(pageGia([runSummaryGia({ id: 11 })]))
      },
    ])
    const e8 = mayChuE8(11, [json(runGia({ id: 11 }))])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-dang-kiem-tra")).toHaveTextContent(RUN_UNCERTAIN_CHECKING)
    expect(await screen.findByTestId("kiem-chua-co-luot-moi")).toHaveTextContent(RUN_NO_NEW)
    await waitFor(() => expect(screen.getByTestId("nut-run_evaluate")).toBeEnabled())
    expect(than).toHaveLength(1)
    expect({ e7: e7.lan, e8: e8.lan }).toEqual({ e7: 1, e8: 0 })
  })

  it("tra E7 bị 429 ⇒ hiện lỗi, KHÔNG kết luận; 'Kiểm tra lại' ⇒ E7 có lượt mới đang chạy ⇒ theo dõi E8 tới xong ⇒ M5", async () => {
    mayChuE3([json(sessionGia())])
    mayChuE6([json({ detail: "Gateway Timeout" }, 504)])
    const e7 = mayChuE7([
      json({ detail: "Rate limit exceeded" }, 429),
      json(pageGia([runSummaryGia({ id: 12, status: "running", finished_at: null, duration_ms: null, tab_counts: null })])),
    ])
    const e8 = mayChuE8(12, [json(chay("running")), json(runGia({ id: 12 }))])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-loi-theo-doi")).toHaveTextContent(RATE_LIMITED_MESSAGE)
    expect(screen.queryByTestId("kiem-chua-co-luot-moi")).toBeNull()
    fireEvent.click(screen.getByTestId("kiem-kiem-tra-lai"))
    await waitFor(() => expect(push).toHaveBeenCalledWith(M5_12))
    expect({ e7: e7.lan, e8: e8.lan }).toEqual({ e7: 2, e8: 2 })
  })
})

// ═══════════════════════════════════════ 409 lượt khác đang chạy ═══════════════════════════════════════
describe("M4 — 409 REVIEW_RUN_IN_PROGRESS: không bấm lại, chờ có trần", () => {
  it("câu máy chủ; nút khoá trong lúc chờ; lượt mới hơn mốc kết thúc ⇒ báo + liên kết (KHÔNG tự mở); E6 chỉ một lần; làm mới", async () => {
    const e3 = mayChuE3([json(sessionGia())])
    const than = mayChuE6([json(RUN_IN_PROGRESS_409, 409)])
    let moCong: () => void = () => undefined
    const cong = new Promise<void>((r) => {
      moCong = () => r()
    })
    const e7 = mayChuE7([
      async () => {
        await cong
        return HttpResponse.json(pageGia([runSummaryGia({ id: 12, status: "done" }), runSummaryGia({ id: 11 })]))
      },
    ])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-cau-may-chu")).toHaveTextContent(CAU_DANG_CHAY)
    expect(screen.getByTestId("kiem-cho-luot-khac")).toHaveTextContent(RUN_OTHER_WAITING)
    await waitFor(() => expect(e3.lan).toBe(2))
    await waitFor(() => expect(screen.queryByTestId("lan-xet-dang-tai-lai")).toBeNull())
    expect(screen.getByTestId("nut-run_evaluate")).toBeDisabled()
    moCong()
    expect(await screen.findByTestId("kiem-luot-khac-xong")).toHaveTextContent(runOtherDone(12, "done"))
    expect(screen.getByTestId("kiem-xem-ket-qua")).toHaveAttribute("href", M5_12)
    expect(than).toHaveLength(1)
    expect(e7.lan).toBe(1)
    expect(push).not.toHaveBeenCalled()
    await waitFor(() => expect(e3.lan).toBe(3))
    await waitFor(() => expect(screen.getByTestId("nut-run_evaluate")).toBeEnabled())
  })

  it("TỔ HỢP: E6 409 REVIEW_RUN_IN_PROGRESS → theo dõi E7 → hết TRẦN ⇒ 'Lượt của người khác chưa xong — thử lại sau.'; DỪNG hỏi; E6 một lần", async () => {
    // Biến thể phá: chờ không trần ⇒ không bao giờ có câu ⇒ ĐỎ; tự gửi lại E6 ⇒ ĐỎ ở số thân gửi.
    keHoach.otherCeilingMs = 200
    const soLan = pollsUntilCeiling(keHoach, 200)
    mayChuE3([json(sessionGia())])
    const than = mayChuE6([json(RUN_IN_PROGRESS_409, 409)])
    const e7 = mayChuE7([json(pageGia([runSummaryGia({ id: 11 })]))])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-cho-luot-khac")).toHaveTextContent(RUN_OTHER_WAITING)
    expect(await screen.findByTestId("kiem-het-tran-cau", {}, { timeout: 3000 })).toHaveTextContent(RUN_OTHER_CEILING)
    expect(e7.lan).toBe(soLan)
    await choLau(200)
    expect(e7.lan).toBe(soLan)
    expect(than).toHaveLength(1)
    await waitFor(() => expect(screen.getByTestId("nut-run_evaluate")).toBeEnabled())
  })
})

// ═══════════════════════════════════════ lỗi E6 khác ═══════════════════════════════════════
describe("M4 — lỗi E6 khác (mọi lỗi: không có lượt ⇒ không theo dõi)", () => {
  it("409 REVIEW_SESSION_STALE ⇒ câu riêng, E3 tải lại; bấm lại gửi version MỚI", async () => {
    const e3 = mayChuE3([json(sessionGia({ version: 2 })), json(sessionGia({ version: 5 }))])
    const than = mayChuE6([json(STALE_409, 409), tao(runGia({ id: 12 }))])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-loi")).toHaveTextContent(RUN_STALE)
    await waitFor(() => expect(e3.lan).toBe(2))
    await waitFor(() => expect(screen.getByTestId("nut-run_evaluate")).toBeEnabled())
    fireEvent.click(screen.getByTestId("nut-run_evaluate"))
    await waitFor(() => expect(push).toHaveBeenCalledWith(M5_12))
    expect(than).toEqual([
      { kind: "evaluate", session_version: 2 },
      { kind: "evaluate", session_version: 5 },
    ])
  })

  it("409 REVIEW_SESSION_NOT_DRAFT ⇒ câu máy chủ; E3 tải lại ⇒ nút tự biến mất theo available_actions", async () => {
    const e3 = mayChuE3([json(sessionGia()), json(sessionDaHuyGia())])
    mayChuE6([
      json({ reason_code: "review_session_not_draft", status: "cancelled", detail: CAU_NOT_DRAFT, error_code: "REVIEW_SESSION_NOT_DRAFT" }, 409),
    ])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-loi")).toHaveTextContent(CAU_NOT_DRAFT)
    await waitFor(() => expect(screen.queryByTestId("nut-run_evaluate")).toBeNull())
    expect(e3.lan).toBe(2)
  })

  it.each<[string, string]>([
    [
      "fee_gate_mode_invalid",
      "Cấu hình chế độ cổng học phí trên máy chủ không hợp lệ — không chạy kiểm hồ sơ. Báo quản trị hệ thống.",
    ],
    [
      "residence_proof_doc_type_missing",
      "Máy chủ chưa cấu hình loại giấy xác nhận thông tin về cư trú — không chạy kiểm hồ sơ. Báo quản trị hệ thống.",
    ],
  ])("503 REVIEW_CONFIG_UNAVAILABLE / %s ⇒ câu máy chủ NGUYÊN VĂN; không theo dõi", async (reason, cau) => {
    mayChuE3([json(sessionGia())])
    mayChuE6([json({ reason_code: reason, detail: cau, error_code: "REVIEW_CONFIG_UNAVAILABLE" }, 503)])
    const e7 = mayChuE7([json(pageGia([]))])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-loi")).toHaveTextContent(cau)
    await choLau()
    expect(e7.lan).toBe(0)
  })

  it("503 PRIORITY_RATE_NOT_CONFIGURED ⇒ câu máy chủ + danh sách missing_codes + liên kết 'Cấu hình Ưu tiên'", async () => {
    const cau = "Chưa có mức điểm ưu tiên đang áp dụng cho đối tượng 01, 06 năm 2026. Cấu hình mức rồi công bố lại."
    mayChuE3([json(sessionGia())])
    mayChuE6([
      json(
        {
          table: "priority_object_config",
          academic_year: 2026,
          missing_codes: ["01", "06"],
          detail: cau,
          error_code: "PRIORITY_RATE_NOT_CONFIGURED",
        },
        503,
      ),
    ])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-loi")).toHaveTextContent(cau)
    expect(screen.getByTestId("kiem-ma-thieu")).toHaveTextContent("Mã còn thiếu: 01, 06")
    expect(screen.getByTestId("kiem-lien-ket-uu-tien")).toHaveAttribute("href", "/admin/priority-config")
  })

  it("503 đóng băng ⇒ câu đóng băng", async () => {
    mayChuE3([json(sessionGia())])
    mayChuE6([json({ detail: "Admission frozen", code: "ADMISSION_FROZEN", frozen_prefix: "/api/admission-config" }, 503)])
    await moChiTiet()
    await bamKiem()
    expect(await screen.findByTestId("kiem-loi")).toHaveTextContent(FROZEN_MESSAGE)
  })
})

// ═══════════════════════════════════════ danh sách lượt kiểm (E7) ═══════════════════════════════════════
describe("M4 — danh sách lượt kiểm (E7)", () => {
  it("mặc định ĐÓNG (không gọi E7); mở ⇒ E7 trang 1 cỡ 20; dòng hiện nhãn / số máy chủ; trạng thái lạ ⇒ chữ máy chủ; liên kết M5", async () => {
    mayChuE3([json(sessionGia())])
    const thamSo: string[] = []
    server.use(
      http.get(`${RS}/3/runs`, ({ request }) => {
        thamSo.push(new URL(request.url).search)
        return HttpResponse.json(
          pageGia([
            runSummaryGia({ id: 12, config_changed_since_run: true }),
            runSummaryGia({ id: 10, status: "trang_thai_moi", finished_at: null, duration_ms: null, tab_counts: null }),
          ]),
        )
      }),
    )
    await moChiTiet()
    await screen.findByTestId("luot-kiem")
    await choLau(50)
    expect(thamSo).toEqual([])
    fireEvent.click(screen.getByTestId("luot-kiem-mo"))
    expect(await screen.findByTestId("luot-12")).toBeInTheDocument()
    expect(thamSo).toEqual(["?page=1&page_size=20"])
    expect(screen.getByTestId("luot-12-trang-thai")).toHaveTextContent("Xong")
    expect(screen.getByTestId("luot-12-cau-hinh-doi")).toHaveTextContent(CONFIG_CHANGED_BADGE)
    expect(screen.getByTestId("luot-12-thoi-luong")).toHaveTextContent("14 giây")
    expect(screen.getByTestId("luot-12-nguoi-chay")).toHaveTextContent("Người dùng #1")
    expect(screen.getByTestId("luot-12-so-nhom")).toHaveTextContent(
      "Đạt — máy đề xuất 120 · Cần Ban thư ký quyết 8 · Chưa đạt — chờ lần sau 31 · Chưa đủ điều kiện 57",
    )
    expect(screen.getByTestId("luot-12-bo-luat")).toHaveTextContent("gd2b-1")
    expect(screen.getByTestId("luot-12-mo")).toHaveAttribute("href", M5_12)
    expect(screen.getByTestId("luot-10-trang-thai")).toHaveTextContent("trang_thai_moi")
    expect(screen.getByTestId("luot-10-xong")).toHaveTextContent("—")
    expect(screen.getByTestId("luot-10-so-nhom")).toHaveTextContent("—")
    expect(screen.queryByTestId("luot-10-cau-hinh-doi")).toBeNull()
  })

  it("đính chính 2 §1: E7 tải lại bị 429 ⇒ hiện LỖI, KHÔNG vẽ dòng cũ", async () => {
    mayChuE3([json(sessionGia())])
    mayChuE7([json(pageGia([runSummaryGia({ id: 12 })])), json({ detail: "Rate limit exceeded" }, 429)])
    await moChiTiet()
    fireEvent.click(await screen.findByTestId("luot-kiem-mo"))
    await screen.findByTestId("luot-12")
    fireEvent.click(screen.getByTestId("luot-kiem-tai-lai"))
    expect(await screen.findByTestId("luot-kiem-loi")).toHaveTextContent(RATE_LIMITED_MESSAGE)
    expect(screen.queryByTestId("luot-12")).toBeNull()
  })

  it("phân trang: 'Trang sau' ⇒ gửi page=2, hiện dòng của trang 2", async () => {
    mayChuE3([json(sessionGia())])
    const trangGui: number[] = []
    server.use(
      http.get(`${RS}/3/runs`, ({ request }) => {
        const p = Number(new URL(request.url).searchParams.get("page"))
        trangGui.push(p)
        return HttpResponse.json(pageGia([runSummaryGia({ id: p === 1 ? 30 : 10 })], { total: 21, page: p, total_pages: 2 }))
      }),
    )
    await moChiTiet()
    fireEvent.click(await screen.findByTestId("luot-kiem-mo"))
    await screen.findByTestId("luot-30")
    fireEvent.click(screen.getByTestId("luot-trang-sau"))
    expect(await screen.findByTestId("luot-10")).toBeInTheDocument()
    expect(screen.queryByTestId("luot-30")).toBeNull()
    expect(trangGui).toEqual([1, 2])
  })

  it("rỗng ⇒ 'Chưa có lượt kiểm nào.'", async () => {
    mayChuE3([json(sessionGia({ latest_run: null, latest_done_run_id: null }))])
    mayChuE7([json(pageGia([]))])
    await moChiTiet()
    fireEvent.click(await screen.findByTestId("luot-kiem-mo"))
    expect(await screen.findByTestId("luot-kiem-rong")).toHaveTextContent(RUNS_EMPTY)
  })

  it("M2: có lượt xong ⇒ liên kết tới M5 của latest_done_run_id (số máy chủ, không lấy latest_run.id)", async () => {
    mayChuE3([json(sessionGia({ latest_done_run_id: 9 }))])
    await moChiTiet()
    const lk = await screen.findByTestId("lan-xet-xem-ket-qua")
    expect(lk).toHaveAttribute("href", "/review-sessions/3/runs/9")
    expect(lk).toHaveTextContent(latestDoneRunLink(9))
  })
})
