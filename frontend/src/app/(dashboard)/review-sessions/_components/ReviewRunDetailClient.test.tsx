/**
 * GĐ2-B F3 — M5 (một lượt kiểm): đầu trang + băng cảnh báo + thẻ "Chỉ tiêu tham khảo" + "Điểm sàn đã dùng", dựng qua ĐÚNG
 * `[sessionId]/runs/[runId]/page.tsx` (máy chủ giả MSW theo HĐ4 §3.3; QueryClient mang mặc định thật của ứng dụng).
 *
 * Khoá (thiết kế §3.6, §6.2 F3; đính chính 2 §1):
 *  - id trên URL kiểm dạng ở trang (sai ⇒ 404 của Next, không gọi máy chủ);
 *  - đầu trang từ E8 + E3 (số thứ tự lần xét); băng CHỈ theo cờ / id máy chủ: "lượt cũ" (id ≠ `latest_done_run_id`),
 *    `config_changed_since_run`, `summary.warnings` (lạ ⇒ câu chung có mã);
 *  - số ở thẻ "Chỉ tiêu tham khảo" là NGUYÊN số máy chủ — KHÔNG tự tính "còn lại" (dữ liệu thử cố ý cho `remaining` lệch phép trừ);
 *    `would_exceed` CHỈ cảnh báo; chỉ tiêu `null` ≠ `0`;
 *  - tải lỗi (kể cả 429) ⇒ hiện LỖI, không vẽ đầu trang cũ.
 * Dữ liệu giả.
 */
import { fireEvent, screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { formatDateTimeVN } from "@/lib/document-review/messages"
import {
  OLD_RUN_NOTE,
  RATE_LIMITED_MESSAGE,
  RUN_CONFIG_CHANGED_BANNER,
  RUN_NOT_DONE_NOTE,
  RUN_NOT_FOUND_MESSAGE,
  RUN_NO_SUMMARY,
  runFailedMessage,
} from "@/lib/review-sessions/messages"
import { server } from "@/test/mocks/server"
import { chanRequestRo } from "@/test/review-sessions-msw"
import { RS, runGia, sessionGia } from "@/test/mocks/review-sessions-data"
import { renderApp } from "@/test/review-sessions-render"
import { resolveServerTree } from "@/test/server-component"

import ReviewRunDetailPage from "../[sessionId]/runs/[runId]/page"

const { notFound } = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND")
  }),
}))
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/review-sessions/3/runs/11",
  notFound,
}))

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

async function moLuot(sessionId = "3", runId = "11") {
  return renderApp(await resolveServerTree(ReviewRunDetailPage({ params: Promise.resolve({ sessionId, runId }) })))
}

/** Chỉ tiêu tham khảo giả — cố ý: `remaining` LỆCH phép trừ chỉ tiêu − đã dùng (giao diện phải hiện số máy chủ). */
const QUOTA_VIEW = {
  majors: [
    {
      offering_academic_info_id: 41,
      offering_id: 12,
      major_code: "<mã>",
      major_name: "<tên ngành>",
      offering_type: "<loại hình>",
      group_id: 5,
      group_code: "N1",
      annual_admission_quota: 30,
      floor_score: "15.00",
      used_publish: 2,
      used_approved: 1,
      used: 3,
      remaining: 7,
      state: "ok",
      candidates: 40,
      auto: 30,
      needs_decision: 2,
      offering_inactive: false,
      major_inactive: true,
    },
    {
      offering_academic_info_id: 42,
      offering_id: 13,
      major_code: "<mã 2>",
      major_name: "<tên ngành 2>",
      offering_type: "<loại hình>",
      group_id: null,
      group_code: null,
      annual_admission_quota: null,
      floor_score: null,
      used_publish: 0,
      used_approved: 0,
      used: 0,
      remaining: null,
      state: "quota_not_configured",
      candidates: 3,
      auto: 0,
      needs_decision: 0,
      offering_inactive: true,
      major_inactive: false,
    },
    {
      offering_academic_info_id: 43,
      offering_id: 14,
      major_code: "<mã 3>",
      major_name: "<tên ngành 3>",
      offering_type: "<loại hình>",
      group_id: 6,
      group_code: "N2",
      annual_admission_quota: 0,
      floor_score: null,
      used_publish: 0,
      used_approved: 0,
      used: 0,
      remaining: 0,
      state: "quota_closed",
      candidates: 1,
      auto: 0,
      needs_decision: 0,
      offering_inactive: false,
      major_inactive: false,
    },
  ],
  groups: [
    {
      group_id: 5,
      code: "N1",
      name: "<nhóm>",
      ceiling: 100,
      used_publish: 2,
      used_approved: 1,
      used: 3,
      auto_in_run: 30,
      remaining_after_auto: -2,
      would_exceed: true,
    },
    {
      group_id: 6,
      code: "N2",
      name: "<nhóm 2>",
      ceiling: 50,
      used_publish: 0,
      used_approved: 0,
      used: 0,
      auto_in_run: 0,
      remaining_after_auto: 50,
      would_exceed: false,
    },
  ],
}

