// src/test/e2e/notification-link-safety.spec.ts
/**
 * Phép thử TRÌNH DUYỆT THẬT cho guard liên kết thông báo.
 *
 * 🔴 VÌ SAO CẦN, KHI ĐÃ CÓ BA TỆP `*.safe-link.test.tsx`
 * Ba tệp ấy đều `vi.mock("next/link")` thành `<a>` thuần. Nghĩa là mọi khẳng
 * định "component render ra `href` gì" đang tựa trên một **stub**: chúng không
 * chứng minh `next/link` THẬT giữ nguyên giá trị, và chúng chạy trên URL parser
 * của jsdom chứ không phải của trình duyệt — mà chính parser mới là nơi `\` và
 * TAB/LF/CR đổi nghĩa. Bộ ca này đóng đúng khâu (d)→(e): "component render ra
 * gì" → "trình duyệt THẬT làm gì với giá trị đó".
 *
 * 🔒 FAIL-CLOSED: KHÔNG chỉ assert "không thấy href xấu".
 * Một ca chỉ nhìn thuộc tính `href` không loại trừ điều hướng bằng
 * `router.push`, `window.location`, hay một handler khác. Vì thế mỗi ca có
 * **bẫy đếm chủ động**:
 *   - `page.route` bắt mọi request tới host ngoài ⇒ assert **đúng 0**;
 *   - `page.on("framenavigated")` ghi mọi khung điều hướng (kể cả iframe);
 *   - `page.on("popup")` bắt tab/cửa sổ mới;
 *   - so `new URL(page.url()).origin` TRƯỚC và SAU khi bấm.
 *
 * Ba tải trọng, mỗi cái chứng minh một điều KHÁC nhau:
 *   1. `/leads?tab=a`        — ĐỐI CHỨNG DƯƠNG. Nếu nó cũng bị chặn thì bản vá
 *                              siết quá tay và bộ ca này phải đỏ.
 *   2. `/\evil.example`      — vector mà guard backend `_is_safe_relative_link`
 *                              CHO QUA (đo 22-09) ⇒ chứng minh lớp FE còn cần.
 *   3. `/..//evil.example`   — chạm CHẶN CUỐI (sau chuẩn hoá), không phải cổng
 *                              hình dạng đầu vào: chuỗi gốc bắt đầu `/` và
 *                              không phải `//` nên nó ĐI QUA `laDuongNoiBo`,
 *                              chỉ tụt thành `//…` sau `URL.pathname`. Đây là
 *                              ca DUY NHẤT chứng minh chặn cuối chịu lực trong
 *                              trình duyệt thật.
 *
 * Dữ liệu là GIẢ (stub API trong mạng docker riêng). Không CSDL thật, không
 * credential thật, không trỏ production.
 */
import { test, expect, type Page } from "@playwright/test";

/** Host ngoài dùng trong tải trọng — chỉ để đếm, không bao giờ được gọi tới. */
const HOST_NGOAI = "evil.example";

/** JWT KHÔNG ký — `proxy.ts` chỉ DECODE (`jwt-decode.ts` không verify). */
function taoAccessTokenGia(): string {
  const b64 = (o: unknown) =>
    Buffer.from(JSON.stringify(o))
      .toString("base64")
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  const now = Math.floor(Date.now() / 1000);
  const header = b64({ alg: "HS256", typ: "JWT" });
  const payload = b64({
    sub: "1",
    user_id: 1,
    type: "access",
    role: "admin",
    jti: "e2e-b-jti",
    iat: now,
    exp: now + 3600,
  });
  return `${header}.${payload}.e2e-b-khong-ky`;
}

interface Bay {
  /** Số request đã cố rời site (bị chặn ở `page.route`). */
  soRequestNgoai: number;
  /** Mọi URL mà một khung nào đó đã điều hướng tới. */
  dieuHuong: string[];
  /** Mọi popup/tab mới. */
  popup: string[];
}

/** Dựng bẫy đếm TRƯỚC khi mở trang. */
async function datBay(page: Page): Promise<Bay> {
  const bay: Bay = { soRequestNgoai: 0, dieuHuong: [], popup: [] };

  // Bắt MỌI request tới host ngoài, bất kể scheme/cổng/đường dẫn.
  await page.route(`**://*${HOST_NGOAI}/**`, (route) => {
    bay.soRequestNgoai += 1;
    return route.abort();
  });
  await page.route(`**://${HOST_NGOAI}/**`, (route) => {
    bay.soRequestNgoai += 1;
    return route.abort();
  });
  // Lưới cuối: bất kỳ URL nào chứa tên host, kể cả dạng không đoán trước.
  await page.route(
    (url) => url.hostname.includes(HOST_NGOAI),
    (route) => {
      bay.soRequestNgoai += 1;
      return route.abort();
    },
  );

  page.on("framenavigated", (frame) => bay.dieuHuong.push(frame.url()));
  page.on("popup", (p) => bay.popup.push(p.url()));

  return bay;
}

