// src/lib/api/refresh-coordination/proof.ts
/**
 * TUỔI của một bằng chứng "đã có token mới" — và chỉ có thế.
 *
 * Một bản ghi `success` trong nhật ký chứng minh **đã có token mới tại thời
 * điểm bản ghi ấy được viết**. Nó KHÔNG chứng minh token ấy còn hạn bây giờ.
 * Access token sống 15 phút; một bản ghi của chu kỳ trước (hook proactive chạy
 * mỗi 13 phút) vẫn mang `resultKind: "success"` y hệt một bản ghi vừa viết ba
 * giây trước. Không phân biệt hai thứ đó là biến mọi lần làm mới sau thành
 * no-op: hàm trả về "xong" mà chưa hề POST, token thật chết ở phút 15, và
 * người dùng quay vòng giữa trang đích và `/session-refresh`.
 *
 * ── Vì sao là MODULE RIÊNG, không nằm trong `refresh.ts` ─────────────────────
 *
 * Hai nơi phải hỏi cùng câu hỏi này: `lock.ts` (cổng giành quyền POST) và
 * `refresh.ts` (đọc kết quả của tab khác). `lock.ts` KHÔNG import `refresh.ts`
 * — và không được phép, vì `refresh.ts` đã import `lock.ts`; đặt hằng ở
 * `refresh.ts` là tạo vòng import. Hai bản sao của cùng một ngưỡng thì sớm
 * muộn lệch nhau đúng ở chỗ đắt nhất, nên nó ở đây, một chỗ, không phụ thuộc
 * ai.
 */

/**
 * Một bản ghi bao lâu tuổi thì còn được coi là bằng chứng "token mới còn hạn".
 *
 * Phải BAO ĐƯỢC một cuộc đua giữa các tab (vài giây, và lease sống 20 giây)
 * nhưng NHỎ HƠN NHIỀU chu kỳ proactive 13 phút — nếu không, nhật ký của chu kỳ
 * trước sẽ biến chu kỳ sau thành no-op và access token chết trong khoảng trống.
 */
export const FRESH_PROOF_WINDOW_MS = 30_000;

/**
 * Bằng chứng viết lúc `writtenAt` có còn dùng được tại `now` không?
 *
 * ⚠️ Tuổi bị chặn ở CẢ HAI phía. `writtenAt` có thể do TAB KHÁC ghi, tức đọc
 * từ một đồng hồ khác; người dùng cũng có thể chỉnh giờ lùi giữa hai chu kỳ.
 * Tuổi ÂM nghĩa là bản ghi "đến từ tương lai" — nó không nói được gì về việc
 * token nó chứng minh còn hạn hay không. Bỏ vế dưới thì mọi bản ghi lệch giờ
 * về phía tương lai đều lọt qua như bằng chứng tươi, tức rơi lại đúng ca mà cả
 * cửa sổ này sinh ra để chặn.
 *
 * `NaN` rơi vào phía fail-closed mà không cần vế kiểm riêng: mọi phép so sánh
 * với `NaN` đều `false`.
 */
export function isProofFresh(writtenAt: number, now: number): boolean {
  const age = now - writtenAt;
  return age >= 0 && age <= FRESH_PROOF_WINDOW_MS;
}
