/**
 * GĐ2-B F0 — bảng lỗi chung (thiết kế §5) chạy THEO BẢNG: mỗi dòng HĐ4 §5 một ca (thân lỗi đúng hình máy chủ
 * `admission_review_errors.py` + `exception_handlers.py`), cộng đóng băng HAI tầng qua khoá `code`, 403 không lộ câu Casbin,
 * mất kết nối ở route ghi ⇒ "chưa rõ". Rẽ nhánh theo MÃ, không theo chữ `detail`.
 *
 * Cùng tệp: nhãn trạng thái / hành động / tab — giá trị lạ hiện chữ máy chủ hoặc bị bỏ qua (HĐ4 §1.8).
 */
import { AxiosError, AxiosHeaders } from "axios"
import { describe, expect, it } from "vitest"
import { z } from "zod"

import { E4_BAD_MEMBER_BODY } from "@/test/mocks/review-sessions-data"

import {
  BAD_RESPONSE_MESSAGE,
  FORBIDDEN_MESSAGE,
  FROZEN_MESSAGE,
  INVALID_MESSAGE,
  RATE_LIMITED_MESSAGE,
  READ_NETWORK_MESSAGE,
  RUN_NOT_FOUND_MESSAGE,
  SERVER_ERROR_MESSAGE,
  SESSION_NOT_FOUND_MESSAGE,
  UNAUTHORIZED_MESSAGE,
  WRITE_UNCERTAIN_MESSAGE,
  describeReviewSessionError,
  knownSessionActions,
  quotaTableHref,
  roundStateLabel,
  sessionStatusLabel,
  tabCountEntries,
  type ReviewErrorKind,
} from "./messages"

function loi(status: number, data: unknown): AxiosError {
  return new AxiosError("x", "ERR", undefined, undefined, {
    status,
    statusText: "",
    headers: {},
    config: { headers: new AxiosHeaders() },
    data,
  })
}

function matKetNoi(): AxiosError {
  return new AxiosError("Network Error", "ERR_NETWORK", { headers: new AxiosHeaders() })
}

/** Câu `detail` GIẢ của máy chủ — ca "mã đã biết" phải hiện NGUYÊN câu này. */
const D = (s: string) => `Câu máy chủ: ${s}`

interface Dong {
  ten: string
  loi: AxiosError
  kind: ReviewErrorKind
  message: string
}