/** Mở trang thông báo với cookie phiên giả. */
async function moTrangThongBao(page: Page) {
  await page.context().addCookies([
    {
      name: "access_token",
      value: taoAccessTokenGia(),
      url: process.env.PLAYWRIGHT_BASE_URL || "http://fe-test:3000",
    },
  ]);
  await page.goto("/notifications", { waitUntil: "domcontentloaded" });
  // Ba thông báo do stub trả về đều phải CÓ MẶT — chặn liên kết KHÔNG được
  // nuốt mất nội dung.
  //
  // ⚠️ Dùng `state: "attached"` chứ không phải "visible": trang render HAI bộ
  // đánh dấu (bảng cho desktop, thẻ cho mobile) và một bộ luôn bị ẩn bằng CSS.
  // Bất biến cần canh là **giá trị `href` đi vào DOM**, không phải bộ nào đang
  // hiển thị; thao tác bấm bên dưới mới lọc `:visible`.
  for (const tieuDe of ["HOP LE", "CHAN BACKSLASH", "CHAN DOTSEG"]) {
    await page.waitForSelector(`text=${tieuDe}`, {
      state: "attached",
      timeout: 60_000,
    });
  }
}

test.describe("Liên kết thông báo — Chromium thật, next/link thật", () => {
  test("ĐỐI CHỨNG DƯƠNG: `/leads?tab=a` điều hướng nội bộ đúng đích", async ({ page }) => {
    const bay = await datBay(page);
    await moTrangThongBao(page);

    const originTruoc = new URL(page.url()).origin;

    // Bấm vào chính thẻ neo do `next/link` THẬT render.
    // Thẻ neo PHẢI có mặt trong DOM (không phụ thuộc bộ markup nào đang hiện).
    await expect(page.locator('a[href="/leads?tab=a"]')).not.toHaveCount(0);
    // Bấm vào bản ĐANG HIỂN THỊ — đúng thứ người dùng chạm tới.
    const neo = page.locator('a[href="/leads?tab=a"]:visible').first();
    await neo.click();
    await page.waitForURL(/\/leads/, { timeout: 30_000 });

    const sau = new URL(page.url());
    expect(sau.origin).toBe(originTruoc);
    expect(sau.pathname).toBe("/leads");
    expect(sau.search).toBe("?tab=a");
    expect(bay.soRequestNgoai).toBe(0);
    expect(bay.popup).toHaveLength(0);
    for (const u of bay.dieuHuong) {
      if (u && u !== "about:blank") expect(new URL(u).origin).toBe(originTruoc);
    }
  });

  for (const ca of [
    { ten: "backslash `/\\evil.example`", tieuDe: "CHAN BACKSLASH" },
    { ten: "dot-segment `/..//evil.example`", tieuDe: "CHAN DOTSEG" },
  ]) {
    test(`CHẶN ${ca.ten}: không điều hướng, 0 request rời site`, async ({ page }) => {
      const bay = await datBay(page);
      await moTrangThongBao(page);

      const originTruoc = new URL(page.url()).origin;
      const urlTruoc = page.url();

      // 1) Không thẻ neo nào mang host ngoài (điều kiện CẦN, CHƯA ĐỦ).
      //
      // ⚠️ `expect.soft` CÓ CHỦ ĐÍCH: nếu dùng assert cứng, một bản vá hỏng sẽ
      // làm ca đỏ NGAY Ở ĐÂY và các khẳng định về ĐIỀU HƯỚNG bên dưới không
      // bao giờ được chạy — tức phần fail-closed quan trọng nhất không được
      // đo. Soft để ca vẫn đi tiếp tới phép bấm và bẫy đếm.
      const neoXau = page.locator(`a[href*="${HOST_NGOAI}"]`);
      await expect.soft(neoXau).toHaveCount(0);

      // 2) Bấm vào chính hàng chứa thông báo đó — đi qua đúng sink, kể cả khi
      //    guard đã hạ `href` xuống "#" hay bỏ hẳn thẻ neo.
      const hang = page.locator(`:text-is("${ca.tieuDe}"):visible`).first();
      await hang.click({ force: true });
      // Cho trình duyệt đủ thời gian để một điều hướng (nếu có) kịp xảy ra.
      await page.waitForTimeout(1500);

      // 3) Bằng chứng FAIL-CLOSED: không rời site, không request ngoài.
      const sau = new URL(page.url());
      expect(sau.origin).toBe(originTruoc);
      expect(sau.hostname).not.toContain(HOST_NGOAI);
      expect(
        bay.soRequestNgoai,
        `số request rời site (phải 0), thực tế ${bay.soRequestNgoai}`,
      ).toBe(0);
      expect(bay.popup, `popup mở ra: ${JSON.stringify(bay.popup)}`).toHaveLength(0);
      const ngoai = bay.dieuHuong.filter(
        (u) => u && u !== "about:blank" && new URL(u).origin !== originTruoc,
      );
      expect(ngoai, `khung điều hướng RỜI origin: ${JSON.stringify(ngoai)}`).toHaveLength(0);
      // Origin không đổi; đường dẫn cũng không được nhảy sang nơi khác.
      expect(new URL(urlTruoc).pathname).toBe("/notifications");
      expect(sau.pathname).toBe("/notifications");
    });
  }
});
