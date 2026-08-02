/**
 * MỘT nguồn duy nhất quyết định "có được xoá cookie phiên hay không".
 *
 * `client.ts` có hai lối độc lập cùng dẫn tới quyết định đó — interceptor 401 và
 * nhánh CSRF-recovery. Trước đây mỗi lối tự phân loại lỗi, nên chỉ cần thêm một
 * mã terminal ở một nơi là hai lối kết luận khác nhau về CÙNG một lỗi, và người
 * dùng gặp hành vi khác nhau tuỳ chỗ lỗi nổ ra.
 *
 * Đây là test TĨNH trên mã nguồn, cố ý: bất biến cần khoá là "không tồn tại bản
 * sao thứ hai", mà một test hành vi chỉ chứng minh được lối nào nó đi qua —
 * không chứng minh được lối còn lại KHÔNG có bản sao riêng.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const clientSource = readFileSync(
  join(process.cwd(), "src/lib/api/client.ts"),
  "utf8",
);

describe("client.ts — một classifier duy nhất", () => {
  // Classifier cũ đã bị gỡ. Nó quay lại = hai nguồn quyết định.
  it("KHÔNG còn `shouldLogoutAfterRefreshFailure`", () => {
    expect(clientSource).not.toContain("shouldLogoutAfterRefreshFailure");
  });

  it("dùng `shouldClearAuthCookies` từ ./refresh, không tự phân loại lại", () => {
    expect(clientSource).toContain("shouldClearAuthCookies");
    // Tự đọc `error.response.status === 401` để QUYẾT ĐỊNH xoá cookie là dấu
    // hiệu một bản sao classifier đang hình thành.
    const tuPhanLoai = /status\s*===\s*401[\s\S]{0,120}(logout|clear|xo[áa])/i;
    expect(tuPhanLoai.test(clientSource)).toBe(false);
  });

  // Cả hai lối thoát phiên phải đi qua đúng một hàm dọn.
  it("mọi lối thoát phiên gọi `performSessionExpiredLogout`", () => {
    const soLanGoi = (clientSource.match(/performSessionExpiredLogout\(/g) ?? [])
      .length;
    // 1 định nghĩa + 2 caller (interceptor 401, CSRF-recovery).
    expect(soLanGoi).toBeGreaterThanOrEqual(3);
  });
});