// Chặn request rò (đối chiếu CI F4; quyết định điều phối 25-11): request không handler ⇒ ghi lại, máy giả trả 500 (KHÔNG ra mạng), ca ĐỎ ở cuối ca (src/test/setup.ts).
chanRequestRo()

/**
 * F4: thẻ "Kết quả" (mặc định) của M5 gọi E9 khi lượt `done` — handler MẶC ĐỊNH (trang rỗng) cho mọi ca của tệp này. Thiếu nó, E9 là
 * request rò: đối chiếu CI F4 đo được request đi ra mạng thật rồi worker sập ở chính tệp này. Ca nào cần dòng E9 cụ thể thì tự
 * `server.use` (đặt sau ⇒ được ưu tiên).
 */
beforeEach(() => {
  server.use(
    http.get(`${RS}/3/runs/:runId/rows`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50, total_pages: 0, tab_counts: { auto: 0 } }),
    ),
  )
})

describe("M5 — trang lượt kiểm: id trên URL", () => {
  it.each<[string, string]>([
    ["3", "abc"],
    ["3", "0"],
    ["x", "11"],
  ])("lần xét %j / lượt %j ⇒ 404 của Next (không gọi máy chủ)", async (sessionId, runId) => {
    const e8 = mayChuGet(`${RS}/3/runs/11`, [json(runGia())])
    const e3 = mayChuGet(`${RS}/3`, [json(sessionGia())])
    await expect(resolveServerTree(ReviewRunDetailPage({ params: Promise.resolve({ sessionId, runId }) }))).rejects.toThrow(
      "NEXT_NOT_FOUND",
    )
    expect({ e3: e3.lan, e8: e8.lan }).toEqual({ e3: 0, e8: 0 })
  })
})

