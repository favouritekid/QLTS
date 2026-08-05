// src/lib/finance/duplicate-payment.ts
/**
 * Cảnh báo ghi trùng phiếu thu — phần thuần tuý, không React.
 *
 * Hai việc, tách khỏi component để kiểm được từng cái một:
 *  1. **Dấu vân tay** của một lần ghi — thứ quyết định một xác nhận còn hiệu
 *     lực hay đã hết hạn;
 *  2. **Đọc thân lỗi 409** một cách phòng thủ — payload méo phải bị từ chối
 *     thẳng, không được đoán.
 *
 * Luật dò trùng KHÔNG ở đây: xem ghi chú dưới cùng.
 */

/** Một phiếu nghi trùng do máy chủ trả về trong thân lỗi 409. */
export interface DuplicatePaymentInfo {
  payment_id: number
  amount: string
  payment_date: string | null
  status: string
  invoice_number: string | null
}

export interface DuplicateSuspectedPayload {
  duplicates: DuplicatePaymentInfo[]
  duplicates_truncated: boolean
}

export const PAYMENT_DUPLICATE_ERROR_CODE = "PAYMENT_DUPLICATE_SUSPECTED"

/**
 * Dấu vân tay của một lần ghi tiền.
 *
 * Xác nhận "đây là khoản thu khác" chỉ đúng cho **đúng bộ dữ liệu người dùng
 * đã nhìn**. Tick cho 2.000.000 rồi sửa thành 5.000.000 mà vẫn gửi cờ xác nhận
 * là bỏ qua cảnh báo cho một số tiền chưa ai từng xem; tương tự, xác nhận cho
 * hoá đơn này không được mang sang hoá đơn khác.
 */
export function paymentFingerprint(input: {
  /**
   * Số thứ tự LẦN MỞ form. Cùng bộ dữ liệu nhưng khác lần mở là hai lần ghi
   * khác nhau: người dùng có thể đóng form giữa lúc request đang bay, và phản
   * hồi 409 về muộn sẽ gọi `setState` sau khi hiệu ứng dọn dẹp đã chạy. Không
   * có số này thì mở lại rồi gõ đúng số tiền cũ sẽ thấy danh sách của phiên
   * trước sống dậy — một cảnh báo về dữ liệu mà lần này chưa ai hỏi.
   */
  sessionId: number
  invoiceId: number
  feeId: number
  amount?: number | null
  paymentDate?: string | null
}): string {
  return [
    input.sessionId,
    input.invoiceId,
    input.feeId,
    input.amount ?? "",
    input.paymentDate ?? "",
  ].join("|")
}

/**
 * Cấp một số phiên MỚI, không bao giờ lặp trong vòng đời trang.
 *
 * Bộ đếm nằm ở MODULE, không phải trong component: form ghi tiền bị **unmount
 * hẳn** khi đóng ở màn Thu học phí (`WorkspaceActionDialogs` chỉ render nó khi
 * `dialog.type === "record"`). Một `useState(0)` sẽ lại là 0 ở lần mở kế tiếp,
 * nên khoá truy vấn trùng khít với phiên trước và bản cache cũ sống lại —
 * đúng thứ số phiên sinh ra để chặn.
 */
let _boDemPhien = 0
export function capSoPhienMoi(): number {
  _boDemPhien += 1
  return _boDemPhien
}

/** Trạng thái phiếu mà luật dò trùng công nhận — khớp danh sách ở máy chủ. */
const TRANG_THAI_HOP_LE = new Set(["pending", "verified"])

/**
 * Chuỗi Decimal DƯƠNG theo hợp đồng của máy chủ: chữ số, tuỳ chọn phần thập
 * phân. Cố tình không nhận `0x10`, `1e3`, `+1` — `Number()` hiểu hết những
 * dạng đó (`Number("0x10") === 16`), nhưng máy chủ không bao giờ sinh ra
 * chúng, nên gặp một trong số đó nghĩa là dữ liệu không tới từ đường ta nghĩ.
 */
const DECIMAL_DUONG = /^\d+(\.\d+)?$/

/**
 * ISO-8601 dạng máy chủ sinh ra: `YYYY-MM-DDTHH:MM:SS` kèm phần giây lẻ tuỳ ý
 * và múi giờ tuỳ ý (`Z`, `+07:00`, hoặc không có).
 */
const ISO_8601 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$/

/** Trần số phần tử, khớp `MAX_DUPLICATE_CANDIDATES` ở máy chủ. */
export const MAX_DUPLICATE_ITEMS = 20

