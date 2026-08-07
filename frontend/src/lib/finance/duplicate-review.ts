// src/lib/finance/duplicate-review.ts
/**
 * Máy trạng thái của một lần ghi tiền tay — phần thuần tuý, không React.
 *
 * Bốn vòng review trước đều lộ cùng một hình dạng lỗi: giao diện giữ NHIỀU
 * mảnh trạng thái mô tả cùng một sự kiện (cảnh báo từ preview, cảnh báo từ 409,
 * dấu vân tay, tập mã phiếu, cờ bị cắt, tick xác nhận), và chúng không bắt buộc
 * đồng bộ. Mỗi bản vá thêm một trường là thêm một chỗ hai mảnh nói khác nhau.
 *
 * Nên ở đây chỉ có MỘT giá trị trạng thái, kiểu union phân biệt được. Không thể
 * biểu diễn "đang chờ xác nhận mà không có phiếu", cũng không thể biểu diễn
 * "có phiếu nhưng danh sách rỗng" — trình biên dịch từ chối trước khi ai kịp
 * viết ra.
 */

/** Một phiếu nghi trùng máy chủ trả trong thân lỗi 409. */
export interface DuplicatePaymentInfo {
  payment_id: number
  amount: string
  payment_date: string | null
  status: string
  invoice_number: string | null
}

/**
 * Ảnh chụp mà máy chủ gửi kèm 409. Cả bốn phần đi CÙNG NHAU, không tách rời:
 * danh sách để vẽ, tổng để nói "còn nữa", cờ bị cắt, và phiếu để gửi lại.
 * Tách chúng thành các state độc lập là dựng lại đúng lớp lỗi vừa xoá — màn
 * hình vẽ tập này trong khi gửi đi phiếu của tập kia.
 */
export interface AnhChupNghiTrung {
  duplicates: DuplicatePaymentInfo[]
  duplicatesTotal: number
  truncated: boolean
  reviewToken: string
}

/**
 * Bộ dữ liệu mà phiếu xác nhận RÀNG BUỘC vào (phía máy chủ ký cả những trường
 * này). Giao diện giữ bản sao ở đây chỉ để biết khi nào người dùng đã đổi ý —
 * không phải để tự phán xét: máy chủ vẫn là hàng rào cuối và từ chối một phiếu
 * sai hoàn cảnh, kể cả khi giao diện quên.
 */
export interface YDinhGhi {
  invoiceId: number
  methodId: number | null
  amount: number | null
  /** Ngày lịch VN dạng `YYYY-MM-DD` — đúng hạt mà máy chủ ràng buộc. */
  ngay: string | null
}

export type TrangThaiGhi =
  | { kind: "idle" }
  | { kind: "submitting"; yDinh: YDinhGhi }
  /** Máy chủ đã từ chối và cấp phiếu. `daTick` là xác nhận của người dùng. */
  | {
      kind: "review_required"
      yDinh: YDinhGhi
      anhChup: AnhChupNghiTrung
      daTick: boolean
    }
  | {
      kind: "submitting_with_token"
      yDinh: YDinhGhi
      anhChup: AnhChupNghiTrung
    }
  | { kind: "success" }

export type HanhDong =
  | { type: "GUI"; yDinh: YDinhGhi }
  | { type: "NHAN_409"; anhChup: AnhChupNghiTrung }
  | { type: "TICK"; gia_tri: boolean }
  | { type: "GUI_KEM_PHIEU" }
  | { type: "THANH_CONG" }
  | { type: "LOI_KHAC" }
  /** Người dùng sửa một trường mà phiếu đã ràng buộc vào. */
  | { type: "DOI_Y_DINH"; yDinh: YDinhGhi }
  | { type: "DONG_FORM" }

/** Hai ý định có ràng buộc phiếu giống nhau không? */
export function cungYDinh(a: YDinhGhi, b: YDinhGhi): boolean {
  return (
    a.invoiceId === b.invoiceId &&
    a.methodId === b.methodId &&
    a.amount === b.amount &&
    a.ngay === b.ngay
  )
}

export const TRANG_THAI_DAU: TrangThaiGhi = { kind: "idle" }

