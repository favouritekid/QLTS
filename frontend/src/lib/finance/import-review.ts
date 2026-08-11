// src/lib/finance/import-review.ts
/**
 * Phiếu nghi trùng của đường NHẬP LÔ — phần thuần tuý, không React.
 *
 * Khác đường ghi tay (`duplicate-review.ts`, máy trạng thái quanh thân lỗi 409):
 * nhập lô trả **200** kèm `rows[]`, và một dòng bị hàng rào giữ lại nằm ngay
 * trong thân thành công ấy. Chính vì vậy hai ca hoàn toàn ngược nhau đi chung
 * một đường:
 *
 *   1. gửi phiếu → dòng vào sổ  (việc đã xong)
 *   2. gửi phiếu → dòng VẪN `duplicate_review_required`  (dòng ấy chưa vào sổ)
 *
 * Hai ca này KHÔNG loại trừ nhau trong một lượt: `committed_count` đếm riêng
 * lượt đang xét, nên một lần gửi hai phiếu có thể ghi được một dòng và bị từ
 * chối dòng kia.
 *
 * Ca 2 xảy ra khi phiếu không còn hiệu lực lúc tới máy chủ — thường vì
 * `duplicate_guard_version` của khoản phí đã đổi, nhưng hết hạn hay đổi người
 * dùng cũng cho cùng kết quả. Máy chủ từ chối dòng đó rồi **cấp phiếu mới**
 * ngay trong cùng lượt (`payment_import_service.py`, cuối pha commit).
 *
 * Đó là chỗ nguy hiểm: nếu giao diện chỉ im lặng nhận phiếu mới và báo thành
 * công, hàng rào chỉ còn là một cú bấm thừa — bấm hai lần là qua, mà chẳng ai
 * phải nhìn lại tập ứng viên mới. Hàm dưới đây tồn tại để ba nơi (hook toast,
 * màn kết quả, đường mở lại từ Lịch sử lô) cùng nhận ra ca 2 theo MỘT phép
 * đo, thay vì mỗi nơi tự suy từ vài con số đếm.
 */

/** Phần của một dòng lô mà phép đo này cần. Cố ý hẹp hơn schema đầy đủ. */
export interface DongLoImport {
  row_no: number
  commit_status: string
  review_token?: string | null
}

export const CHO_SOAT = "duplicate_review_required"

/**
 * Những dòng ĐÃ gửi phiếu mà máy chủ vẫn giữ ở `duplicate_review_required`.
 *
 * Đọc theo `row_no` của chính lượt gửi, KHÔNG theo số đếm: `review_required_count`
 * không phân biệt "dòng người dùng vừa xác nhận nhưng bị từ chối" với "dòng
 * chưa ai đụng tới", mà hai thứ đó đòi hai phản ứng khác hẳn nhau.
 *
 * Không gửi phiếu nào (`undefined`/rỗng) ⇒ mảng rỗng: lượt commit đầu tiên có
 * dòng bị giữ là chuyện bình thường, không phải phiếu hết hiệu lực.
 */
export function dongPhieuHetHieuLuc(
  daGui: ReadonlyArray<{ row_no: number }> | undefined,
  rows: ReadonlyArray<DongLoImport> | undefined,
): number[] {
  if (!daGui?.length || !rows?.length) return []
  const daGuiSet = new Set(daGui.map((r) => r.row_no))
  return rows
    .filter((r) => daGuiSet.has(r.row_no) && r.commit_status === CHO_SOAT)
    .map((r) => r.row_no)
    .sort((a, b) => a - b)
}

/** Có phiếu nào vừa gửi bị từ chối không? */
export function coPhieuHetHieuLuc(
  daGui: ReadonlyArray<{ row_no: number }> | undefined,
  rows: ReadonlyArray<DongLoImport> | undefined,
): boolean {
  return dongPhieuHetHieuLuc(daGui, rows).length > 0
}

/**
 * Câu nói cho người dùng khi phiếu hết hiệu lực. Để ở đây vì cả toast lẫn hai
 * khối cảnh báo trên màn hình phải nói CÙNG một điều — lệch câu chữ giữa chúng
 * là mở lại đúng khe hiểu nhầm mà việc này đang đóng.
 *
 * 🔴 Chỉ nói thứ response CHỨNG MINH được. Bản trước viết "tập nghi trùng đã
 * thay đổi — chưa dòng nào được ghi", và sai ở cả hai vế:
 *
 *   * NGUYÊN NHÂN: response chỉ cho biết dòng vừa gửi vẫn bị giữ. Phiếu hết
 *     hiệu lực vì `duplicate_guard_version` đổi là một khả năng, nhưng phiếu
 *     hết hạn hay đổi người dùng cũng cho đúng kết quả ấy. Quy cho một nguyên
 *     nhân cụ thể là đoán.
 *   * PHẠM VI: `committed_count` là số dòng ghi được ở LƯỢT này
 *     (`payment_import_service.py`, `CommitResult`), nên một lượt có thể vừa
 *     ghi xong dòng A vừa từ chối phiếu cũ của dòng B. Khi đó "chưa dòng nào
 *     được ghi" tự mâu thuẫn với "Đã ghi 1 dòng" ngay câu sau.
 */
export const LOI_TAP_DA_DOI =
  "Một hoặc nhiều dòng vừa xác nhận chưa được ghi vì phiếu xác nhận không " +
  "còn hiệu lực. Danh sách bên dưới là snapshot hiện tại; hãy soát lại."

/**
 * Bản cho toast: không có "bên dưới" để trỏ tới, nên nêu SỐ dòng bị từ chối.
 * Người gọi ghép thêm phần đếm của cả lượt (đã ghi bao nhiêu, còn bao nhiêu
 * chờ soát) — hai con số ấy mới trả lời được câu hỏi kế tiếp của kế toán.
 */
export function cauPhieuHetHieuLuc(soDong: number): string {
  return (
    `${soDong} dòng vừa xác nhận chưa được ghi vì phiếu xác nhận không còn ` +
    "hiệu lực — mở lại lô và soát snapshot hiện tại."
  )
}
