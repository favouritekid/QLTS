// frontend/playwright.link-safety.config.ts
/**
 * Cấu hình RIÊNG cho phép thử guard liên kết thông báo (lát B).
 *
 * 🔴 VÌ SAO KHÔNG DÙNG `playwright.config.ts`
 * Cấu hình chính khai `webServer: { command: "npm run dev", url:
 * "http://localhost:3000", reuseExistingServer: true }`. Chạy nó ở máy này sẽ
 * **tự khởi chạy dev server trên HOST và chiếm cổng 3000** — đúng thứ phải
 * tránh. Ở đây **KHÔNG khai `webServer`**, nên Playwright không bao giờ tự
 * dựng server; nó chỉ nối tới `PLAYWRIGHT_BASE_URL`, là một container Next.js
 * trong mạng docker riêng, không publish cổng nào ra host.
 *
 * Cấu hình chính cũng khai một project `setup` chạy `auth.setup.ts` (đăng nhập
 * bằng tài khoản thật vào backend thật). Ở đây KHÔNG dùng: phiên được giả bằng
 * cookie trong chính spec, và API do stub trả — không credential thật, không
 * CSDL thật.
 */
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./src/test/e2e",
  testMatch: /notification-link-safety\.spec\.ts/,

  // Tuần tự: mỗi ca tự dựng bẫy đếm riêng, chạy song song làm nhiễu phép đếm.
  fullyParallel: false,
  workers: 1,
  retries: 0,

  reporter: [["list"]],

  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://fe-test:3000",
    trace: "off",
    screenshot: "only-on-failure",
    video: "off",
    // Dev server của Next biên dịch theo yêu cầu ⇒ lượt đầu chậm.
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
  },

  timeout: 120_000,
  expect: { timeout: 30_000 },

  projects: [
    { name: "chromium-link-safety", use: { ...devices["Desktop Chrome"] } },
  ],

  // ⚠️ KHÔNG khai `webServer` — xem đầu tệp.
});
