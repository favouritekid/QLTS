// src/lib/finance/duplicate-payment.test.ts
/**
 * Hai việc thuần của cảnh báo ghi trùng: dấu vân tay của một lần ghi, và đọc
 * thân lỗi 409 một cách phòng thủ.
 *
 * KHÔNG có luật dò trùng ở đây — nó sống ở máy chủ
 * (`payment_repository.find_duplicate_candidates`). Một bản sao ở giao diện đã
 * được thử và lệch ngay lập tức: nó không thấy tổng tiền đã hoàn của từng
 * phiếu, và "ngày lịch Việt Nam" tính theo múi giờ máy người dùng.
 */
import { describe, it, expect } from "vitest"

import {
  MAX_DUPLICATE_ITEMS,
  PAYMENT_DUPLICATE_ERROR_CODE,
  parseDuplicateSuspected,
  paymentFingerprint,
} from "./duplicate-payment"

const PHIEU_HOP_LE = {
  payment_id: 7,
  amount: "1000000",
  payment_date: "2026-08-05T03:00:00+00:00",
  status: "pending",
  invoice_number: "INV-1",
}

function than409(over: Record<string, unknown> = {}) {
  return {
    detail: "trùng",
    error_code: PAYMENT_DUPLICATE_ERROR_CODE,
    duplicates: [PHIEU_HOP_LE],
    duplicates_truncated: false,
    ...over,
  }
}

describe("paymentFingerprint", () => {
  const goc = {
    sessionId: 0,
    invoiceId: 1,
    feeId: 2,
    amount: 1000,
    paymentDate: "2026-08-05",
  }

  it("cùng dữ liệu thì cùng dấu vân tay", () => {
    expect(paymentFingerprint(goc)).toBe(paymentFingerprint({ ...goc }))
  })

  it.each([
    ["số tiền", { amount: 2000 }],
    ["ngày", { paymentDate: "2026-08-06" }],
    ["hoá đơn", { invoiceId: 99 }],
    ["khoản phí", { feeId: 99 }],
    // Cùng dữ liệu nhưng khác LẦN MỞ form là hai lần ghi khác nhau: phản hồi
    // đến muộn của phiên trước không được nói chuyện với phiên này.
    ["lần mở form", { sessionId: 1 }],
  ])("đổi %s thì dấu vân tay đổi", (_ten, doi) => {
    expect(paymentFingerprint({ ...goc, ...doi })).not.toBe(
      paymentFingerprint(goc),
    )
  })
})

describe("parseDuplicateSuspected", () => {
  it("đọc được thân lỗi đúng hợp đồng", () => {
    const r = parseDuplicateSuspected(than409())
    expect(r).not.toBeNull()
    expect(r!.duplicates).toHaveLength(1)
    expect(r!.duplicates_truncated).toBe(false)
  })

  it("giữ nguyên cờ bị cắt", () => {
    expect(
      parseDuplicateSuspected(than409({ duplicates_truncated: true }))!
        .duplicates_truncated,
    ).toBe(true)
  })

  it.each([
    ["mã lỗi khác", than409({ error_code: "CONFLICT" })],
    ["thiếu duplicates", { detail: "x", error_code: PAYMENT_DUPLICATE_ERROR_CODE }],
    ["duplicates không phải mảng", than409({ duplicates: "nhiều" })],
    ["thiếu cờ bị cắt", { detail: "x", error_code: PAYMENT_DUPLICATE_ERROR_CODE, duplicates: [] }],
    ["cờ bị cắt sai kiểu", than409({ duplicates_truncated: "true" })],
    ["phần tử thiếu trường", than409({ duplicates: [{ payment_id: 1 }] })],
    ["số tiền là số, không phải chuỗi", than409({ duplicates: [{ ...PHIEU_HOP_LE, amount: 1000000 }] })],
    ["thân lỗi là chuỗi", "lỗi"],
    ["thân lỗi rỗng", null],
  ])("từ chối khi %s", (_ten, than) => {
    // Fail-closed: người gọi dùng kết quả này để TẮT thông báo lỗi chung, nên
    // "không chắc" phải trả null để rơi về đường lỗi chung. Nhận bừa một
    // payload méo là người dùng bấm Lưu rồi không thấy phản hồi nào.
    expect(parseDuplicateSuspected(than)).toBeNull()
  })
})

describe("parseDuplicateSuspected — kiểm Ý NGHĨA, không chỉ kiểu", () => {
  it.each([
    ["id không dương", { ...PHIEU_HOP_LE, payment_id: -1 }],
    ["id không nguyên", { ...PHIEU_HOP_LE, payment_id: 1.5 }],
    ["số tiền không đọc được", { ...PHIEU_HOP_LE, amount: "không-phải-tiền" }],
    ["ngày không đọc được", { ...PHIEU_HOP_LE, payment_date: "hôm-qua" }],
    ["trạng thái ngoài danh sách", { ...PHIEU_HOP_LE, status: "bất-kỳ" }],
  ])("từ chối khi %s", (_ten, phieu) => {
    // `typeof` một mình vẫn nhận hết những thứ này, rồi giao diện dựng khối
    // cảnh báo từ rác VÀ tắt thông báo lỗi chung — người dùng bấm Lưu và không
    // hiểu chuyện gì đang xảy ra.
    expect(parseDuplicateSuspected(than409({ duplicates: [phieu] }))).toBeNull()
  })

  it("từ chối danh sách RỖNG", () => {
    // Máy chủ chỉ ném lỗi này KHI có ứng viên; rỗng nghĩa là ta đang hiểu sai
    // thân lỗi, và một khối cảnh báo trống thì không nói được điều gì.
    expect(parseDuplicateSuspected(than409({ duplicates: [] }))).toBeNull()
  })

  it("từ chối khi vượt trần của máy chủ", () => {
    const qua = Array.from({ length: MAX_DUPLICATE_ITEMS + 1 }, (_, i) => ({
      ...PHIEU_HOP_LE,
      payment_id: i + 1,
    }))
    expect(parseDuplicateSuspected(than409({ duplicates: qua }))).toBeNull()
  })

  it("chấp nhận đúng trần", () => {
    const vua = Array.from({ length: MAX_DUPLICATE_ITEMS }, (_, i) => ({
      ...PHIEU_HOP_LE,
      payment_id: i + 1,
    }))
    expect(parseDuplicateSuspected(than409({ duplicates: vua }))).not.toBeNull()
  })

  it("chấp nhận ngày null (phiếu chưa có ngày thu)", () => {
    expect(
      parseDuplicateSuspected(
        than409({ duplicates: [{ ...PHIEU_HOP_LE, payment_date: null }] }),
      ),
    ).not.toBeNull()
  })
})
