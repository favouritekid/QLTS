/**
 * Canary cho đường ghi log của E2E.
 *
 * Kho này PUBLIC ⇒ log GitHub Actions đọc được công khai, và nightly seed CSDL
 * từ `scripts/seed_from_xlsx`. Vì vậy mọi thứ đi ra `console.log` trong lượt
 * E2E phải coi như đăng lên một trang công cộng.
 *
 * Ca kiểm dưới đây nạp dữ liệu canary — họ tên, phường/xã, trường THPT, điện
 * thoại, CCCD, email, token, mật khẩu — rồi khẳng định KHÔNG chuỗi nào trong
 * số đó xuất hiện ở đầu ra. Đây là phép kiểm chống hồi quy cho một lớp lỗi,
 * không phải kiểm một hàm: thêm trường mới vào API mà quên khai báo an toàn
 * thì nó bị CHE, và ca này vẫn xanh — fail-closed.
 *
 * Vì sao tệp này nằm ngoài `src/test/e2e/`: `vitest.config` loại trừ thư mục
 * ấy (spec Playwright không chạy được dưới vitest), nên một canary đặt trong
 * đó sẽ KHÔNG bao giờ chạy — đúng hình mẫu "cổng canh trên giấy".
 */

import { describe, it, expect } from "vitest";
import {
  safeBody,
  summarizeApiError,
  correlationHash,
  SAFE_KEYS,
} from "./e2e/helpers/log-redaction";

/** Mỗi chuỗi ở đây, nếu lọt ra log công khai, là một sự cố. */
const CANARIES = {
  hoTen: "Nguyễn Thị Bích Trâm",
  phuongXa: "Phường Tân Lập",
  truongThpt: "THPT Buôn Ma Thuột",
  diaChi: "số 12 đường Lê Duẩn, Phường Tân Lập",
  dienThoai: "0905123456",
  cccd: "066301004321",
  email: "bichtram.nguyen@example.com",
  token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.canary.signature",
  matKhau: "Abc@123456789",
  totp: "482915",
} as const;

function assertNoCanary(output: string, except: string[] = []) {
  for (const [ten, giaTri] of Object.entries(CANARIES)) {
    if (except.includes(ten)) continue;
    expect(
      output.includes(giaTri),
      `RÒ RỈ: canary "${ten}" xuất hiện nguyên văn trong log.\nĐầu ra: ${output}`
    ).toBe(false);
  }
}

describe("summarizeApiError — danh sách trường được phép", () => {
  it("không in detail dù detail mang tên phường và tên trường", () => {
    const body = JSON.stringify({
      detail: `KV_UNRESOLVED: không tra được ${CANARIES.truongThpt} cho ${CANARIES.phuongXa}`,
      error_code: "BUSINESS_RULE_VIOLATION",
    });
    const out = summarizeApiError(400, body);

    assertNoCanary(out);
    expect(out).toContain("status=400");
    expect(out).toContain("error_code=BUSINESS_RULE_VIOLATION");
    expect(out).toMatch(/detail=<str:\d+ h=[0-9a-f]{8}>/);
  });

  it("in TÊN TRƯỜNG không hợp lệ nhưng không in giá trị đã gửi", () => {
    const body = JSON.stringify({
      detail: "Request validation failed",
      error_code: "VALIDATION_ERROR",
      errors: [
        {
          type: "missing",
          loc: ["body", "admission_round_id"],
          msg: "Field required",
          input: { full_name: CANARIES.hoTen, phone: CANARIES.dienThoai },
        },
      ],
    });
    const out = summarizeApiError(422, body);

    assertNoCanary(out);
    // Vẫn phải chẩn đoán được: tên trường thiếu là hằng của lược đồ.
    expect(out).toContain("invalid_fields=body.admission_round_id[missing]");
  });

  it("thân phi-JSON không lọt một byte nội dung nào", () => {
    const html = `<html><body>Xin chào ${CANARIES.hoTen} — ${CANARIES.email}</body></html>`;
    const out = summarizeApiError(500, html);

    assertNoCanary(out);
    expect(out).toMatch(/body=<non-JSON:\d+B h=[0-9a-f]{8}>/);
  });

  it("không in errors[].msg (backend có chỗ nhét giá trị vào msg)", () => {
    const body = JSON.stringify({
      error_code: "VALIDATION_ERROR",
      errors: [
        { type: "value_error", loc: ["body", "phone"], msg: `Số ${CANARIES.dienThoai} đã tồn tại` },
      ],
    });
    assertNoCanary(summarizeApiError(422, body));
  });
});

