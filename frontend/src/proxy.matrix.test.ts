/**
 * Bước 3 + Bước 5 — ma trận loại request, nắp chống lặp, shortcut, và handoff
 * pathname sang Server Component.
 *
 * Tách khỏi `proxy.test.ts` (vốn khoá nhánh "token hết hạn không tự kết luận
 * hết phiên") để mỗi tệp còn đọc được; cả hai chạy middleware THẬT với
 * `NextRequest`.
 */
import { describe, it, expect } from "vitest";
import { NextRequest } from "next/server";

import { proxy } from "./proxy";

const BASE = "https://qlts.tnpc.edu.vn";

function makeToken(payload: Record<string, unknown>): string {
  const b64 = (obj: unknown) =>
    Buffer.from(JSON.stringify(obj))
      .toString("base64")
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64(payload)}.sig`;
}

function accessToken(expiresInSeconds: number, extra: Record<string, unknown> = {}) {
  return makeToken({
    sub: "officer1",
    user_id: 25,
    role: "officer",
    type: "access",
    jti: "jti-goc",
    exp: Math.floor(Date.now() / 1000) + expiresInSeconds,
    ...extra,
  });
}

/** Request kèm header — dùng cho ma trận loại request. */
function requestWithHeaders(
  headers: Record<string, string>,
  token: string | undefined = accessToken(-120),
  path = "/admissions/611",
) {
  const req = new NextRequest(new URL(path, BASE), { headers });
  if (token) req.cookies.set("access_token", token);
  return req;
}

function locationOf(res: Response): string {
  return decodeURIComponent(res.headers.get("location") ?? "");
}

/**
 * ⚠️ PHẠM VI CỦA TỆP NÀY: nó kiểm **chính sách sau khi header đã tới proxy**.
 *
 * Nó KHÔNG chứng minh được header có tới nơi hay không — `NextRequest` ở đây do
 * test tự dựng nên header luôn nguyên vẹn, còn production thì Next gỡ các Flight
 * header trước khi gọi Proxy trừ khi `skipProxyUrlNormalize` được bật
 * (`proxy.config.contract.test.ts` khoá cờ đó, và smoke production là trọng tài
 * cuối). Hai lớp này bù cho nhau; thiếu một lớp là mù đúng chỗ vừa hỏng.
 */
describe("ma trận loại request khi cần cứu phiên", () => {
  it("full document → sang /session-refresh", async () => {
    const res = await proxy(requestWithHeaders({ "sec-fetch-dest": "document" }));

    expect(res.status).toBe(307);
    expect(locationOf(res)).toContain("/session-refresh");
  });

  it("RSC navigation thật (rsc:1, không prefetch) → sang /session-refresh", async () => {
    const res = await proxy(requestWithHeaders({ rsc: "1" }));

    expect(res.status).toBe(307);
    expect(locationOf(res)).toContain("/session-refresh");
  });

  it.each([["1"], ["2"]])(
    "prefetch (next-router-prefetch=%s) → 204, KHÔNG refresh",
    async (value) => {
      const res = await proxy(requestWithHeaders({ "next-router-prefetch": value }));

      expect(res.status).toBe(204);
      expect(res.headers.get("location")).toBeNull();
      const cacheControl = res.headers.get("cache-control") ?? "";
      expect(cacheControl).toContain("private");
      expect(cacheControl).toContain("no-store");
    },
  );

  it("segment prefetch → 204", async () => {
    const res = await proxy(
      requestWithHeaders({ "next-router-segment-prefetch": "/admissions" }),
    );

    expect(res.status).toBe(204);
  });

  /**
   * 🔴 Ca khoá THỨ TỰ vị từ.
   *
   * Một request prefetch mang ĐỒNG THỜI `rsc: 1` và `next-router-prefetch: 1`.
   * Nếu cài đặt kiểm `rsc` trước thì nó vẫn qua sạch mọi ca ở trên, mà mỗi lần
   * người dùng rê chuột qua một link là một redirect + một POST refresh.
   */
  it("rsc:1 VÀ prefetch:1 cùng lúc → vẫn phải 204 (prefetch thắng)", async () => {
    const res = await proxy(
      requestWithHeaders({ rsc: "1", "next-router-prefetch": "1" }),
    );

    expect(res.status).toBe(204);
    expect(res.headers.get("location")).toBeNull();
  });

  it("header thiếu/lạ → fail-safe như full document", async () => {
    const res = await proxy(requestWithHeaders({ "sec-fetch-dest": "empty" }));

    expect(res.status).toBe(307);
    expect(locationOf(res)).toContain("/session-refresh");
  });

  it("prefetch khi KHÔNG có access cookie → cũng 204", async () => {
    const res = await proxy(
      requestWithHeaders({ "next-router-prefetch": "1" }, undefined),
    );

    expect(res.status).toBe(204);
  });
});

/**
 * 🔴 Marker prefetch là thứ CLIENT tự gửi, nên nó chỉ được phép làm một việc:
 * đổi một lượt cứu phiên thành `204`. Nó KHÔNG bao giờ được biến thành
 * `NextResponse.next()` — nếu không, gắn thêm một header là vượt được auth.
 *
 * Nói cách khác: header giả chỉ có thể khiến chính request đó **không nhận được
 * gì**; nó không mở được cửa nào.
 */
describe("marker prefetch KHÔNG được dùng để vượt auth", () => {
  it.each([
    ["prefetch=1", { "next-router-prefetch": "1" }],
    ["prefetch=2", { "next-router-prefetch": "2" }],
    ["segment-prefetch", { "next-router-segment-prefetch": "/leads" }],
    ["prefetch + rsc", { rsc: "1", "next-router-prefetch": "1" }],
  ])("%s không có access token ⇒ KHÔNG trả nội dung protected", async (_l, headers) => {
    const res = await proxy(requestWithHeaders(headers, undefined, "/admissions/611"));

    // 204 = rỗng (đúng), 307 = đẩy đi cứu phiên (đúng). Điều DUY NHẤT bị cấm là
    // 200 — tức middleware cho request đi tiếp vào trang được bảo vệ.
    expect(res.status).not.toBe(200);
    expect([204, 307]).toContain(res.status);
  });

  /**
   * Biến thể transport: Next phục vụ payload RSC qua nhiều dạng đường dẫn
   * (`.rsc`, segment prefetch path). Chúng vẫn phải đi qua ranh giới auth —
   * advisory GHSA-267c-6grr-h53f là đúng lớp lỗi này.
   */
  it.each([
    ["đuôi .rsc", "/admissions/611.rsc"],
    ["segment path", "/admissions/611/__PAGE__.segment.rsc"],
    ["đuôi .rsc + prefetch marker", "/leads.rsc"],
  ])("%s không có access token ⇒ KHÔNG trả nội dung protected", async (_l, path) => {
    const res = await proxy(
      requestWithHeaders({ "next-router-prefetch": "1" }, undefined, path),
    );

    expect(res.status).not.toBe(200);
  });
});

describe("return-url: giữ query nghiệp vụ, gỡ _rsc", () => {
  it("giữ nguyên query nghiệp vụ qua vòng redirect", async () => {
    const req = new NextRequest(new URL("/admissions?tab=ho-so&page=3", BASE));
    req.cookies.set("access_token", accessToken(-120));
    const res = await proxy(req);

    const location = locationOf(res);
    expect(location).toContain("tab=ho-so");
    expect(location).toContain("page=3");
  });

  it.each([
    ["?_rsc=abc", "_rsc=abc"],
    ["?_rsc", "_rsc"],
    ["?a=1&_rsc&b=2", "_rsc"],
  ])("gỡ _rsc khỏi return-url (%s)", async (query, forbidden) => {
    const req = new NextRequest(new URL(`/admissions/611${query}`, BASE));
    req.cookies.set("access_token", accessToken(-120));
    const res = await proxy(req);

    expect(locationOf(res)).not.toContain(forbidden);
  });
});

describe("/session-refresh — nắp chống lặp và shortcut", () => {
  function refreshPage(query: string, token?: string) {
    const req = new NextRequest(new URL(`/session-refresh${query}`, BASE));
    if (token) req.cookies.set("access_token", token);
    return req;
  }

  it("chưa đi vòng nào → cho trang bootstrap render, no-store", async () => {
    const res = await proxy(refreshPage("?redirect=%2Fadmissions%2F611"));

    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control") ?? "").toContain("no-store");
  });

  it("đã đi 2 vòng → dừng hẳn, sang /login?reauth=true", async () => {
    const res = await proxy(refreshPage("?redirect=%2Fadmissions%2F611%3F_sr%3D2"));

    expect(res.status).toBe(307);
    const location = locationOf(res);
    expect(location).toContain("/login");
    expect(location).toContain("reauth=true");
    // Marker không được mang theo sang trang đăng nhập.
    expect(location).not.toContain("_sr");
  });

  it("nắp đứng TRƯỚC source=server_401 (nếu không, SSR 401 lặp mãi)", async () => {
    const res = await proxy(
      refreshPage("?redirect=%2Fadmissions%2F611%3F_sr%3D2&source=server_401"),
    );

    expect(res.status).toBe(307);
    expect(locationOf(res)).toContain("reauth=true");
  });

  it("source=server_401 → KHÔNG bao giờ shortcut, dù token còn hạn", async () => {
    const res = await proxy(
      refreshPage(
        "?redirect=%2Fadmissions%2F611&source=server_401&at=van-tay-cu",
        accessToken(600),
      ),
    );

    expect(res.status).toBe(200);
  });

  it("token đã đổi (at khác vân tay hiện tại) → quay lại target, _sr tăng", async () => {
    const res = await proxy(
      refreshPage("?redirect=%2Fadmissions%2F611&at=van-tay-cu", accessToken(600)),
    );

    expect(res.status).toBe(307);
    const location = locationOf(res);
    expect(location).toContain("/admissions/611");
    expect(location).toContain("_sr=1");
  });

  it("không có `at` → không shortcut, vào bootstrap", async () => {
    const res = await proxy(
      refreshPage("?redirect=%2Fadmissions%2F611", accessToken(600)),
    );

    expect(res.status).toBe(200);
  });

  it.each([
    ["token hết hạn", accessToken(-120)],
    ["token sai định dạng", "khong-phai-jwt"],
    ["thiếu jti", makeToken({ type: "access", exp: Math.floor(Date.now() / 1000) + 600 })],
    [
      "sai type",
      makeToken({
        type: "refresh",
        jti: "x",
        exp: Math.floor(Date.now() / 1000) + 600,
      }),
    ],
  ])("%s → không đủ điều kiện shortcut", async (_label, token) => {
    const res = await proxy(
      refreshPage("?redirect=%2Fadmissions%2F611&at=van-tay-cu", token),
    );

    expect(res.status).toBe(200);
  });

  it("target ngoại lai → không mang theo", async () => {
    const res = await proxy(
      refreshPage("?redirect=https%3A%2F%2Fevil.com%2Fx%3F_sr%3D2"),
    );

    expect(locationOf(res)).not.toContain("evil.com");
  });

  it.each([
    ["_sr trùng khoá", "%2Fadmissions%2F611%3F_sr%3D1%26_sr%3D2"],
    ["_sr không phải số", "%2Fadmissions%2F611%3F_sr%3Dabc"],
    ["_sr âm", "%2Fadmissions%2F611%3F_sr%3D-5"],
  ])("%s ⇒ coi như 0, vẫn vào bootstrap", async (_label, redirect) => {
    const res = await proxy(refreshPage(`?redirect=${redirect}`));

    expect(res.status).toBe(200);
  });
});

describe("handoff pathname sang Server Component", () => {
  /**
   * 🔴 Phải là REQUEST header được chuyển tiếp, không phải header của response:
   * `nextHeaders()` trong Server Component chỉ đọc được header của request.
   * Đặt nhầm lên response thì `server.ts` luôn thấy thiếu và im lặng đi đường
   * fallback — mất return-url mà không có dấu hiệu nào.
   *
   * Next mã hoá header chuyển tiếp thành `x-middleware-request-*` trên response
   * của middleware; đó là thứ quan sát được từ test.
   */
  it("đặt x-qlts-pathname vào REQUEST header khi cho đi tiếp", async () => {
    const req = new NextRequest(new URL("/admissions/611?tab=ho-so", BASE));
    req.cookies.set("access_token", accessToken(600));
    const res = await proxy(req);

    expect(res.headers.get("x-middleware-request-x-qlts-pathname")).toBe(
      "/admissions/611?tab=ho-so",
    );
  });

  it("header do CLIENT tự gửi bị GHI ĐÈ", async () => {
    const req = new NextRequest(new URL("/admissions/611", BASE), {
      headers: { "x-qlts-pathname": "//evil.com/x" },
    });
    req.cookies.set("access_token", accessToken(600));
    const res = await proxy(req);

    const forwarded = res.headers.get("x-middleware-request-x-qlts-pathname");
    expect(forwarded).toBe("/admissions/611");
    expect(forwarded).not.toContain("evil.com");
  });
});