/** HĐ4 §5 — từng dòng (thứ tự của hợp đồng). */
const BANG_HD4_5: Dong[] = [
  {
    ten: "400 review_round_invalid (E1)",
    loi: loi(400, { reason_code: "review_round_invalid", admission_round_id: 7, detail: D("đợt"), error_code: "VALIDATION_ERROR" }),
    kind: "known",
    message: D("đợt"),
  },
  {
    // Phụ lục HĐ4 E10 §2 (S1, owner G1 (c)) — thiếu mã này trong bộ nhận diện ⇒ "Có lỗi (mã: VALIDATION_ERROR)." (rà F01-5).
    ten: "400 review_round_archived (E1, phụ lục S1 — đợt đã lưu trữ)",
    loi: loi(400, {
      reason_code: "review_round_archived",
      admission_round_id: 9,
      detail:
        "Đợt tuyển sinh này đã lưu trữ — không tạo lần xét trên đợt đã lưu trữ. Khôi phục đợt hoặc chọn đợt khác rồi làm lại.",
      error_code: "VALIDATION_ERROR",
    }),
    kind: "known",
    message:
      "Đợt tuyển sinh này đã lưu trữ — không tạo lần xét trên đợt đã lưu trữ. Khôi phục đợt hoặc chọn đợt khác rồi làm lại.",
  },
  {
    ten: "400 review_floor_duplicate (E4)",
    loi: loi(400, {
      reason_code: "review_floor_duplicate",
      duplicate_offering_academic_info_ids: [41],
      detail: D("trùng"),
      error_code: "VALIDATION_ERROR",
    }),
    kind: "known",
    message: D("trùng"),
  },
  {
    ten: "400 review_floor_bad_member (E4, ví dụ HĐ4 §9)",
    loi: loi(400, E4_BAD_MEMBER_BODY),
    kind: "known",
    message: "Có học vụ không thuộc năm 2026 (không tồn tại, đã xoá, hoặc khác năm).",
  },
  { ten: "401", loi: loi(401, { detail: "Not authenticated" }), kind: "unauthorized", message: UNAUTHORIZED_MESSAGE },
  {
    ten: "403 PERMISSION_DENIED (câu Casbin tiếng Anh KHÔNG hiện)",
    loi: loi(403, { detail: "Permission denied: admin role required for /api/admission-config", error_code: "PERMISSION_DENIED" }),
    kind: "forbidden",
    message: FORBIDDEN_MESSAGE,
  },
  {
    ten: "404 review_session_not_found",
    loi: loi(404, { reason_code: "review_session_not_found", detail: D("404"), error_code: "RESOURCE_NOT_FOUND" }),
    kind: "not_found",
    message: SESSION_NOT_FOUND_MESSAGE,
  },
  {
    ten: "404 review_run_not_found",
    loi: loi(404, { reason_code: "review_run_not_found", detail: D("404"), error_code: "RESOURCE_NOT_FOUND" }),
    kind: "not_found",
    message: RUN_NOT_FOUND_MESSAGE,
  },
  {
    ten: "409 REVIEW_QUOTA_TABLE_MISSING",
    loi: loi(409, { reason_code: "review_quota_table_missing", academic_year: 2027, detail: D("thiếu bảng"), error_code: "REVIEW_QUOTA_TABLE_MISSING" }),
    kind: "known",
    message: D("thiếu bảng"),
  },
  {
    ten: "409 REVIEW_SESSION_STALE",
    loi: loi(409, { reason_code: "review_session_stale", current_version: 5, detail: D("cũ"), error_code: "REVIEW_SESSION_STALE" }),
    kind: "known",
    message: D("cũ"),
  },
  {
    ten: "409 REVIEW_SESSION_NOT_DRAFT (đường trigger: không có `status`)",
    loi: loi(409, { reason_code: "review_session_not_draft", detail: D("không nháp"), error_code: "REVIEW_SESSION_NOT_DRAFT" }),
    kind: "known",
    message: D("không nháp"),
  },
  {
    ten: "409 REVIEW_RUN_IN_PROGRESS",
    loi: loi(409, { reason_code: "review_run_in_progress", detail: D("đang chạy"), error_code: "REVIEW_RUN_IN_PROGRESS" }),
    kind: "known",
    message: D("đang chạy"),
  },
  {
    ten: "409 REVIEW_RUN_NOT_DONE",
    loi: loi(409, { reason_code: "review_run_not_done", status: "running", detail: D("chưa xong"), error_code: "REVIEW_RUN_NOT_DONE" }),
    kind: "known",
    message: D("chưa xong"),
  },
  {
    ten: "409 ACADEMIC_INFO_IN_REVIEW_FLOOR (không reason_code)",
    loi: loi(409, { detail: D("dời năm"), error_code: "ACADEMIC_INFO_IN_REVIEW_FLOOR" }),
    kind: "known",
    message: D("dời năm"),
  },
  {
    ten: "422 VALIDATION_ERROR (errors[] đọc được để tô ô)",
    loi: loi(422, {
      detail: "Request validation failed",
      error_code: "VALIDATION_ERROR",
      errors: [{ loc: ["body", "reason"], msg: "Value error" }],
    }),
    kind: "invalid",
    message: INVALID_MESSAGE,
  },
  { ten: "429", loi: loi(429, { detail: "Rate limit exceeded: 300 per 1 hour" }), kind: "rate_limited", message: RATE_LIMITED_MESSAGE },
  {
    ten: "503 REVIEW_CONFIG_UNAVAILABLE / fee_gate_mode_invalid",
    loi: loi(503, { reason_code: "fee_gate_mode_invalid", detail: D("cổng học phí"), error_code: "REVIEW_CONFIG_UNAVAILABLE" }),
    kind: "known",
    message: D("cổng học phí"),
  },
  {
    ten: "503 REVIEW_CONFIG_UNAVAILABLE / residence_proof_doc_type_missing",
    loi: loi(503, { reason_code: "residence_proof_doc_type_missing", detail: D("cư trú"), error_code: "REVIEW_CONFIG_UNAVAILABLE" }),
    kind: "known",
    message: D("cư trú"),
  },
  {
    ten: "503 PRIORITY_RATE_NOT_CONFIGURED",
    loi: loi(503, {
      table: "priority_area",
      academic_year: 2026,
      missing_codes: ["KV1"],
      detail: D("mức ưu tiên"),
      error_code: "PRIORITY_RATE_NOT_CONFIGURED",
    }),
    kind: "known",
    message: D("mức ưu tiên"),
  },
  {
    ten: "503 đóng băng tầng ứng dụng (khoá `code`, không error_code)",
    loi: loi(503, { detail: "Admission frozen", code: "ADMISSION_FROZEN", frozen_prefix: "/api/admission-config" }),
    kind: "frozen",
    message: FROZEN_MESSAGE,
  },
  {
    ten: "503 đóng băng tầng nginx",
    loi: loi(503, { detail: "frozen", code: "NGINX_ADMISSION_FROZEN" }),
    kind: "frozen",
    message: FROZEN_MESSAGE,
  },
  {
    ten: "500 INTERNAL_ERROR",
    loi: loi(500, { detail: "Internal server error", error_code: "INTERNAL_ERROR" }),
    kind: "server",
    message: SERVER_ERROR_MESSAGE,
  },
]

