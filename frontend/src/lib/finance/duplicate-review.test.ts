import { describe, expect, it } from "vitest"

import {
  MAX_DUPLICATE_ITEMS,
  TRANG_THAI_DAU,
  docThanLoi409,
  rutGon,
  type AnhChupNghiTrung,
  type TrangThaiGhi,
  type YDinhGhi,
} from "./duplicate-review"

const Y_DINH: YDinhGhi = {
  invoiceId: 19,
  methodId: 3,
  amount: 2_000_000,
  ngay: "2026-08-05",
}

function phieu(i = 91) {
  return {
    payment_id: i,
    amount: "2000000",
    payment_date: "2026-08-05T03:00:00+00:00",
    status: "pending",
    invoice_number: `INV-${i}`,
  }
}

function than409(over: Record<string, unknown> = {}) {
  return {
    detail: "trùng",
    error_code: "PAYMENT_DUPLICATE_SUSPECTED",
    duplicates: [phieu()],
    duplicates_truncated: false,
    duplicates_total: 1,
    review_token: "than.chuky",
    ...over,
  }
}

const ANH_CHUP: AnhChupNghiTrung = {
  duplicates: [phieu()],
  duplicatesTotal: 1,
  truncated: false,
  reviewToken: "than.chuky",
}

/** Chạy một dãy hành động từ trạng thái đầu. */
function chay(...hd: Parameters<typeof rutGon>[1][]): TrangThaiGhi {
  return hd.reduce<TrangThaiGhi>((s, h) => rutGon(s, h), TRANG_THAI_DAU)
}

describe("máy trạng thái ghi tiền — vòng xác nhận", () => {
  it("gửi → 409 → tick → gửi kèm phiếu, và phiếu đi cùng ảnh chụp", () => {
    const s = chay(
      { type: "GUI", yDinh: Y_DINH },
      { type: "NHAN_409", anhChup: ANH_CHUP },
      { type: "TICK", gia_tri: true },
      { type: "GUI_KEM_PHIEU" },
    )
    expect(s.kind).toBe("submitting_with_token")
    // Phiếu KHÔNG phải một biến rời: nó nằm trong chính ảnh chụp đang được vẽ,
    // nên không có đường nào gửi phiếu của tập này kèm danh sách của tập kia.
    expect(s.kind === "submitting_with_token" && s.anhChup.reviewToken).toBe(
      "than.chuky",
    )
  })

  it("chưa tick thì KHÔNG gửi được phiếu", () => {
    const s = chay(
      { type: "GUI", yDinh: Y_DINH },
      { type: "NHAN_409", anhChup: ANH_CHUP },
      { type: "GUI_KEM_PHIEU" },
    )
    expect(s.kind).toBe("review_required")
  })

  it("409 MỚI lúc đang xác nhận ⇒ thay TOÀN BỘ ảnh chụp và bỏ tick", () => {
    const moi: AnhChupNghiTrung = {
      duplicates: [phieu(91), phieu(92)],
      duplicatesTotal: 2,
      truncated: false,
      reviewToken: "phieu.moi",
    }
    const s = chay(
      { type: "GUI", yDinh: Y_DINH },
      { type: "NHAN_409", anhChup: ANH_CHUP },
      { type: "TICK", gia_tri: true },
      { type: "GUI_KEM_PHIEU" },
      { type: "NHAN_409", anhChup: moi },
    )
    expect(s.kind).toBe("review_required")
    if (s.kind !== "review_required") throw new Error("sai nhánh")
    expect(s.daTick, "tick cũ nói về tập cũ, phải mất hiệu lực").toBe(false)
    expect(s.anhChup.reviewToken).toBe("phieu.moi")
    expect(s.anhChup.duplicates).toHaveLength(2)
  })

  it("sửa một trường phiếu ràng buộc vào ⇒ về idle NGAY, mất phiếu", () => {
    const sau = rutGon(
      chay(
        { type: "GUI", yDinh: Y_DINH },
        { type: "NHAN_409", anhChup: ANH_CHUP },
        { type: "TICK", gia_tri: true },
      ),
      { type: "DOI_Y_DINH", yDinh: { ...Y_DINH, amount: 3_000_000 } },
    )
    expect(sau.kind).toBe("idle")
  })

  it("gõ lại ĐÚNG giá trị cũ thì KHÔNG mất phiếu", () => {
    const sau = rutGon(
      chay(
        { type: "GUI", yDinh: Y_DINH },
        { type: "NHAN_409", anhChup: ANH_CHUP },
        { type: "TICK", gia_tri: true },
      ),
      { type: "DOI_Y_DINH", yDinh: { ...Y_DINH } },
    )
    expect(
      sau.kind,
      "bắt người dùng xác nhận lại vì một thay đổi không có thật là cách nhanh " +
        "nhất khiến họ bấm qua cảnh báo mà không đọc",
    ).toBe("review_required")
  })

  it("bấm hai lần khi đang gửi ⇒ vẫn một lượt", () => {
    const s = chay({ type: "GUI", yDinh: Y_DINH }, { type: "GUI", yDinh: Y_DINH })
    expect(s.kind).toBe("submitting")
  })

  it("bấm hai lần khi đang gửi KÈM PHIẾU ⇒ vẫn một lượt", () => {
    const s = chay(
      { type: "GUI", yDinh: Y_DINH },
      { type: "NHAN_409", anhChup: ANH_CHUP },
      { type: "TICK", gia_tri: true },
      { type: "GUI_KEM_PHIEU" },
      { type: "GUI_KEM_PHIEU" },
    )
    expect(s.kind).toBe("submitting_with_token")
  })

  it("đóng form ⇒ mất phiếu, không hồi sinh", () => {
    const s = chay(
      { type: "GUI", yDinh: Y_DINH },
      { type: "NHAN_409", anhChup: ANH_CHUP },
      { type: "TICK", gia_tri: true },
      { type: "DONG_FORM" },
    )
    expect(s.kind).toBe("idle")
    // Và mở lại rồi gửi: bắt đầu từ chỗ trống, không có phiếu nào.
    const lai = rutGon(s, { type: "GUI", yDinh: Y_DINH })
    expect(lai.kind).toBe("submitting")
  })

  it("lỗi khác 409 ⇒ về idle, KHÔNG giữ ảnh chụp của lần gửi đã kết thúc", () => {
    const s = chay(
      { type: "GUI", yDinh: Y_DINH },
      { type: "NHAN_409", anhChup: ANH_CHUP },
      { type: "TICK", gia_tri: true },
      { type: "GUI_KEM_PHIEU" },
      { type: "LOI_KHAC" },
    )
    expect(s.kind).toBe("idle")
  })
})

