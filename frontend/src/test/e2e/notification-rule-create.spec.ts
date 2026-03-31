/**
 * E2E: Notification Rule Create Flow
 *
 * Tests the full-page notification rule editor at /admin/notification-rules/new.
 * Uses API-based login for reliability in container environments.
 */
import { test, expect, type Page } from "@playwright/test";
import * as OTPAuth from "otpauth";

const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "@Abc12345!";
const TOTP_SECRET = process.env.E2E_ADMIN_TOTP_SECRET || "";
const API_URL =
  process.env.E2E_API_URL ||
  process.env.BACKEND_URL ||
  "http://backend:8000";
const FRONTEND_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000";
const AUTH_STORAGE_KEY = "auth-storage";
const AUTH_STORAGE_VERSION = 1;

function generateTOTP(secret: string): string {
  const totp = new OTPAuth.TOTP({
    secret: OTPAuth.Secret.fromBase32(secret),
    digits: 6,
    period: 30,
    algorithm: "SHA1",
  });
  return totp.generate();
}

async function extractAndAddCookies(
  page: Page,
  response: { headersArray(): Array<{ name: string; value: string }> },
): Promise<string> {
  const apiHost = new URL(API_URL).hostname;
  const frontendHost = new URL(FRONTEND_URL).hostname;
  let csrf = "";
  for (const header of response.headersArray()) {
    if (header.name.toLowerCase() !== "set-cookie") continue;
    const match = header.value.match(/^([^=]+)=([^;]*)/);
    if (!match) continue;
    const pathMatch = header.value.match(/path=([^;]*)/i);
    const cookie = {
      name: match[1].trim(),
      value: match[2],
      path: pathMatch ? pathMatch[1].trim() : "/",
      httpOnly: /httponly/i.test(header.value),
      secure: /secure/i.test(header.value),
    };
    await page.context().addCookies([{ ...cookie, domain: apiHost }]);
    if (frontendHost !== apiHost) {
      await page.context().addCookies([{ ...cookie, domain: frontendHost }]);
    }
    if (match[1].trim() === "csrf_token") csrf = match[2];
  }
  return csrf;
}

async function loginAndBootstrap(page: Page): Promise<void> {
  await page.context().clearCookies();

  let authUser: Record<string, unknown> | undefined;
  let authResp: Awaited<ReturnType<typeof page.request.post>> | undefined;

  for (let attempt = 0; attempt < 3; attempt++) {
    const loginResp = await page.request.post(`${API_URL}/api/auth/login`, {
      form: { username: ADMIN_USERNAME, password: ADMIN_PASSWORD },
    });

    if (loginResp.status() === 429) {
      await page.waitForTimeout(65_000);
      continue;
    }

    expect(loginResp.ok()).toBeTruthy();
    const loginBody = await loginResp.json();
    authResp = loginResp;
    authUser = loginBody.user;

    if (loginBody.mfa_required) {
      if (!TOTP_SECRET) throw new Error("MFA required but no TOTP secret");
      const mfaResp = await page.request.post(`${API_URL}/api/auth/verify-mfa`, {
        data: { mfa_token: loginBody.mfa_token, code: generateTOTP(TOTP_SECRET) },
      });
      if (!mfaResp.ok()) { await page.waitForTimeout(31_000); continue; }
      authResp = mfaResp;
      authUser = (await mfaResp.json()).user;
    }
    break;
  }

  if (!authUser || !authResp) throw new Error("Unable to login after 3 attempts");

  await extractAndAddCookies(page, authResp);

  await page.addInitScript(
    ({ key, value }) => window.localStorage.setItem(key, value),
    {
      key: AUTH_STORAGE_KEY,
      value: JSON.stringify({
        state: { user: authUser, isAuthenticated: true },
        version: AUTH_STORAGE_VERSION,
      }),
    },
  );

  await page.goto(`${FRONTEND_URL}/admin/notification-rules/new`);
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 });
  await page.waitForLoadState("domcontentloaded");
}

test.describe("Notification Rule Create Flow", () => {
  test.describe.configure({ timeout: 120_000 });

  test.beforeEach(async ({ page }) => {
    await loginAndBootstrap(page);
  });

  test("page loads with step 1 and quick templates", async ({ page }) => {
    await expect(page.getByText("Sự kiện & Điều kiện")).toBeVisible();
    await expect(page.getByText("Soạn nội dung")).toBeVisible();
    await expect(page.getByText("Người nhận & Kênh gửi")).toBeVisible();
    await expect(page.getByText("Kiểm tra & Lưu")).toBeVisible();
    await expect(page.getByText("Cấu hình nhanh")).toBeVisible();
    await expect(page.getByText("Manager tạo lead → Gửi cho Officers")).toBeVisible();
  });

  test("quick template fills form and navigates to step 2", async ({ page }) => {
    // Use role selector to target the quick-template button (not the radio label)
    await page.getByRole("button", { name: /Lead được phân công/ }).click();
    await expect(page.getByText("Bước 2: Nội dung mặc định")).toBeVisible();
    const titleInput = page.locator("#title_template");
    await expect(titleInput).toHaveValue(/Lead được phân công/);
  });

  test("Next button blocks when step 1 is empty", async ({ page }) => {
    // Button is disabled when no event selected — verify it stays disabled
    const nextBtn = page.getByRole("button", { name: "Tiếp theo" });
    await expect(nextBtn).toBeDisabled();
  });

  test("can navigate step 2 → 3 → 4 via quick template", async ({ page }) => {
    await page.getByRole("button", { name: /Lead được phân công/ }).click();
    await page.getByRole("button", { name: "Tiếp theo" }).click();
    await expect(page.getByText("Thêm nhóm nhân viên")).toBeVisible({ timeout: 5000 });
    await page.getByRole("button", { name: "Tiếp theo" }).click();
    await expect(page.getByText("Tóm tắt quy tắc:")).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("Kích hoạt ngay")).toBeVisible();
    await expect(page.getByRole("button", { name: "Tạo quy tắc" })).toBeVisible();
  });
});
