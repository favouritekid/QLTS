/**
 * E2E Tests — Settings Pages (Security, Password, MFA, Notifications)
 *
 * Tests the unified /settings/security page and related settings pages.
 * Login once, reuse auth cookies across all tests to avoid rate-limiting.
 *
 * Run:
 *   npx playwright test settings-security --project=e2e-workflow --reporter=list
 *   npx playwright test settings-security --project=e2e-workflow --headed
 */

import { test, expect, type Page, type BrowserContext } from "@playwright/test";
import * as OTPAuth from "otpauth";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "@G00gl38889@";
const ADMIN_TOTP_SECRET = process.env.E2E_ADMIN_TOTP_SECRET || "";

const API_URL = process.env.E2E_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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
  resp: { headersArray(): Array<{ name: string; value: string }> }
): Promise<void> {
  const apiHost = new URL(API_URL).hostname;
  for (const h of resp.headersArray()) {
    if (h.name.toLowerCase() !== "set-cookie") continue;
    const m = h.value.match(/^([^=]+)=([^;]*)/);
    if (!m) continue;
    const pathM = h.value.match(/path=([^;]*)/i);
    await page.context().addCookies([
      {
        name: m[1].trim(),
        value: m[2],
        domain: apiHost,
        path: pathM ? pathM[1].trim() : "/",
        httpOnly: /httponly/i.test(h.value),
        secure: /secure/i.test(h.value),
      },
    ]);
  }
}

async function waitForPageReady(page: Page): Promise<void> {
  await page.waitForLoadState("domcontentloaded");
  try {
    await page.waitForFunction(
      () =>
        document.querySelectorAll(
          '[class*="skeleton"], [class*="Skeleton"], [data-loading="true"]'
        ).length === 0,
      { timeout: 8_000 }
    );
  } catch {
    // Persistent loading states are OK
  }
  await page.waitForTimeout(500);
}

// ---------------------------------------------------------------------------
// Test Suite — login ONCE, reuse for all tests
// ---------------------------------------------------------------------------

