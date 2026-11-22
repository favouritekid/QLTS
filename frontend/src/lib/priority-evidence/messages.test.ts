/**
 * GĐ2-F1 — câu cho lỗi thao tác minh chứng ưu tiên: mã lý do của máy chủ ⇒ câu tiếng Việt, không lộ mã nội bộ.
 */
import { describe, expect, it } from "vitest"
import { AxiosError, AxiosHeaders } from "axios"

import { describePriorityEvidenceError, priorityEvidenceBlockText } from "./messages"

function loi(status: number, data: Record<string, unknown>): AxiosError {
  const config = { headers: new AxiosHeaders() }
  return new AxiosError("loi", "ERR_BAD_RESPONSE", config, undefined, {
    status,
    statusText: "",
    headers: {},
    config,
    data,
  })
}

describe("describePriorityEvidenceError", () => {
  it.each([
    ["own_submission", "OWN_SUBMISSION", /không tự duyệt hay từ chối/],
    ["unknown_submitter", "UNKNOWN_SUBMITTER", /cần tích ô cam kết và ghi lý do/],
  ])("409 %s ⇒ câu riêng, không lộ mã", (rc, ec, mau) => {
    const cau = describePriorityEvidenceError(loi(409, { reason_code: rc, error_code: ec, detail: "x" }), "verify")
    expect(cau).toMatch(mau)
    expect(cau).not.toMatch(new RegExp(`${rc}|${ec}`))
  })

  it("409 chỉ có error_code (không reason_code) vẫn ra câu đúng", () => {
    expect(describePriorityEvidenceError(loi(409, { error_code: "OWN_SUBMISSION" }), "reject")).toMatch(
      /không tự duyệt hay từ chối/,
    )
  })

  it("409 CONFLICT (lệch phiên bản hồ sơ) ⇒ bảo tải lại", () => {
    expect(describePriorityEvidenceError(loi(409, { error_code: "CONFLICT", detail: "Expected version 3" }), "verify")).toMatch(
      /người khác cập nhật/,
    )
  })

  it("409 mã lạ ⇒ câu chung, không lộ mã", () => {
    const cau = describePriorityEvidenceError(loi(409, { reason_code: "ma_noi_bo_la" }), "verify")
    expect(cau).not.toMatch(/ma_noi_bo_la/)
  })

  it("400 theo thao tác: ghi nhận bản giấy có câu riêng", () => {
    expect(describePriorityEvidenceError(loi(400, { detail: "x" }), "paper")).toMatch(/Không ghi nhận được/)
    expect(describePriorityEvidenceError(loi(400, { detail: "x" }), "verify")).toMatch(/Không duyệt được/)
  })

  it("503 đóng băng tuyển sinh ⇒ câu đóng băng", () => {
    expect(describePriorityEvidenceError(loi(503, { code: "ADMISSION_FROZEN" }), "paper")).toMatch(/đóng băng/)
  })
})

describe("priorityEvidenceBlockText", () => {
  it("mã đã biết ⇒ câu riêng; mã lạ ⇒ câu chung không lộ mã", () => {
    expect(priorityEvidenceBlockText("own_submission")).toMatch(/không tự duyệt hay từ chối/)
    expect(priorityEvidenceBlockText("ma_la")).not.toMatch(/ma_la/)
  })
})