describe("M5 — đầu trang, băng cảnh báo", () => {
  it("đầu trang 'Lượt kiểm #11 — lần xét số 3 năm 2026' + trạng thái / xong / thời lượng / người chạy / bộ luật / cổng học phí / ảnh chụp; thẻ 'Kết quả' = số máy chủ", async () => {
    mayChuGet(`${RS}/3`, [json(sessionGia())])
    mayChuGet(`${RS}/3/runs/11`, [json(runGia())])
    await moLuot()
    expect(await screen.findByTestId("luot-tieu-de")).toHaveTextContent("Lượt kiểm #11 — lần xét số 3 năm 2026")
    expect(screen.getByTestId("luot-trang-thai")).toHaveTextContent("Xong")
    expect(screen.getByTestId("luot-xong")).toHaveTextContent(`Xong lúc ${formatDateTimeVN("2026-11-24T02:12:14Z")}`)
    expect(screen.getByTestId("luot-thoi-luong")).toHaveTextContent("Thời lượng 14 giây")
    expect(screen.getByTestId("luot-nguoi-chay")).toHaveTextContent("Chạy bởi Người dùng #1")
    expect(screen.getByTestId("luot-bo-luat")).toHaveTextContent("Bộ luật gd2b-1")
    expect(screen.getByTestId("luot-cong-hoc-phi")).toHaveTextContent(
      "Cổng học phí lúc chạy: Phải đóng đủ (hoặc được miễn) học phí học kỳ 1",
    )
    expect(screen.getByTestId("luot-anh-chup")).toHaveTextContent(`Ảnh chụp lúc ${formatDateTimeVN("2026-11-24T02:12:00Z")}`)
    // F4: thẻ "Kết quả" = bốn tab, số trên tab là `summary.tab_counts` của máy chủ (thay dòng tóm tắt + câu "đợt sau" của F3).
    expect(screen.getByTestId("kq-tab-auto")).toHaveTextContent("Đạt — máy đề xuất 120")
    expect(screen.getByTestId("kq-tab-needs_decision")).toHaveTextContent("Cần Ban thư ký quyết 8")
    expect(screen.getByTestId("kq-tab-not_passed")).toHaveTextContent("Chưa đạt — chờ lần sau 31")
    expect(screen.getByTestId("kq-tab-ineligible")).toHaveTextContent("Chưa đủ điều kiện 57")
    expect(screen.getAllByTestId("ve-lan-xet")[0]).toHaveAttribute("href", "/review-sessions/3")
    expect(screen.queryByTestId("bang-luot-cu")).toBeNull()
    expect(screen.queryByTestId("bang-luot-cau-hinh-doi")).toBeNull()
  })

  it("S3 (phụ lục S3/S7): 'Chạy bởi' hiện HỌ TÊN máy chủ trả (E8 `requested_by_full_name`)", async () => {
    // Biến thể phá: đầu M5 gọi userRef chỉ với id ⇒ ĐỎ.
    mayChuGet(`${RS}/3`, [json(sessionGia())])
    mayChuGet(`${RS}/3/runs/11`, [json(runGia({ requested_by_user_id: 2, requested_by_full_name: "Người Chạy Giả" }))])
    await moLuot()
    expect(await screen.findByTestId("luot-nguoi-chay")).toHaveTextContent("Chạy bởi Người Chạy Giả")
    expect(screen.getByTestId("luot-nguoi-chay")).not.toHaveTextContent("#")
  })

  it.each<[string, number, boolean]>([
    ["là lượt xong mới nhất", 11, false],
    ["KHÔNG phải lượt xong mới nhất", 12, true],
  ])("lượt đã xong %s (latest_done_run_id = %i) ⇒ băng 'lượt cũ': %s", async (_ten, latestDone, coBang) => {
    mayChuGet(`${RS}/3`, [json(sessionGia({ latest_done_run_id: latestDone }))])
    mayChuGet(`${RS}/3/runs/11`, [json(runGia())])
    await moLuot()
    await screen.findByTestId("luot-tieu-de")
    if (coBang) expect(screen.getByTestId("bang-luot-cu")).toHaveTextContent(OLD_RUN_NOTE)
    else expect(screen.queryByTestId("bang-luot-cu")).toBeNull()
  })

  it("cờ máy chủ: config_changed ⇒ băng; summary.warnings ⇒ nhãn Phụ lục A, quota_closed_present nhấn mạnh, mã lạ ⇒ câu chung có mã", async () => {
    mayChuGet(`${RS}/3`, [json(sessionGia())])
    mayChuGet(`${RS}/3/runs/11`, [
      json(
        runGia({
          config_changed_since_run: true,
          summary: {
            rows_total: 216,
            pool_total: 216,
            tab_counts: { auto: 120, needs_decision: 8, not_passed: 31, ineligible: 57 },
            reason_counts: {},
            flag_counts: {},
            warnings: ["quota_table_not_locked", "quota_closed_present", "canh_bao_moi"],
          },
        }),
      ),
    ])
    await moLuot()
    expect(await screen.findByTestId("bang-luot-cau-hinh-doi")).toHaveTextContent(RUN_CONFIG_CHANGED_BANNER)
    expect(screen.getByTestId("canh-bao-quota_table_not_locked")).toHaveTextContent("Bảng chỉ tiêu năm chưa khoá lúc chạy")
    expect(screen.getByTestId("canh-bao-quota_closed_present")).toHaveTextContent("Có ngành chỉ tiêu 0")
    expect(screen.getByTestId("canh-bao-quota_closed_present")).toHaveClass("text-destructive")
    expect(screen.getByTestId("canh-bao-canh_bao_moi")).toHaveTextContent("Cảnh báo khác (mã: canh_bao_moi)")
  })

  it("lượt chưa xong (running) ⇒ băng 'chưa xong', KHÔNG băng 'lượt cũ'; thẻ 'Kết quả' / 'Chỉ tiêu tham khảo' ⇒ 'Chưa có'", async () => {
    mayChuGet(`${RS}/3`, [json(sessionGia())])
    mayChuGet(`${RS}/3/runs/12`, [
      json(runGia({ id: 12, status: "running", finished_at: null, duration_ms: null, summary: null, quota_view: null })),
    ])
    await moLuot("3", "12")
    expect(await screen.findByTestId("bang-luot-chua-xong")).toHaveTextContent(RUN_NOT_DONE_NOTE)
    expect(screen.queryByTestId("bang-luot-cu")).toBeNull()
    expect(screen.getByTestId("luot-trang-thai")).toHaveTextContent("Đang chạy")
    expect(screen.getByTestId("the-noi-dung-ket-qua")).toHaveTextContent(RUN_NO_SUMMARY)
    fireEvent.click(screen.getByTestId("the-chi-tieu"))
    expect(screen.getByTestId("cttk-chua-co")).toHaveTextContent(RUN_NO_SUMMARY)
  })

  it("lượt hỏng ⇒ 'Lượt kiểm hỏng — mã: …' (mã máy chủ)", async () => {
    mayChuGet(`${RS}/3`, [json(sessionGia())])
    mayChuGet(`${RS}/3/runs/12`, [
      json(runGia({ id: 12, status: "failed", error_code: "engine_error", summary: null, quota_view: null })),
    ])
    await moLuot("3", "12")
    expect(await screen.findByTestId("bang-luot-hong")).toHaveTextContent(runFailedMessage("engine_error"))
  })
})

