// src/lib/finance/duplicate-payment.test.ts
/**
 * Ba việc thuần của cảnh báo ghi trùng.
 *
 * Bộ ca biên ở `locUngVienTrung` là **bản sao có chủ ý** của bộ ca đang canh
 * luật máy chủ (`tests/services/test_payment_duplicate_guard.py`): 0 / 3 / 4
 * ngày, bằng tiền / khác tiền, pending / verified / rejected. Hai bản luật
 * không dùng chung được vì khác ngôn ngữ, nên chúng phải được canh bằng cùng
 * một bộ ca — lệch một bên là giao diện báo oan hoặc bỏ sót.
 */
import { describe, it, expect } from "vitest"

import {
  DUPLICATE_WINDOW_DAYS,
  PAYMENT_DUPLICATE_ERROR_CODE,
  calendarDaysApart,
  locUngVienTrung,
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
  const goc = { invoiceId: 1, feeId: 2, amount: 1000, paymentDate: "2026-08-05" }

  it("cùng dữ liệu thì cùng dấu vân tay", () => {
    expect(paymentFingerprint(goc)).toBe(paymentFingerprint({ ...goc }))
  })

  it.each([
    ["số tiền", { amount: 2000 }],
    ["ngày", { paymentDate: "2026-08-06" }],
    ["hoá đơn", { invoiceId: 99 }],
    ["khoản phí", { feeId: 99 }],
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

describe("calendarDaysApart", () => {
  it("đếm theo NGÀY LỊCH, không theo số giờ", () => {
    // Cách nhau 2 giờ nhưng khác ngày ⇒ 1 ngày lịch.
    expect(
      calendarDaysApart("2026-08-05T23:00:00", "2026-08-06T01:00:00"),
    ).toBe(1)
    // Cách nhau 23 giờ nhưng cùng ngày ⇒ 0.
    expect(
      calendarDaysApart("2026-08-05T00:30:00", "2026-08-05T23:30:00"),
    ).toBe(0)
  })

  it("trả null khi không đọc được", () => {
    expect(calendarDaysApart("không phải ngày", "2026-08-05")).toBeNull()
  })
})

describe("locUngVienTrung", () => {
  const ngay = "2026-08-05T10:00:00"
  const phieu = (over: Partial<Parameters<typeof locUngVienTrung>[0][0]> = {}) => ({
    id: 1,
    amount: "1000000",
    status: "pending",
    payment_date: "2026-08-05T10:00:00",
    ...over,
  })

  it("cùng tiền, cùng ngày ⇒ là ứng viên", () => {
    expect(
      locUngVienTrung([phieu()], { amount: 1_000_000, paymentDate: ngay }),
    ).toHaveLength(1)
  })

  it(`đúng ${DUPLICATE_WINDOW_DAYS} ngày vẫn là ứng viên (biên NẰM TRONG)`, () => {
    expect(
      locUngVienTrung([phieu({ payment_date: "2026-08-08T10:00:00" })], {
        amount: 1_000_000,
        paymentDate: ngay,
      }),
    ).toHaveLength(1)
  })

  it("quá cửa sổ thì thôi", () => {
    expect(
      locUngVienTrung([phieu({ payment_date: "2026-08-09T10:00:00" })], {
        amount: 1_000_000,
        paymentDate: ngay,
      }),
    ).toHaveLength(0)
  })

  it("khác số tiền thì không phải ứng viên", () => {
    expect(
      locUngVienTrung([phieu({ amount: "500000" })], {
        amount: 1_000_000,
        paymentDate: ngay,
      }),
    ).toHaveLength(0)
  })

  it("phiếu đã từ chối / đã đảo không còn là tiền", () => {
    const items = [phieu({ status: "rejected" }), phieu({ status: "refunded" })]
    expect(
      locUngVienTrung(items, { amount: 1_000_000, paymentDate: ngay }),
    ).toHaveLength(0)
  })

  it("phiếu đã duyệt vẫn tính", () => {
    expect(
      locUngVienTrung([phieu({ status: "verified" })], {
        amount: 1_000_000,
        paymentDate: ngay,
      }),
    ).toHaveLength(1)
  })

  it("chưa nhập đủ số tiền / ngày thì không cảnh báo gì", () => {
    expect(locUngVienTrung([phieu()], { amount: null, paymentDate: ngay })).toEqual([])
    expect(
      locUngVienTrung([phieu()], { amount: 1_000_000, paymentDate: null }),
    ).toEqual([])
  })
})
