/**
 * Guard: E2E seed-credential parity
 *
 * ROOT CAUSE được chốt chặn tại đây: credential literal (admin password,
 * officer username/password) bị copy-paste khắp ~18 file spec trong
 * `src/test/e2e` và drift khỏi `Backend_FastAPI/seed_data_template.xlsx`
 * (sheet `2_TaiKhoan`) sau khi xlsx đổi account:
 *     vothuhien      → vothithuthuhien
 *     @Matkhau123!   → Abc@123456789   (mọi officer/manager/accountant)
 *     Admin@12345    → Admin@123        (admin)
 * Nightly-regression fail 10+ run liên tiếp với
 *     "Login failed for admin: 401" + "Login failed for vothuhien: 401".
 *
 * SOURCE OF TRUTH cho credential = seed_data_template.xlsx, sheet 2_TaiKhoan:
 *     admin                              / Admin@123
 *     <mọi officer / manager / accountant> / Abc@123456789
 *
 * Guard quét toàn bộ `*.spec.ts` + `auth.setup.ts` và FAIL nếu các giá trị
 * credential ĐÃ CHẾT tái xuất hiện (copy-paste từ branch cũ / muscle memory).
 * Đây KHÔNG phải tautological: đọc file thật trên đĩa, không mock.
 *
 * Khi xlsx đổi account lần nữa: cập nhật fallback trong các spec + thêm giá
 * trị cũ vào `DEAD_CREDENTIALS` dưới đây để chặn regression.
 *
 * Lưu ý: các password test-created (vd "Admin@12345!", "Officer@12345!",
 * "Test@1234567!", "E2eQuota@12345") do helper `POST /api/admin/users` tạo
 * user mới — KHÔNG phải login vào account seed → cố ý KHÔNG bị chặn (regex
 * dưới đây loại trừ chúng bằng ràng buộc dấu nháy đóng / khác chuỗi).
 */
import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "fs";
import path from "path";

const E2E_DIR = path.resolve(process.cwd(), "src/test/e2e");

// Giá trị credential ĐÃ CHẾT — không được phép xuất hiện trong bất kỳ spec nào.
const DEAD_CREDENTIALS: { label: string; pattern: RegExp }[] = [
  { label: 'officer password cũ "@Matkhau123!"', pattern: /@Matkhau123!/ },
  // username phải bị bao bởi nháy (không khớp "vothithuthuhien" hay email)
  { label: 'officer username cũ "vothuhien"', pattern: /["']vothuhien["']/ },
  { label: 'admin password cũ "@Abc12345!"', pattern: /@Abc12345!/ },
  // "Admin@12345" theo sau bởi nháy đóng — KHÔNG khớp "Admin@12345!" (test-created)
  { label: 'admin password cũ "Admin@12345"', pattern: /Admin@12345["']/ },
];

describe("E2E seed-credential parity guard", () => {
  const files = readdirSync(E2E_DIR).filter(
    (f) => f.endsWith(".spec.ts") || f === "auth.setup.ts",
  );

  it("tìm thấy ít nhất 1 spec để quét (chống vacuous pass)", () => {
    expect(files.length).toBeGreaterThan(0);
  });

  for (const file of files) {
    it(`${file} không chứa credential đã chết`, () => {
      const content = readFileSync(path.join(E2E_DIR, file), "utf8");
      const violations = DEAD_CREDENTIALS.filter(({ pattern }) =>
        pattern.test(content),
      ).map(({ label }) => label);

      expect(
        violations,
        `${file} chứa credential đã chết: ${violations.join("; ")}. ` +
          `Đồng bộ fallback với seed_data_template.xlsx ` +
          `(admin=Admin@123, officer/manager/accountant=Abc@123456789).`,
      ).toEqual([]);
    });
  }
});