function isDuplicateInfo(v: unknown): v is DuplicatePaymentInfo {
  if (typeof v !== "object" || v === null) return false
  const o = v as Record<string, unknown>
  // Kiểm cả Ý NGHĨA, không chỉ kiểu. `typeof` một mình vẫn nhận
  // `payment_id: -1`, `amount: "không-phải-tiền"`, `payment_date` là chuỗi bất
  // kỳ — rồi giao diện dựng một khối cảnh báo từ rác và TẮT thông báo lỗi
  // chung. Không đọc được thì phải nói là không đọc được.
  if (!Number.isInteger(o.payment_id) || (o.payment_id as number) <= 0) return false
  // Số tiền phải là một Decimal DƯƠNG, kiểm bằng HÌNH DẠNG trước rồi mới đổi
  // sang số. `Number()` một mình quá dễ dãi: `""` thành 0, `"0x10"` thành 16,
  // `"1e3"` thành 1000 — không dạng nào trong số đó là thứ máy chủ sinh ra.
  if (typeof o.amount !== "string" || !DECIMAL_DUONG.test(o.amount)) return false
  if (Number(o.amount) <= 0) return false
  if (o.payment_date !== null) {
    if (typeof o.payment_date !== "string") return false
    // Đòi ISO-8601 thật, không chỉ "thứ `Date.parse` hiểu được": `Date.parse`
    // nhận cả "March 5, 2026" lẫn vài dạng riêng của từng trình duyệt, nên nó
    // không phải một hợp đồng — hai máy khác nhau sẽ đọc ra hai kết quả.
    if (!ISO_8601.test(o.payment_date)) return false
    if (Number.isNaN(Date.parse(o.payment_date))) return false
  }
  if (typeof o.status !== "string" || !TRANG_THAI_HOP_LE.has(o.status)) return false
  if (o.invoice_number !== null && typeof o.invoice_number !== "string") return false
  return true
}

/**
 * Đọc thân lỗi 409 "nghi trùng". Trả `null` nếu KHÔNG phải ca đó **hoặc**
 * payload không đúng cấu trúc.
 *
 * Vì sao kiểm từng trường thay vì tin `error_code`: người gọi dùng kết quả này
 * để **tắt thông báo lỗi chung** và chuyển sang khối cảnh báo. Nếu payload
 * méo mà ta vẫn nhận, người dùng bấm Lưu và không thấy phản hồi nào — im lặng
 * là trạng thái tệ nhất của một hàng rào. Trả `null` thì người gọi rơi về
 * đường lỗi chung, tức fail-closed.
 */
export function parseDuplicateSuspected(
  body: unknown,
): DuplicateSuspectedPayload | null {
  if (typeof body !== "object" || body === null) return null
  const o = body as Record<string, unknown>
  if (o.error_code !== PAYMENT_DUPLICATE_ERROR_CODE) return null
  if (!Array.isArray(o.duplicates)) return null
  if (typeof o.duplicates_truncated !== "boolean") return null
  // Rỗng cũng là méo: máy chủ chỉ ném lỗi này KHI có ứng viên, nên một danh
  // sách rỗng nghĩa là ta đang hiểu sai thân lỗi. Quá trần cũng vậy — máy chủ
  // cắt ở 20; nhiều hơn thế là dữ liệu không đến từ đường ta nghĩ.
  if (o.duplicates.length === 0) return null
  if (o.duplicates.length > MAX_DUPLICATE_ITEMS) return null
  if (!o.duplicates.every(isDuplicateInfo)) return null
  return {
    duplicates: o.duplicates as DuplicatePaymentInfo[],
    duplicates_truncated: o.duplicates_truncated,
  }
}

/*
 * 🔴 KHÔNG dựng lại luật dò trùng ở đây.
 *
 * Bản trước có một `locUngVienTrung` lọc theo số tiền + ngày lịch, và nó lệch
 * khỏi máy chủ ngay trong lần viết đầu tiên, ở hai chỗ mà giao diện **không
 * thể** biết:
 *
 *  - **tiền đã hoàn**: đường hoàn thường chỉ đổi `RefundRequest.status`, còn
 *    `Payment.status` vẫn là `verified`. Máy chủ loại phiếu đã hoàn ĐỦ bằng
 *    tổng `refunded`; giao diện không có con số đó nên sẽ cảnh báo và khoá nút
 *    Lưu cho một phiếu mà máy chủ đã bỏ qua từ lâu;
 *  - **"ngày lịch Việt Nam"**: `getFullYear()` đọc theo múi giờ MÁY NGƯỜI
 *    DÙNG, còn máy chủ cố định `Asia/Ho_Chi_Minh`. Một máy đặt UTC sẽ tính
 *    lệch một ngày và bỏ sót đúng ca sát biên.
 *
 * Luật sống ở một chỗ: `payment_repository.find_duplicate_candidates`. Giao
 * diện hỏi chính nó qua `GET /api/payments?fee_id=&duplicate_amount=
 * &duplicate_date=` rồi chỉ hiển thị kết quả.
 */
