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
 *   2. gửi phiếu → dòng VẪN `duplicate_review_required`  (chưa đồng nào vào sổ)
 *
 * Ca 2 xảy ra khi `duplicate_guard_version` của khoản phí đổi giữa lúc phiếu
 * được cấp và lúc nó được gửi — tức tập ứng viên người dùng vừa soát KHÔNG còn
 * là tập hiện tại. Máy chủ từ chối dòng đó rồi **cấp phiếu mới** ngay trong
 * cùng lượt (`payment_import_service.py`, cuối pha commit).
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
 */
export const LOI_TAP_DA_DOI =
  "Tập nghi trùng đã thay đổi — chưa dòng nào được ghi. " +
  "Danh sách bên dưới là ứng viên MỚI; hãy soát lại rồi xác nhận."