export function rutGon(s: TrangThaiGhi, h: HanhDong): TrangThaiGhi {
  switch (h.type) {
    case "GUI":
      // Chỉ đi từ `idle`. Bấm lần hai trong lúc request đang bay KHÔNG được
      // sinh thêm một lượt gửi — double-click ở đây là hai phiếu thu.
      return s.kind === "idle" ? { kind: "submitting", yDinh: h.yDinh } : s

    case "NHAN_409":
      // Thay TOÀN BỘ ảnh chụp và bỏ tick cũ. Kể cả khi đang ở
      // `submitting_with_token`: 409 mới nghĩa là tập ứng viên đã khác tập
      // người dùng vừa xác nhận, nên xác nhận ấy hết hiệu lực.
      if (s.kind !== "submitting" && s.kind !== "submitting_with_token") return s
      return {
        kind: "review_required",
        yDinh: s.yDinh,
        anhChup: h.anhChup,
        daTick: false,
      }

    case "TICK":
      return s.kind === "review_required" ? { ...s, daTick: h.gia_tri } : s

    case "GUI_KEM_PHIEU":
      // Chưa tick thì không đi được — và vì `anhChup` nằm trong chính state
      // này, không có đường nào gửi phiếu mà không có phiếu.
      return s.kind === "review_required" && s.daTick
        ? { kind: "submitting_with_token", yDinh: s.yDinh, anhChup: s.anhChup }
        : s

    case "THANH_CONG":
      return { kind: "success" }

    case "LOI_KHAC":
      // Lỗi không phải nghi trùng: về `idle` để người dùng sửa rồi gửi lại.
      // KHÔNG giữ ảnh chụp — nó nói về một lần gửi đã kết thúc.
      return s.kind === "submitting" || s.kind === "submitting_with_token"
        ? { kind: "idle" }
        : s

    case "DOI_Y_DINH":
      // Sửa bất kỳ trường nào phiếu ràng buộc vào ⇒ về `idle` NGAY, mất phiếu.
      // Giữ lại là để người dùng gửi một phiếu nói về số tiền cũ kèm số tiền
      // mới; máy chủ sẽ từ chối, nhưng trước đó màn hình đã hiện một cảnh báo
      // về tập ứng viên của con số họ vừa xoá.
      if (s.kind === "review_required" && !cungYDinh(s.yDinh, h.yDinh)) {
        return { kind: "idle" }
      }
      // Đang gửi thì KHÓA — các trường đã bind vào phiếu không được đổi giữa
      // chừng. Giao diện disable chúng; nhánh này là hàng rào thứ hai.
      return s

    case "DONG_FORM":
      // Đóng là mất sạch. Phiếu không sống qua một lần đóng/mở: nó nói về một
      // tập ứng viên tại một thời điểm, và lần mở sau là một câu hỏi khác.
      return { kind: "idle" }

    default:
      return s
  }
}

// ============================================================================
// ĐỌC THÂN LỖI 409 — FAIL-CLOSED
// ============================================================================

export const PAYMENT_DUPLICATE_ERROR_CODE = "PAYMENT_DUPLICATE_SUSPECTED"

/**
 * Trạng thái phiếu mà luật dò trùng công nhận.
 *
 * BẢN SAO của `TRANG_THAI_UNG_VIEN_TRUNG` trong
 * `app/repositories/payment_repository.py`. Không gộp được — giao diện phải
 * kiểm payload trước khi tin nó — nên hai bản được neo bằng một ca ở máy chủ
 * (`test_payment_duplicate_contract.py`) sẽ đỏ nếu ai nới luật dò mà quên sửa
 * ở đây.
 */
const TRANG_THAI_HOP_LE = new Set(["pending", "verified"])

/** Trần số phần tử, khớp `MAX_DUPLICATE_CANDIDATES` ở máy chủ. */
export const MAX_DUPLICATE_ITEMS = 20

/**
 * Chuỗi Decimal DƯƠNG theo hợp đồng của máy chủ. Cố tình không nhận `0x10`,
 * `1e3`, `+1` — `Number()` hiểu hết những dạng đó (`Number("0x10") === 16`),
 * nhưng máy chủ không bao giờ sinh ra chúng, nên gặp một trong số đó nghĩa là
 * dữ liệu không tới từ đường ta nghĩ. Số chữ số cũng có trần: cột tiền là
 * `Numeric(15,2)`, còn `Number()` biến một chuỗi vài trăm chữ số thành
 * `Infinity` — thứ vượt mọi phép so và vẫn là "dương hữu hạn" dưới mắt `> 0`.
 */
const DECIMAL_DUONG = /^\d{1,18}(\.\d{1,6})?$/

/** ISO-8601 dạng máy chủ sinh ra. */
const ISO_8601 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$/