describe("thiết kế §5 — bảng lỗi chung, mỗi dòng HĐ4 §5 một ca", () => {
  it.each(BANG_HD4_5)("$ten", ({ loi: e, kind, message }) => {
    const v = describeReviewSessionError(e, "write")
    expect(v.kind).toBe(kind)
    expect(v.message).toBe(message)
  })

  it("500 REVIEW_ISOLATION_UNSUPPORTED (mã riêng) ⇒ hiện câu máy chủ ('… chưa ghi gì')", () => {
    const v = describeReviewSessionError(
      loi(500, { detail: D("cô lập — chưa ghi gì"), error_code: "REVIEW_ISOLATION_UNSUPPORTED" }),
      "write",
    )
    expect(v.kind).toBe("known")
    expect(v.message).toBe(D("cô lập — chưa ghi gì"))
  })

  it("403: câu Casbin tiếng Anh không lọt ra màn (kể cả khi thân có error_code lạ)", () => {
    const v = describeReviewSessionError(loi(403, { detail: "Forbidden: policy denies GET", error_code: "REVIEW_SOMETHING" }))
    expect(v.message).toBe(FORBIDDEN_MESSAGE)
    expect(v.message).not.toContain("Forbidden")
  })

  it("rẽ nhánh theo MÃ, không theo chữ: 409 mã lạ mà `detail` giống câu cũ ⇒ câu chung có mã", () => {
    const v = describeReviewSessionError(loi(409, { detail: "Lần xét đã được sửa ở nơi khác", error_code: "SOMETHING_ELSE" }))
    expect(v.kind).toBe("unknown")
    expect(v.message).toBe("Có lỗi (mã: SOMETHING_ELSE).")
  })

  it("409 STALE: trả `current_version` + reason_code cho màn đọc thêm", () => {
    const v = describeReviewSessionError(
      loi(409, { reason_code: "review_session_stale", current_version: 5, detail: "x", error_code: "REVIEW_SESSION_STALE" }),
    )
    expect(v.errorCode).toBe("REVIEW_SESSION_STALE")
    expect(v.reasonCode).toBe("review_session_stale")
    expect(v.data?.current_version).toBe(5)
  })

  it("422: danh sách `errors[].loc` đọc được (để tô ô)", () => {
    const v = describeReviewSessionError(
      loi(422, { error_code: "VALIDATION_ERROR", errors: [{ loc: ["body", "floors", "0", "floor_score"], msg: "x" }] }),
    )
    expect(v.validation).toEqual([{ loc: ["body", "floors", "0", "floor_score"], msg: "x" }])
  })
})

