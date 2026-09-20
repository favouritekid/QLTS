// src/lib/api/refresh-coordination/proof.contract.test.ts
/**
 * Tuổi của bằng chứng — bất biến mà nếu vỡ thì vỡ IM LẶNG.
 *
 * Gỡ vế trên (`age <= WINDOW`) thì một nhật ký `success` của chu kỳ trước biến
 * mọi lần làm mới sau thành no-op: hàm báo "xong" mà chưa hề POST, access
 * token chết ở phút 15, và người dùng quay vòng giữa trang đích và
 * `/session-refresh`. Gỡ vế dưới (`age >= 0`) thì mọi bản ghi lệch giờ về phía
 * tương lai lọt qua như bằng chứng tươi — cùng hậu quả, chỉ khó thấy hơn.
 *
 * Hai vế nằm ở HAI nhóm `describe` riêng và không ca nào chạm cả hai: gộp lại
 * thì gỡ một vế cũng đỏ đúng những ca mà gỡ vế kia làm đỏ, và ta mất khả năng
 * đọc ra vế nào đã hỏng.
 *
 * Các mốc tuổi viết bằng SỐ THẬT chứ không suy từ `FRESH_PROOF_WINDOW_MS`: nếu
 * lấy hằng làm kỳ vọng thì đổi hằng cũng tự sửa luôn kỳ vọng, và biên không
 * còn được canh.
 */
import { describe, it, expect } from "vitest";

import { isProofFresh } from "./proof";

/** Mốc "bây giờ" cố định — mọi ca chỉ đổi TUỔI của bản ghi. */
const NOW = 1_800_000_000_000;

/** Bản ghi được viết lúc nào, nếu bây giờ nó `tuoi` mili-giây tuổi. */
function vietLuc(tuoi: number): number {
  return NOW - tuoi;
}

describe("tuổi KHÔNG ÂM — vế `age <= FRESH_PROOF_WINDOW_MS`", () => {
  it("tuổi 0 (vừa viết xong) ⇒ còn là bằng chứng", () => {
    expect(isProofFresh(vietLuc(0), NOW)).toBe(true);
  });

  it("tuổi 29.999ms (sát biên, chưa chạm) ⇒ còn là bằng chứng", () => {
    expect(isProofFresh(vietLuc(29_999), NOW)).toBe(true);
  });

  it("tuổi 30.000ms (ĐÚNG biên) ⇒ vẫn còn — biên là bao gồm", () => {
    expect(isProofFresh(vietLuc(30_000), NOW)).toBe(true);
  });

  it("tuổi 30.001ms (quá biên đúng 1ms) ⇒ HẾT là bằng chứng", () => {
    expect(isProofFresh(vietLuc(30_001), NOW)).toBe(false);
  });

  it("tuổi 13 phút (nhật ký của chu kỳ proactive TRƯỚC) ⇒ hết là bằng chứng", () => {
    expect(isProofFresh(vietLuc(13 * 60_000), NOW)).toBe(false);
  });
});

describe("tuổi ÂM — vế `age >= 0`, bản ghi đến TỪ TƯƠNG LAI", () => {
  // Tuổi âm nghĩa là bản ghi mang mốc thời gian muộn hơn "bây giờ": đồng hồ
  // của tab ghi lệch, hoặc người dùng chỉnh giờ lùi giữa hai chu kỳ. Nó không
  // nói được gì về việc token nó chứng minh còn hạn hay không.
  it("tuổi -1ms (lệch đúng 1ms) ⇒ KHÔNG được coi là bằng chứng", () => {
    expect(isProofFresh(vietLuc(-1), NOW)).toBe(false);
  });

  it("tuổi -5 phút (đồng hồ lùi hẳn) ⇒ KHÔNG được coi là bằng chứng", () => {
    expect(isProofFresh(vietLuc(-5 * 60_000), NOW)).toBe(false);
  });
});