function laPhieuHopLe(v: unknown): v is DuplicatePaymentInfo {
  if (typeof v !== "object" || v === null) return false
  const o = v as Record<string, unknown>
  // Kiểm cả Ý NGHĨA, không chỉ kiểu: `typeof` một mình vẫn nhận
  // `payment_id: -1` và `amount: "không-phải-tiền"`, rồi giao diện dựng một
  // khối cảnh báo từ rác và TẮT thông báo lỗi chung.
  if (!Number.isInteger(o.payment_id) || (o.payment_id as number) <= 0) return false
  if (typeof o.amount !== "string" || !DECIMAL_DUONG.test(o.amount)) return false
  const soTien = Number(o.amount)
  if (!Number.isFinite(soTien) || soTien <= 0) return false
  if (o.payment_date !== null) {
    if (typeof o.payment_date !== "string") return false
    // Đòi ISO-8601 thật, không chỉ "thứ `Date.parse` hiểu được": `Date.parse`
    // nhận cả "March 5, 2026" lẫn vài dạng riêng của từng trình duyệt, nên nó
    // không phải một hợp đồng.
    if (!ISO_8601.test(o.payment_date)) return false
    if (Number.isNaN(Date.parse(o.payment_date))) return false
  }
  if (typeof o.status !== "string" || !TRANG_THAI_HOP_LE.has(o.status)) return false
  if (o.invoice_number !== null && typeof o.invoice_number !== "string") return false
  return true
}

/**
 * Đọc thân lỗi 409. Trả `null` nếu KHÔNG phải ca nghi trùng **hoặc** payload
 * méo — người gọi rơi về đường lỗi chung, tức fail-closed.
 *
 * Vì sao kiểm từng trường thay vì tin `error_code`: kết quả này quyết định có
 * hiện nút xác nhận hay không. Payload méo mà vẫn nhận nghĩa là dựng một cánh
 * cửa "bỏ qua cảnh báo" trên một cảnh báo ta không đọc được.
 *
 * Thiếu `review_token` là méo, không phải thiếu vặt: không có phiếu thì không
 * có gì để xác nhận, và một khối cảnh báo kèm nút bấm vô hiệu còn tệ hơn một
 * thông báo lỗi thẳng thắn.
 */
export function docThanLoi409(body: unknown): AnhChupNghiTrung | null {
  if (typeof body !== "object" || body === null) return null
  const o = body as Record<string, unknown>
  if (o.error_code !== PAYMENT_DUPLICATE_ERROR_CODE) return null
  if (typeof o.review_token !== "string" || !o.review_token) return null
  if (!Array.isArray(o.duplicates)) return null
  if (typeof o.duplicates_truncated !== "boolean") return null
  // Rỗng là méo: máy chủ chỉ ném lỗi này KHI có ứng viên.
  if (o.duplicates.length === 0) return null
  if (!o.duplicates.every(laPhieuHopLe)) return null

  // Dài hơn trần thì CẮT, không từ chối. Trần ở đây là bản sao hằng số của máy
  // chủ; nâng nó bên kia là một dòng sửa hiển nhiên vô hại, mà từ chối cứng sẽ
  // biến nó thành "khối cảnh báo im lặng biến mất".
  const duplicates = (o.duplicates as DuplicatePaymentInfo[]).slice(
    0,
    MAX_DUPLICATE_ITEMS,
  )
  const tong =
    typeof o.duplicates_total === "number" &&
    Number.isInteger(o.duplicates_total) &&
    o.duplicates_total >= duplicates.length
      ? o.duplicates_total
      : duplicates.length
  return {
    duplicates,
    duplicatesTotal: tong,
    truncated: o.duplicates_truncated || o.duplicates.length > MAX_DUPLICATE_ITEMS,
    reviewToken: o.review_token,
  }
}

/*
 * 🔴 KHÔNG dựng lại luật dò trùng ở đây, và KHÔNG tự tạo/biến đổi phiếu.
 *
 * Bản trước có một `locUngVienTrung` lọc theo số tiền + ngày lịch, và nó lệch
 * khỏi máy chủ ngay trong lần viết đầu tiên, ở hai chỗ giao diện KHÔNG thể
 * biết: tiền đã hoàn (đường hoàn chỉ đổi `RefundRequest.status`, `Payment` vẫn
 * `verified`), và "ngày lịch Việt Nam" (`getFullYear()` đọc theo múi giờ máy
 * người dùng, máy chủ cố định `Asia/Ho_Chi_Minh`).
 *
 * Phiếu thì mờ với giao diện theo đúng thiết kế: nhận, giữ trong state của lần
 * gửi này, gửi lại nguyên văn, rồi quên. Không đọc, không ghép, không lưu vào
 * React Query / Zustand / storage.
 */
