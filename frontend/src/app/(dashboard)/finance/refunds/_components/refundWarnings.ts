import type { RefundRequest } from "@/types/finance.types"

/**
 * Phiếu này còn CHỜ CHI hay đã xong đời?
 *
 * Mọi cảnh báo về số tiền chỉ có nghĩa với phiếu chưa ra tiền. `rejected` thì
 * không bao giờ chi, `refunded` thì đã chi rồi — cảnh báo lúc đó chỉ gây hoang mang.
 */
export function isPendingPayout(refund: Pick<RefundRequest, "status">): boolean {
  return refund.status === "pending" || refund.status === "approved"
}

/**
 * Có nên tô đỏ "vượt số còn hoàn được" cho dòng này?
 *
 * 🔴 Cái bẫy: `refundable_amount` = tiền phiếu thu − TỔNG các phiếu đã chi, và tổng
 * đó bao gồm **chính dòng này** khi nó đã `refunded`. Nên một phiếu hoàn TOÀN PHẦN
 * sau khi chi xong luôn có `amount > refundable` (refundable về 0) và sẽ đỏ oan mãi
 * mãi. Không phải ca hiếm: 7/7 phiếu chờ chi trên prod ngày 30-07 đều toàn phần,
 * tức bảng sẽ đỏ sạch ngay sau khi kế toán chi.
 *
 * Vì vậy phép so chỉ áp cho phiếu CHƯA chi — đúng lúc nó còn ý nghĩa: chặn kế toán
 * bấm một cái nút mà backend sẽ từ chối.
 */
export function isOverAsking(
  refund: Pick<RefundRequest, "status" | "amount" | "refundable_amount">,
): boolean {
  if (!isPendingPayout(refund)) return false
  if (refund.refundable_amount === null) return false
  return Number(refund.amount) > Number(refund.refundable_amount)
}
