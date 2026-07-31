/**
 * Tests cho middleware `proxy` — trọng tâm: access token HẾT HẠN không còn tự
 * kết luận "hết phiên".
 *
 * Bối cảnh: `refresh_token` sống 30 ngày nhưng backend set `Path=/api`, nên
 * middleware (chạy trên `/dashboard`, `/admissions/...`) KHÔNG bao giờ nhận
 * được cookie đó — nó không có dữ liệu để kết luận phiên đã chết. Trước đây nó
 * vẫn xoá `access_token` và 307 về /login, biến mọi lần F5 / mở tab mới sau 15
 * phút thành một lần đăng nhập lại, kể cả khi client vừa cố ý giữ phiên qua
 * một refresh hỏng tạm thời.
 *
 * Chạy middleware THẬT với `NextRequest` thay vì tách một hàm thuần ra test:
 * quyết định nằm ở chính nhánh này, và một test trên hàm phụ sẽ vẫn xanh khi
 * nhánh trong middleware bị đổi.
 */
import { describe, it, expect } from "vitest";
import { NextRequest } from "next/server";

import { proxy } from "./proxy";

const BASE = "https://qlts.tnpc.edu.vn";

/** JWT không ký (middleware chỉ decode payload, không verify chữ ký). */
function makeToken(payload: Record<string, unknown>): string {
  const b64 = (obj: unknown) =>
    Buffer.from(JSON.stringify(obj))
      .toString("base64")
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64(payload)}.sig`;
}

function accessToken(expiresInSeconds: number, role = "officer") {
  return makeToken({
    sub: "officer1",
    user_id: 25,
    role,
    type: "access",
    exp: Math.floor(Date.now() / 1000) + expiresInSeconds,
  });
}

function requestWith(token: string | undefined, path = "/admissions/611") {
  const req = new NextRequest(new URL(path, BASE));
  if (token) req.cookies.set("access_token", token);
  return req;
}

describe("proxy — access token hết hạn", () => {
  // Ca sự cố: officer rời máy hơn 15 phút rồi F5 (hoặc mở hồ sơ ở tab mới).
  it("hết hạn gần đây → sang /session-refresh kèm return-url", () => {
    const res = proxy(requestWith(accessToken(-120))); // hết hạn 2 phút trước

    expect(res.status).toBe(307);
    const location = res.headers.get("location") ?? "";
    expect(location).toContain("/session-refresh");
    expect(location).toContain("redirect=");
    expect(location).toContain("admissions");
  });

  // KHÔNG được `next()`: Server Component sẽ fetch ngay bằng token hết hạn →
  // 401 → server.ts redirect /login?force_login=true → nhánh force_login xoá
  // SẠCH cả refresh_token, mất phiên trước khi client kịp hydrate.
  it("hết hạn gần đây → KHÔNG cho request đi thẳng vào route SSR", () => {
    const res = proxy(requestWith(accessToken(-120)));

    expect(res.status).not.toBe(200);
    expect(res.headers.get("location") ?? "").not.toContain("/login");
  });

  it("hết hạn gần đây → KHÔNG xoá cookie nào (refresh_token là thứ cứu phiên)", () => {
    const res = proxy(requestWith(accessToken(-120)));

    const setCookie = res.headers.get("set-cookie") ?? "";
    expect(setCookie).not.toContain("access_token=;");
    expect(setCookie).not.toContain("refresh_token=;");
  });

  it("hết hạn cả tuần (refresh_token vẫn còn) → vẫn sang /session-refresh", () => {
    const res = proxy(requestWith(accessToken(-7 * 24 * 3600)));

    expect(res.status).toBe(307);
    expect(res.headers.get("location") ?? "").toContain("/session-refresh");
  });

  it("trang /session-refresh phải công khai (nếu không sẽ tự đá chính nó → vòng lặp)", () => {
    const res = proxy(new NextRequest(new URL("/session-refresh?redirect=/admissions/611", BASE)));

    expect(res.status).toBe(200);
    expect(res.headers.get("location")).toBeNull();
  });

  // Quá cửa sổ refresh_token (30 ngày) → không còn gì để cứu, đá về login luôn
  // thay vì cho user nhìn trang rỗng rồi mới bị đá.
  it("hết hạn quá 30 ngày → redirect /login kèm return-url", () => {
    const res = proxy(requestWith(accessToken(-31 * 24 * 3600)));

    expect(res.status).toBe(307);
    const location = res.headers.get("location") ?? "";
    expect(location).toContain("/login");
    expect(location).toContain("redirect=");
  });
});

describe("proxy — không có access cookie", () => {
  // "Không có cookie ⇒ chưa từng đăng nhập" là suy luận SAI với đúng những
  // người đang dùng hệ thống: mọi phiên tạo TRƯỚC khi cookie được nới tuổi thọ
  // vẫn mất cookie sau 15 phút (cả cơ sở người dùng, trong 30 ngày đầu sau
  // deploy), chưa kể eviction. `refresh_token` (Path=/api) có thể vẫn sống mà
  // middleware không nhìn thấy.
  it("không có access_token → sang /session-refresh kèm return-url", () => {
    const res = proxy(requestWith(undefined));

    expect(res.status).toBe(307);
    const location = res.headers.get("location") ?? "";
    expect(location).toContain("/session-refresh");
    expect(location).toContain("redirect=");
    expect(location).toContain("admissions");
  });

  it("không có access_token → KHÔNG xoá cookie nào", () => {
    const res = proxy(requestWith(undefined));

    const setCookie = res.headers.get("set-cookie") ?? "";
    expect(setCookie).not.toContain("refresh_token=;");
    expect(setCookie).not.toContain("access_token=;");
  });

  // Cùng một hàm dựng URL cho mọi nhánh, nên return-url ngoại lai bị loại ở
  // MỌI lối vào — không nhánh nào được quên `isValidRedirect`.
  it("return-url ngoại lai bị loại bỏ, không đính vào /session-refresh", () => {
    const req = new NextRequest(new URL("/admissions/611", BASE));
    const res = proxy(req);
    const location = res.headers.get("location") ?? "";

    expect(location).toContain("/session-refresh");
    expect(location).not.toContain("evil.com");
  });
});

describe("proxy — các nhánh KHÔNG được nới lỏng", () => {
  it("token sai định dạng → vẫn redirect /login", () => {
    const res = proxy(requestWith("khong-phai-jwt"));

    expect(res.status).toBe(307);
    expect(res.headers.get("location") ?? "").toContain("/login");
  });

  it("token còn hạn → đi tiếp bình thường", () => {
    const res = proxy(requestWith(accessToken(600)));

    expect(res.status).toBe(200);
    expect(res.headers.get("location")).toBeNull();
  });

  // RBAC vẫn chạy trên token còn hạn: đây là gate UX, backend Casbin là gate
  // thật, nhưng nới nhánh hết-hạn không được phép làm hỏng nhánh này.
  it("officer vào route admin → vẫn bị đẩy khỏi trang admin", () => {
    const res = proxy(requestWith(accessToken(600, "officer"), "/admin/users"));

    expect(res.status).toBe(307);
    expect(res.headers.get("location") ?? "").not.toContain("/admin/users");
  });

  // Nhánh hết-hạn nằm TRƯỚC bước RBAC, nên nếu nó `next()` thì một token hết
  // hạn sẽ vào thẳng vỏ trang admin mà không qua kiểm quyền.
  it("token HẾT HẠN vào route admin → không được vào vỏ trang admin", () => {
    const res = proxy(requestWith(accessToken(-120, "officer"), "/admin/users"));

    expect(res.status).toBe(307);
    expect(res.headers.get("location") ?? "").not.toContain("/admin/users");
  });
});