describe("thiết kế §5 — mất kết nối / 502 / 504: route GHI ⇒ 'chưa rõ đã ghi', route ĐỌC ⇒ câu đọc", () => {
  it.each([
    ["mất kết nối", matKetNoi()],
    ["502", loi(502, "<html>bad gateway</html>")],
    ["504", loi(504, "<html>timeout</html>")],
  ])("%s ở route ghi ⇒ uncertain", (_ten, e) => {
    const v = describeReviewSessionError(e, "write")
    expect(v.kind).toBe("uncertain")
    expect(v.message).toBe(WRITE_UNCERTAIN_MESSAGE)
  })

  it.each([
    ["mất kết nối", matKetNoi()],
    ["504", loi(504, "")],
  ])("%s ở route đọc ⇒ network", (_ten, e) => {
    const v = describeReviewSessionError(e, "read")
    expect(v.kind).toBe("network")
    expect(v.message).toBe(READ_NETWORK_MESSAGE)
  })

  it("lỗi KHÔNG phải HTTP (phản hồi 2xx sai hợp đồng — Zod) ⇒ câu riêng, không nhận nhầm là mất kết nối", () => {
    const zodErr = z.object({ a: z.string() }).safeParse({ a: 1 }).error
    const v = describeReviewSessionError(zodErr, "write")
    expect(v.kind).toBe("bad_response")
    expect(v.message).toBe(BAD_RESPONSE_MESSAGE)
  })
})

describe("nhãn — giá trị lạ hiện chữ máy chủ / bị bỏ qua (HĐ4 §1.8)", () => {
  it("trạng thái lần xét: biết ⇒ nhãn Phụ lục A; lạ ⇒ nguyên chữ máy chủ", () => {
    expect(sessionStatusLabel("draft")).toBe("Nháp")
    expect(sessionStatusLabel("cancelled")).toBe("Đã huỷ")
    expect(sessionStatusLabel("trang_thai_moi")).toBe("trang_thai_moi")
  })

  it("hành động: chỉ giá trị biết vẽ nút, theo thứ tự cố định; giá trị lạ bỏ qua; [] ⇒ []", () => {
    expect(knownSessionActions(["cancel", "lock", "edit_floors"])).toEqual(["edit_floors", "cancel"])
    expect(knownSessionActions([])).toEqual([])
  })

  it("số theo tab: bốn tab biết trước theo thứ tự máy chủ, tab lạ nối sau với chữ máy chủ; null ⇒ []", () => {
    expect(tabCountEntries({ ineligible: 4, excluded: 2, auto: 1 })).toEqual([
      { tab: "auto", label: "Đạt — máy đề xuất", count: 1 },
      { tab: "ineligible", label: "Chưa đủ điều kiện", count: 4 },
      { tab: "excluded", label: "excluded", count: 2 },
    ])
    expect(tabCountEntries(null)).toEqual([])
  })

  it("nhãn đợt = chữ có sẵn của trang Cấu hình tuyển sinh (chỉ là nhãn, không khoá đợt nào)", () => {
    expect(roundStateLabel({ is_active: true, archived_at: null })).toBe("Đang hoạt động")
    expect(roundStateLabel({ is_active: false, archived_at: null })).toBe("Tạm dừng")
    expect(roundStateLabel({ is_active: true, archived_at: "2026-01-01T00:00:00Z" })).toBe("Đã lưu trữ")
  })

  it("liên kết bảng chỉ tiêu: `/quota-tables?year=<năm>` — KHÔNG `/admin/quota-tables` (chuyển hướng làm mất năm)", () => {
    expect(quotaTableHref(2027)).toBe("/quota-tables?year=2027")
  })
})