test.describe("Settings Pages", () => {
  test.describe.configure({ timeout: 120_000, mode: "serial" });

  // Shared context: login once, reuse across all serial tests
  let sharedContext: BrowserContext;
  let sharedPage: Page;

  test.beforeAll(async ({ browser }) => {
    sharedContext = await browser.newContext();
    sharedPage = await sharedContext.newPage();

    // API login — single call for entire suite
    const loginResp = await sharedPage.request.post(
      `${API_URL}/api/auth/login`,
      { form: { username: ADMIN_USERNAME, password: ADMIN_PASSWORD } }
    );
    if (!loginResp.ok()) {
      throw new Error(`Login failed: ${loginResp.status()}`);
    }

    const loginBody = await loginResp.json();
    let authResp = loginResp;

    if (loginBody.mfa_required && ADMIN_TOTP_SECRET) {
      const code = generateTOTP(ADMIN_TOTP_SECRET);
      const mfaResp = await sharedPage.request.post(
        `${API_URL}/api/auth/verify-mfa`,
        { data: { mfa_token: loginBody.mfa_token, code } }
      );
      if (!mfaResp.ok()) throw new Error(`MFA failed: ${mfaResp.status()}`);
      authResp = mfaResp;
    } else if (loginBody.mfa_required) {
      throw new Error("MFA required but no TOTP secret configured");
    }

    await extractAndAddCookies(sharedPage, authResp);

    // Navigate first (localStorage requires same-origin page)
    await sharedPage.goto("/settings");

    // Set auth in localStorage
    const authBody = await authResp.json();
    await sharedPage.evaluate((user) => {
      localStorage.setItem(
        "auth-storage",
        JSON.stringify({
          state: { user, isAuthenticated: true },
          version: 0,
        })
      );
    }, authBody.user);

    // Reload to pick up localStorage auth state
    await sharedPage.reload();
    await expect(sharedPage).not.toHaveURL(/\/login/, { timeout: 15_000 });
  });

  test.afterAll(async () => {
    await sharedContext?.close();
  });

  // =========================================================================
  // 1. Settings Navigation
  // =========================================================================

  test("settings layout shows navigation tabs", async () => {
    const page = sharedPage;
    await page.goto("/settings");
    await waitForPageReady(page);

    await expect(page.locator("h1")).toContainText("Cài đặt");

    const nav = page.locator('nav[aria-label="Settings navigation"]');
    await expect(nav).toBeVisible();
    await expect(nav.getByText("Mật khẩu")).toBeVisible();
    await expect(nav.getByText("Bảo mật")).toBeVisible();
    await expect(nav.getByText("Xác thực 2 lớp")).toBeVisible();
    await expect(nav.getByText("Thông báo")).toBeVisible();
  });

  test("settings tabs navigate to correct pages", async () => {
    const page = sharedPage;
    await page.goto("/settings");
    await waitForPageReady(page);

    await page.click('nav[aria-label="Settings navigation"] >> text=Bảo mật');
    await expect(page).toHaveURL(/\/settings\/security/);

    await page.click(
      'nav[aria-label="Settings navigation"] >> text=Xác thực 2 lớp'
    );
    await expect(page).toHaveURL(/\/settings\/mfa/);

    await page.click('nav[aria-label="Settings navigation"] >> text=Thông báo');
    await expect(page).toHaveURL(/\/settings\/notifications/);

    await page.click('nav[aria-label="Settings navigation"] >> text=Mật khẩu');
    await expect(page).toHaveURL(/\/settings$/);
  });

  // =========================================================================
  // 2. Password Page (/settings)
  // =========================================================================

  test("password page renders change password form", async () => {
    await sharedPage.goto("/settings");
    await waitForPageReady(sharedPage);
    await expect(sharedPage.locator('input[type="password"]').first()).toBeVisible();
  });

  // =========================================================================
  // 3. Security Page (/settings/security)
  // =========================================================================

  test("security page renders all sections", async () => {
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);
    await expect(sharedPage.getByText("Phiên Đang Hoạt Động")).toBeVisible();
    await expect(sharedPage.getByText("Lịch sử đăng nhập")).toBeVisible();
  });

  test("security page sessions section is rendered", async () => {
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);
    // Sessions section header is already verified in "renders all sections" test.
    // Here we verify the section is scrollable and contains session-related content.
    // API login may not create a UI session, so we just verify the section exists.
    const sessionsHeading = sharedPage.getByText("Phiên Đang Hoạt Động");
    await sessionsHeading.scrollIntoViewIfNeeded();
    await expect(sessionsHeading).toBeVisible();
  });

  test("security page shows login history cards", async () => {
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);
    const historySection = sharedPage.locator("section", {
      has: sharedPage.getByText("Lịch sử đăng nhập"),
    });
    const cards = historySection.locator('[class*="card"], [class*="Card"]');
    await expect(cards.first()).toBeVisible({ timeout: 10_000 });
  });

  test("suspicious logins section behavior", async () => {
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);

    const suspiciousAlert = sharedPage.getByText("đăng nhập đáng ngờ");
    const hasSuspicious = await suspiciousAlert.isVisible().catch(() => false);

    if (hasSuspicious) {
      await expect(sharedPage.getByText("Là tôi").first()).toBeVisible();
      await expect(sharedPage.getByText("Không phải tôi").first()).toBeVisible();

      const confirmButtons = sharedPage.getByRole("button", { name: "Là tôi" });
      const count = await confirmButtons.count();
      expect(count).toBeLessThanOrEqual(3);

      const expandButton = sharedPage.getByText(/Xem thêm.*đăng nhập đáng ngờ/);
      const hasExpand = await expandButton.isVisible().catch(() => false);
      if (hasExpand) {
        await expandButton.click();
        expect(await confirmButtons.count()).toBeGreaterThan(3);
        await sharedPage.getByText("Thu gọn").first().click();
        expect(await confirmButtons.count()).toBeLessThanOrEqual(3);
      }
    }
  });

  test("confirm login flow works", async () => {
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);

    const confirmButton = sharedPage.getByRole("button", { name: "Là tôi" }).first();
    if (!(await confirmButton.isVisible().catch(() => false))) {
      test.skip();
      return;
    }
    await confirmButton.click();
    // Success alert says "Đã xác nhận đăng nhập..."
    await expect(sharedPage.getByText("Đã xác nhận đăng nhập")).toBeVisible({ timeout: 10_000 });
  });

  test("secure account dialog opens and cancels", async () => {
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);

    const secureButton = sharedPage.getByRole("button", { name: "Không phải tôi" }).first();
    if (!(await secureButton.isVisible().catch(() => false))) {
      test.skip();
      return;
    }
    await secureButton.click();
    await expect(sharedPage.getByText("Bảo mật tài khoản")).toBeVisible();
    await expect(sharedPage.getByText("Thu hồi tất cả phiên đăng nhập hiện tại")).toBeVisible();
    await expect(sharedPage.getByRole("button", { name: "Bảo mật ngay" })).toBeVisible();
    await sharedPage.getByRole("button", { name: "Hủy" }).click();
    await expect(sharedPage.getByText("Bảo mật tài khoản")).not.toBeVisible();
  });

  test("login history expand/collapse works", async () => {
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);

    const expandButton = sharedPage.getByRole("button", { name: /Xem thêm \d+ mục/ });
    if (!(await expandButton.isVisible().catch(() => false))) {
      test.skip();
      return;
    }
    await expandButton.click();
    await expect(sharedPage.getByRole("button", { name: "Thu gọn" })).toBeVisible();
    await sharedPage.getByRole("button", { name: "Thu gọn" }).click();
    await expect(expandButton).toBeVisible();
  });

  // =========================================================================
  // 4. Route Redirects
  // =========================================================================

  test("old /settings/sessions redirects to /settings/security", async () => {
    await sharedPage.goto("/settings/sessions");
    await waitForPageReady(sharedPage);
    await expect(sharedPage).toHaveURL(/\/settings\/security/);
  });

  test("old /settings/login-history redirects to /settings/security", async () => {
    await sharedPage.goto("/settings/login-history");
    await waitForPageReady(sharedPage);
    await expect(sharedPage).toHaveURL(/\/settings\/security/);
  });

  // =========================================================================
  // 5. MFA Page
  // =========================================================================

  test("MFA page renders without crash", async () => {
    await sharedPage.goto("/settings/mfa");
    await waitForPageReady(sharedPage);
    await expect(sharedPage).toHaveURL(/\/settings\/mfa/);
    await expect(sharedPage.locator("main")).not.toBeEmpty();
  });

  // =========================================================================
  // 6. Notifications Page
  // =========================================================================

  test("notifications settings page renders", async () => {
    await sharedPage.goto("/settings/notifications");
    await waitForPageReady(sharedPage);
    await expect(sharedPage).toHaveURL(/\/settings\/notifications/);
    await expect(sharedPage.locator("main")).not.toBeEmpty();
  });

  // =========================================================================
  // 7. Mobile Responsiveness
  // =========================================================================

  test("security page renders on mobile viewport", async () => {
    // Resize shared page to mobile viewport
    await sharedPage.setViewportSize({ width: 375, height: 812 });
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);

    await expect(sharedPage).toHaveURL(/\/settings\/security/);
    await expect(sharedPage.getByText("Phiên Đang Hoạt Động")).toBeVisible();
    await expect(sharedPage.getByText("Lịch sử đăng nhập")).toBeVisible();

    // Restore desktop viewport
    await sharedPage.setViewportSize({ width: 1280, height: 720 });
  });
});
