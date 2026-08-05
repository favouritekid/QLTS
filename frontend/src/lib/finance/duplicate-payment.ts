// src/lib/finance/duplicate-payment.ts
/**
 * Cảnh báo ghi trùng phiếu thu — phần thuần tuý, không React.
 *
 * Ba việc, tách khỏi component để kiểm được từng cái một:
 *  1. **Dấu vân tay** của một lần ghi — thứ quyết định một xác nhận còn hiệu
 *     lực hay đã hết hạn;
 *  2. **Đọc thân lỗi 409** một cách phòng thủ — payload méo phải bị từ chối
 *     thẳng, không được đoán;
 *  3. **Luật lọc ứng viên** cho lớp cảnh báo sớm ở giao diện.
 *
 * ⚠️ Điều 3 là bản SAO của luật đang chạy ở máy chủ
 * (`payment_repository.find_duplicate_candidates`). Hai bản không dùng chung
 * được vì khác ngôn ngữ, nên chúng phải được canh bằng **cùng một bộ ca biên**
 * (0 / 3 / 4 ngày, bằng tiền / khác tiền) ở cả hai phía. Lệch một trong hai
 * bên là giao diện báo oan hoặc bỏ sót — nhưng **máy chủ vẫn là nơi quyết
 * định cuối**: lớp này chỉ để người ghi thấy sớm, danh sách của nó có thể bị
 * cắt theo trang.
 */

/** Cửa sổ dò trùng, tính bằng NGÀY LỊCH. Phải khớp `window_days` ở máy chủ. */
export const DUPLICATE_WINDOW_DAYS = 3

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
  invoiceId: number
  feeId: number
  amount?: number | null
  paymentDate?: string | null
}): string {
  return [
    input.invoiceId,
    input.feeId,
    input.amount ?? "",
    input.paymentDate ?? "",
  ].join("|")
}

function isDuplicateInfo(v: unknown): v is DuplicatePaymentInfo {
  if (typeof v !== "object" || v === null) return false
  const o = v as Record<string, unknown>
  return (
    typeof o.payment_id === "number" &&
    typeof o.amount === "string" &&
    (o.payment_date === null || typeof o.payment_date === "string") &&
    typeof o.status === "string" &&
    (o.invoice_number === null || typeof o.invoice_number === "string")
  )
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
  if (!o.duplicates.every(isDuplicateInfo)) return null
  return {
    duplicates: o.duplicates as DuplicatePaymentInfo[],
    duplicates_truncated: o.duplicates_truncated,
  }
}

/** "YYYY-MM-DD" hoặc ISO đầy đủ → số ngày kể từ mốc, theo LỊCH ĐỊA PHƯƠNG. */
function toLocalDayIndex(value: string): number | null {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return null
  return Math.floor(
    Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / 86_400_000,
  )
}

/** Lệch bao nhiêu NGÀY LỊCH giữa hai mốc; `null` nếu không đọc được. */
export function calendarDaysApart(a: string, b: string): number | null {
  const ia = toLocalDayIndex(a)
  const ib = toLocalDayIndex(b)
  if (ia === null || ib === null) return null
  return Math.abs(ia - ib)
}

/** Trạng thái phiếu còn được coi là tiền — khớp luật máy chủ. */
const TRANG_THAI_CON_HIEU_LUC = new Set(["pending", "verified"])

export interface UngVienTrungInput {
  id: number
  amount: string
  status: string
  payment_date: string | null
}

/**
 * Lọc những phiếu mà một khoản thu sắp ghi có thể đang lặp lại.
 *
 * Cùng luật với máy chủ: **số tiền bằng nhau** và lệch không quá
 * `DUPLICATE_WINDOW_DAYS` **ngày lịch**, chỉ `pending`/`verified`. Cố tình
 * KHÔNG có luật theo mã tham chiếu — form prefill mã hồ sơ nên mọi lần thu góp
 * của cùng hồ sơ đều trùng mã, và cảnh báo oan mọi lần thu thứ hai là cách
 * nhanh nhất khiến người dùng ngừng đọc cảnh báo.
 */
export function locUngVienTrung(
  items: UngVienTrungInput[],
  input: { amount?: number | null; paymentDate?: string | null },
): UngVienTrungInput[] {
  const { amount, paymentDate } = input
  if (amount == null || !paymentDate) return []
  return items.filter((p) => {
    if (!TRANG_THAI_CON_HIEU_LUC.has(p.status)) return false
    if (Number(p.amount) !== amount) return false
    if (!p.payment_date) return false
    const lech = calendarDaysApart(p.payment_date, paymentDate)
    return lech !== null && lech <= DUPLICATE_WINDOW_DAYS
  })
}