describe("đọc thân lỗi 409 — fail-closed", () => {
  it("thân đúng thì đọc được", () => {
    const r = docThanLoi409(than409())
    expect(r).not.toBeNull()
    expect(r!.reviewToken).toBe("than.chuky")
  })

  it.each([
    ["thiếu review_token", { review_token: undefined }],
    ["review_token rỗng", { review_token: "" }],
    ["review_token sai kiểu", { review_token: 123 }],
    ["error_code khác", { error_code: "CONFLICT" }],
    ["duplicates rỗng", { duplicates: [] }],
    ["duplicates sai kiểu", { duplicates: "x" }],
    ["truncated sai kiểu", { duplicates_truncated: "no" }],
    ["phiếu có payment_id âm", { duplicates: [{ ...phieu(), payment_id: -1 }] }],
    ["phiếu có amount không phải tiền", { duplicates: [{ ...phieu(), amount: "x" }] }],
    ["phiếu có amount dạng hex", { duplicates: [{ ...phieu(), amount: "0x10" }] }],
    ["phiếu có status lạ", { duplicates: [{ ...phieu(), status: "rejected" }] }],
    ["ngày không phải ISO", { duplicates: [{ ...phieu(), payment_date: "5/8/2026" }] }],
  ])("%s ⇒ null (không mở đường xác nhận)", (_ten, over) => {
    expect(docThanLoi409(than409(over))).toBeNull()
  })

  it("thiếu phiếu là MÉO, không phải thiếu vặt", () => {
    // Ca này tách riêng vì nó dễ bị coi là "cứ hiện cảnh báo, chỉ ẩn nút đi".
    // Không: một khối cảnh báo kèm nút bấm vô hiệu còn tệ hơn một thông báo lỗi
    // thẳng thắn — người dùng không biết phải làm gì tiếp.
    const r = docThanLoi409(than409({ review_token: undefined }))
    expect(r).toBeNull()
  })

  it("dài hơn trần thì CẮT và nói ra, không từ chối", () => {
    const nhieu = Array.from({ length: MAX_DUPLICATE_ITEMS + 5 }, (_, i) =>
      phieu(i + 1),
    )
    const r = docThanLoi409(
      than409({ duplicates: nhieu, duplicates_total: nhieu.length }),
    )
    expect(r).not.toBeNull()
    expect(r!.duplicates).toHaveLength(MAX_DUPLICATE_ITEMS)
    expect(r!.truncated).toBe(true)
    expect(r!.duplicatesTotal).toBe(nhieu.length)
  })

  it("tổng nhỏ hơn số dòng là dữ liệu vô lý ⇒ lấy số dòng", () => {
    const r = docThanLoi409(than409({ duplicates_total: 0 }))
    expect(r!.duplicatesTotal).toBe(1)
  })
})