describe("M5 — thẻ tham khảo: NGUYÊN số máy chủ", () => {
  it("'Chỉ tiêu tham khảo': chỉ tiêu null ≠ 0; đã dùng kèm công bố / Phê duyệt cũ; còn lại = remaining máy chủ (không tự trừ); còn sau đề xuất âm; 'Sẽ vượt trần' chỉ cảnh báo", async () => {
    // Biến thể phá: tự tính còn lại = chỉ tiêu − đã dùng ⇒ hiện 27 thay vì 7 ⇒ ĐỎ.
    mayChuGet(`${RS}/3`, [json(sessionGia())])
    mayChuGet(`${RS}/3/runs/11`, [json(runGia({ quota_view: QUOTA_VIEW }))])
    await moLuot()
    fireEvent.click(await screen.findByTestId("the-chi-tieu"))
    expect(screen.getByTestId("cttk-41-chi-tieu")).toHaveTextContent(/^30$/)
    expect(screen.getByTestId("cttk-42-chi-tieu")).toHaveTextContent("Chưa cấu hình")
    expect(screen.getByTestId("cttk-43-chi-tieu")).toHaveTextContent("0 — đóng tuyệt đối")
    expect(screen.getByTestId("cttk-41-da-dung")).toHaveTextContent("3theo công bố 2, theo “Phê duyệt” cũ 1")
    expect(screen.getByTestId("cttk-41-con-lai")).toHaveTextContent(/^7$/)
    expect(screen.getByTestId("cttk-42-con-lai")).toHaveTextContent(/^—$/)
    expect(screen.getByTestId("cttk-43-con-lai")).toHaveTextContent(/^0$/)
    expect(screen.getByTestId("cttk-41-san")).toHaveTextContent("15,00")
    expect(screen.getByTestId("cttk-42-san")).toHaveTextContent(/^—$/)
    expect(screen.getByTestId("cttk-41-trang-thai")).toHaveTextContent("Có sàn")
    expect(screen.getByTestId("cttk-42-trang-thai")).toHaveTextContent("Chưa có chỉ tiêu")
    expect(screen.getByTestId("cttk-41-nganh-ngung")).toHaveTextContent("Ngành đang ngừng")
    expect(screen.getByTestId("cttk-42-loai-hinh-ngung")).toHaveTextContent("Loại hình đang ngừng")
    expect(screen.getByTestId("cttk-nhom-5-con-sau")).toHaveTextContent("-2")
    expect(screen.getByTestId("cttk-nhom-5-vuot-tran")).toHaveTextContent("Sẽ vượt trần")
    expect(screen.queryByTestId("cttk-nhom-6-vuot-tran")).toBeNull()
    // Chỉ cảnh báo: không băng lỗi, các thẻ khác vẫn mở được.
    expect(screen.queryByTestId("luot-loi")).toBeNull()
    fireEvent.click(screen.getByTestId("the-diem-san"))
    expect(screen.getByTestId("san-da-dung")).toBeInTheDocument()
  })

  it("'Điểm sàn đã dùng' = inputs.floors (ảnh chụp lúc chạy): nhãn ngành ghép theo id với quota_view; không có ⇒ 'Học vụ #id'; điểm dấu phẩy", async () => {
    mayChuGet(`${RS}/3`, [json(sessionGia())])
    const g = runGia({ quota_view: QUOTA_VIEW }) as { inputs: Record<string, unknown> }
    mayChuGet(`${RS}/3/runs/11`, [
      json(
        runGia({
          quota_view: QUOTA_VIEW,
          inputs: {
            ...g.inputs,
            floors: [
              { offering_academic_info_id: 41, floor_score: "15.00" },
              { offering_academic_info_id: 99, floor_score: "16.50" },
            ],
          },
        }),
      ),
    ])
    await moLuot()
    fireEvent.click(await screen.findByTestId("the-diem-san"))
    expect(screen.getByTestId("san-da-dung-41")).toHaveTextContent("<mã> — <tên ngành>")
    expect(screen.getByTestId("san-da-dung-41")).toHaveTextContent("15,00")
    expect(screen.getByTestId("san-da-dung-99")).toHaveTextContent("Học vụ #99")
    expect(screen.getByTestId("san-da-dung-99")).toHaveTextContent("16,50")
  })
})