describe("safeBody — khoá lạ bị che theo mặc định", () => {
  it("hồ sơ đầy đủ chỉ lộ ID và mã, không lộ nhân thân", () => {
    const profile = {
      id: 83,
      lead_id: 41,
      status: "draft",
      version: 3,
      full_name: CANARIES.hoTen,
      phone: CANARIES.dienThoai,
      citizen_id: CANARIES.cccd,
      email: CANARIES.email,
      permanent_address: CANARIES.diaChi,
      graduation_school: CANARIES.truongThpt,
      ward: CANARIES.phuongXa,
    };
    const out = safeBody(profile);

    assertNoCanary(out);
    expect(out).toContain("id=83");
    expect(out).toContain("lead_id=41");
    expect(out).toContain('status="draft"');
    // Khoá lạ vẫn lộ SỰ TỒN TẠI và kiểu — đủ để chẩn đoán hình dạng phản hồi.
    expect(out).toMatch(/full_name=<str:\d+ h=[0-9a-f]{8}>/);
  });

  it("token và mật khẩu bị che kể cả khi lồng sâu", () => {
    const loginBody = {
      ok: true,
      access_token: CANARIES.token,
      refresh_token: CANARIES.token,
      user: { id: 7, full_name: CANARIES.hoTen, password: CANARIES.matKhau },
      mfa: { otp: CANARIES.totp },
    };
    assertNoCanary(safeBody(loginBody));
  });

  it("mảng bản ghi không lộ nội dung phần tử", () => {
    const rows = Array.from({ length: 25 }, (_, i) => ({
      id: i + 1,
      full_name: CANARIES.hoTen,
      phone: CANARIES.dienThoai,
    }));
    const out = safeBody(rows);

    assertNoCanary(out);
    expect(out).toContain("(n=25)");
  });

  it("chuỗi dài dưới khoá an toàn vẫn bị che", () => {
    // `status` là khoá an toàn, nhưng nếu backend nhét câu văn vào đó thì nó
    // không còn là enum nữa. Ngưỡng 40 ký tự bắt đúng ca này.
    const out = safeBody({ status: `${CANARIES.diaChi} ${CANARIES.hoTen}` });
    assertNoCanary(out);
  });

  it("giá trị null và kiểu lạ không làm vỡ hàm", () => {
    expect(safeBody(null)).toBe("null");
    expect(safeBody(undefined)).toBe("null");
    expect(safeBody([])).toBe("[]");
    expect(safeBody(42)).toBe("<number>");
  });
});

describe("correlationHash", () => {
  it("ổn định giữa các lượt và khác nhau cho thông điệp khác nhau", () => {
    expect(correlationHash("abc")).toBe(correlationHash("abc"));
    expect(correlationHash("abc")).not.toBe(correlationHash("abd"));
    expect(correlationHash("")).toMatch(/^[0-9a-f]{8}$/);
  });
});

describe("SAFE_KEYS — hợp đồng của danh sách cho phép", () => {
  it("không chứa khoá nào mang nhân thân", () => {
    const cam = [
      "full_name", "name", "phone", "email", "citizen_id", "address",
      "permanent_address", "ward", "district", "province", "school",
      "graduation_school", "dob", "date_of_birth", "detail", "msg",
      "input", "password", "token", "access_token",
    ];
    for (const k of cam) {
      expect(SAFE_KEYS.has(k), `SAFE_KEYS không được chứa "${k}"`).toBe(false);
    }
  });
});
