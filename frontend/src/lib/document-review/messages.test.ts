/**
 * GĐ1b — phân loại lỗi + câu hiển thị. Khoá §5.9: lỗi mạng / 5xx / 504 / 409 BATCH_RUNNING / BATCH_EXISTS ⇒ TRA lô
 * (không bao giờ gửi lại execute); PREVIEW_EXPIRED / 404 ⇒ xem trước lại; nhịp hỏi lại 3 s rồi 10 s.
 */
import { AxiosError, AxiosHeaders } from "axios"
import { describe, expect, it } from "vitest"

import {
  batchItemText,
  batchPollInterval,
  classifyExecuteError,
  confirmationSentence,
  describeDocumentActionError,
  describeFinalizeError,
  describePreviewError,
  VERSION_CHANGED_MESSAGE,
} from "./messages"

function loi(status: number, data: Record<string, unknown> = {}): AxiosError {
  const config = { headers: new AxiosHeaders() }
  return new AxiosError("loi", "ERR_BAD_RESPONSE", config, undefined, {
    status,
    statusText: "",
    headers: {},
    config,
    data,
  })
}
const matMang = () => new AxiosError("Network Error", "ERR_NETWORK")

describe("classifyExecuteError — §5.9", () => {
  it.each([
    ["mất mạng", matMang()],
    ["500", loi(500)],
    ["502", loi(502)],
    ["504 (nginx 60 s)", loi(504)],
    ["409 BATCH_RUNNING", loi(409, { error_code: "BATCH_RUNNING" })],
    ["409 BATCH_EXISTS", loi(409, { error_code: "BATCH_EXISTS" })],
    ["lỗi không phải axios (vd phản hồi 200 sai dạng)", new Error("zod")],
  ])("%s ⇒ tra lô", (_t, e) => {
    expect(classifyExecuteError(e).kind).toBe("lookup")
  })

  it("409 PREVIEW_EXPIRED ⇒ xem trước lại", () => {
    expect(classifyExecuteError(loi(409, { error_code: "PREVIEW_EXPIRED" })).kind).toBe("expired")
  })

  it("404 (kể cả PREVIEW_GONE) ⇒ 'Bản xem trước không còn — xem trước lại'", () => {
    const o = classifyExecuteError(loi(404, { error_code: "PREVIEW_GONE" }))
    expect(o.kind).toBe("gone")
    expect(o.message).toBe("Bản xem trước không còn — xem trước lại")
  })

  it.each([401, 403, 422, 429])("%i ⇒ máy chủ từ chối TRƯỚC khi ghi (lô chưa chạy)", (s) => {
    const o = classifyExecuteError(loi(s))
    expect(o.kind).toBe("refused")
    expect(o.message).toMatch(/CHƯA chạy/)
  })
})

describe("batchPollInterval — hỏi lại 3 s rồi 10 s", () => {
  it.each(["starting", "running", "unknown"])("%s: lần đầu 3000, sau đó 10000", (s) => {
    expect(batchPollInterval(s, 1)).toBe(3000)
    expect(batchPollInterval(s, 2)).toBe(10000)
    expect(batchPollInterval(s, 7)).toBe(10000)
  })

  it.each(["not_started", "expired", "interrupted_unfinalized", "completed", "stopped", "interrupted", undefined])(
    "%s ⇒ không hỏi lại",
    (s) => {
      expect(batchPollInterval(s, 1)).toBe(false)
    },
  )
})

describe("câu hiển thị", () => {
  it("mục lô version_changed ⇒ câu §5.9 (kể cả khi máy chủ ghi câu khác)", () => {
    expect(batchItemText({ reason_code: "version_changed", message: "server text" })).toBe(VERSION_CHANGED_MESSAGE)
    expect(VERSION_CHANGED_MESSAGE).toBe(
      "Giấy này đã được xử lý ở lô khác hoặc thao tác khác sau khi bạn xem trước — hãy xem trước lại",
    )
  })

  it("mục lô mã lạ ⇒ câu máy chủ", () => {
    expect(batchItemText({ reason_code: "ma_moi", message: "Câu máy chủ" })).toBe("Câu máy chủ")
  })

  it("câu xác nhận mang đúng số giấy máy chủ trả", () => {
    expect(confirmationSentence(37)).toBe(
      "Tôi xác nhận đã đối chiếu giấy thật của 37 giấy này. Phần mềm chỉ ghi lại kết quả kiểm của tôi.",
    )
  })

  it("xem trước 422 TOO_MANY_PROFILES ⇒ câu có số đếm của máy chủ", () => {
    const m = describePreviewError(loi(422, { error_code: "TOO_MANY_PROFILES", profile_count: 140, limit: 100 }))
    expect(m).toContain("140")
    expect(m).toContain("100")
  })

  it("xem trước 409 TOO_MANY_PREVIEWS ⇒ chờ rồi thử lại", () => {
    expect(describePreviewError(loi(409, { error_code: "TOO_MANY_PREVIEWS" }))).toMatch(/thử lại sau giây lát/)
  })

  it("nút lẻ 409 VERSION_CHANGED (theo reason_code hoặc error_code) ⇒ version_changed", () => {
    expect(describeDocumentActionError(loi(409, { reason_code: "version_changed", error_code: "VERSION_CHANGED" })).kind).toBe(
      "version_changed",
    )
    expect(describeDocumentActionError(loi(409, { error_code: "VERSION_CHANGED" })).kind).toBe("version_changed")
  })

  it("nút lẻ 409 OWN_SUBMISSION ⇒ câu tiếng Việt, không lộ mã", () => {
    const v = describeDocumentActionError(loi(409, { reason_code: "own_submission", error_code: "OWN_SUBMISSION" }))
    expect(v.kind).toBe("conflict")
    expect(v.message).not.toMatch(/own_submission|OWN_SUBMISSION/)
  })

  it("chốt lô 422 ⇒ cần lý do", () => {
    expect(describeFinalizeError(loi(422))).toBe("Cần nhập lý do chốt lô")
    expect(describeFinalizeError(loi(409, { error_code: "BATCH_RUNNING" }))).toBe("Lô đang chạy — chưa chốt được")
  })
})