describe("M5 — lỗi tải", () => {
  it("E8 404 review_run_not_found ⇒ 'Không tìm thấy lượt kiểm.' + liên kết về lần xét", async () => {
    mayChuGet(`${RS}/3`, [json(sessionGia())])
    mayChuGet(`${RS}/3/runs/11`, [
      json({ reason_code: "review_run_not_found", detail: "x", error_code: "RESOURCE_NOT_FOUND" }, 404),
    ])
    await moLuot()
    expect(await screen.findByTestId("luot-loi")).toHaveTextContent(RUN_NOT_FOUND_MESSAGE)
    expect(screen.getByTestId("ve-lan-xet")).toHaveAttribute("href", "/review-sessions/3")
  })

  it("đính chính 2 §1: tải lại bị 429 sau khi đã có dữ liệu ⇒ hiện LỖI, KHÔNG vẽ đầu trang / bảng cũ", async () => {
    // Biến thể phá: đọc `data` trước `isError` ⇒ đầu trang cũ còn ⇒ ĐỎ.
    mayChuGet(`${RS}/3`, [json(sessionGia())])
    mayChuGet(`${RS}/3/runs/11`, [json(runGia()), json({ detail: "Rate limit exceeded" }, 429)])
    await moLuot()
    await screen.findByTestId("luot-tieu-de")
    fireEvent.click(screen.getByTestId("luot-tai-lai"))
    expect(await screen.findByTestId("luot-loi")).toHaveTextContent(RATE_LIMITED_MESSAGE)
    expect(screen.queryByTestId("luot-tieu-de")).toBeNull()
  })
})
