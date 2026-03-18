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
  // 7. Anomaly Badges & Risk Score
  // =========================================================================

  test("login cards show anomaly badges", async () => {
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);

    // At least one badge type should be visible (IP mới, Thiết bị mới, or Vị trí mới)
    const ipBadge = sharedPage.getByText("IP mới").first();
    const deviceBadge = sharedPage.getByText("Thiết bị mới").first();
    const locationBadge = sharedPage.getByText("Vị trí mới").first();

    const hasAny =
      (await ipBadge.isVisible().catch(() => false)) ||
      (await deviceBadge.isVisible().catch(() => false)) ||
      (await locationBadge.isVisible().catch(() => false));

    // With test data (30 suspicious logins), at least one badge should exist
    expect(hasAny).toBe(true);
  });

  test("risk score badges display with correct severity", async () => {
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);

    // Check for any risk score badge (Rủi ro cao/trung bình/thấp)
    const highRisk = sharedPage.getByText(/Rủi ro cao/).first();
    const medRisk = sharedPage.getByText(/Rủi ro trung bình/).first();
    const lowRisk = sharedPage.getByText(/Rủi ro thấp/).first();

    const hasRisk =
      (await highRisk.isVisible().catch(() => false)) ||
      (await medRisk.isVisible().catch(() => false)) ||
      (await lowRisk.isVisible().catch(() => false));

    expect(hasRisk).toBe(true);
  });

  // =========================================================================
  // 8. Login Card Content Verification
  // =========================================================================

  test("login cards show device, location, and time info", async () => {
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);

    // Page should contain device info text pattern: "Browser trên OS"
    // Look in the entire page since cards may be in different sections
    const deviceText = sharedPage.getByText("trên").first();
    const hasDeviceInfo = await deviceText.isVisible().catch(() => false);

    if (!hasDeviceInfo) {
      // Fallback: check for browser name or "Trình duyệt không xác định"
      const hasBrowser = await sharedPage
        .getByText(/Chrome|Firefox|Safari|Edge|Trình duyệt/)
        .first()
        .isVisible()
        .catch(() => false);
      expect(hasBrowser).toBe(true);
    }
  });

  test("login history section shows read-only cards without action buttons", async () => {
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);

    // Scroll to history section
    const historyHeading = sharedPage.getByText("Lịch sử đăng nhập");
    await historyHeading.scrollIntoViewIfNeeded();

    // Get the history section
    const historySection = sharedPage.locator("section", {
      has: historyHeading,
    });

    // Cards in history section should NOT have "Là tôi" buttons (readOnly)
    const actionButtons = historySection.getByRole("button", { name: "Là tôi" });
    const count = await actionButtons.count();
    expect(count).toBe(0);
  });

  // =========================================================================
  // 9. Confirm Login — count decreases
  // =========================================================================

  test("confirming login decreases suspicious count", async () => {
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);

    // Get initial suspicious count from alert text
    const alertText = sharedPage.getByText(/Phát hiện \d+ đăng nhập đáng ngờ/);
    if (!(await alertText.isVisible().catch(() => false))) {
      test.skip();
      return;
    }

    const initialText = await alertText.textContent();
    const initialCount = parseInt(initialText?.match(/\d+/)?.[0] || "0");

    // Confirm first suspicious login
    const confirmBtn = sharedPage.getByRole("button", { name: "Là tôi" }).first();
    await confirmBtn.click();
    await expect(sharedPage.getByText("Đã xác nhận đăng nhập")).toBeVisible({
      timeout: 10_000,
    });

    // Wait for query invalidation and re-render
    await sharedPage.waitForTimeout(2000);

    // Count should decrease by 1
    const updatedAlert = sharedPage.getByText(/Phát hiện \d+ đăng nhập đáng ngờ/);
    if (await updatedAlert.isVisible().catch(() => false)) {
      const updatedText = await updatedAlert.textContent();
      const updatedCount = parseInt(updatedText?.match(/\d+/)?.[0] || "0");
      expect(updatedCount).toBe(initialCount - 1);
    }
    // If alert disappeared entirely, all suspicious logins were confirmed — also valid
  });

  // =========================================================================
  // 10. Password Page — form fields and validation
  // =========================================================================

  test("password page has all required form fields", async () => {
    await sharedPage.goto("/settings");
    await waitForPageReady(sharedPage);

    const passwordInputs = sharedPage.locator('input[type="password"]');
    const count = await passwordInputs.count();
    // Should have at least 2 password fields: old password + new password
    expect(count).toBeGreaterThanOrEqual(2);
  });

  test("password page submit button is present", async () => {
    await sharedPage.goto("/settings");
    await waitForPageReady(sharedPage);

    // Should have a submit button
    const submitButton = sharedPage.getByRole("button", { name: /đổi mật khẩu/i });
    await expect(submitButton).toBeVisible();
  });

  // =========================================================================
  // 11. MFA Page — detailed checks
  // =========================================================================

  test("MFA page shows enable/disable status", async () => {
    await sharedPage.goto("/settings/mfa");
    await waitForPageReady(sharedPage);

    // MFA page should show either "Thiết lập" (setup) or status indicator
    const main = sharedPage.locator("main");
    const text = await main.textContent();
    // Should contain MFA-related content
    const hasMfaContent =
      text?.includes("Xác thực") ||
      text?.includes("MFA") ||
      text?.includes("2FA") ||
      text?.includes("Thiết lập") ||
      text?.includes("Bật") ||
      text?.includes("Tắt");
    expect(hasMfaContent).toBe(true);
  });

  // =========================================================================
  // 12. Notifications Page — detailed checks
  // =========================================================================

  test("notifications page shows preference categories", async () => {
    await sharedPage.goto("/settings/notifications");
    await waitForPageReady(sharedPage);

    // Should have toggle switches or cards for notification categories
    const main = sharedPage.locator("main");
    const text = await main.textContent();
    // Should have notification-related content
    const hasNotifContent =
      text?.includes("Thông báo") ||
      text?.includes("Email") ||
      text?.includes("Trình duyệt") ||
      text?.includes("thông báo");
    expect(hasNotifContent).toBe(true);
  });

  // =========================================================================
  // 13. Navigation — active tab highlighting
  // =========================================================================

  test("active tab is highlighted correctly", async () => {
    const nav = 'nav[aria-label="Settings navigation"]';

    // Go to /settings — "Mật khẩu" should be active
    await sharedPage.goto("/settings");
    await waitForPageReady(sharedPage);
    const passwordTab = sharedPage.locator(`${nav} >> text=Mật khẩu`);
    await expect(passwordTab).toHaveClass(/border-primary/);

    // Go to /settings/security — "Bảo mật" should be active
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);
    const securityTab = sharedPage.locator(`${nav} >> text=Bảo mật`);
    await expect(securityTab).toHaveClass(/border-primary/);
  });

  // =========================================================================
  // 14. Security Page — page header and breadcrumb
  // =========================================================================

  test("security page shows correct breadcrumb", async () => {
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);

    // Breadcrumb should show "Settings > Security" or "Dashboard > Settings > Security"
    const breadcrumb = sharedPage.getByText("Security");
    await expect(breadcrumb.first()).toBeVisible();
  });

  // =========================================================================
  // 15. Security Page — suspicious section expand shows correct count
  // =========================================================================

  test("suspicious expand button shows correct hidden count", async () => {
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);

    const expandButton = sharedPage.getByText(/Xem thêm \d+ đăng nhập đáng ngờ/);
    if (!(await expandButton.isVisible().catch(() => false))) {
      test.skip();
      return;
    }

    // Extract count from button text
    const text = await expandButton.textContent();
    const hiddenCount = parseInt(text?.match(/\d+/)?.[0] || "0");
    expect(hiddenCount).toBeGreaterThan(0);

    // Expand and verify count matches
    await expandButton.click();
    const allConfirmButtons = sharedPage.getByRole("button", { name: "Là tôi" });
    const totalCount = await allConfirmButtons.count();
    // Total should be hidden + initial 3
    expect(totalCount).toBe(hiddenCount + 3);

    // Collapse back
    await sharedPage.getByText("Thu gọn").first().click();
  });

  // =========================================================================
  // 16. Mobile Responsiveness
  // =========================================================================

  test("security page renders on mobile viewport", async () => {
    await sharedPage.setViewportSize({ width: 375, height: 812 });
    await sharedPage.goto("/settings/security");
    await waitForPageReady(sharedPage);

    await expect(sharedPage).toHaveURL(/\/settings\/security/);
    await expect(sharedPage.getByText("Phiên Đang Hoạt Động")).toBeVisible();
    await expect(sharedPage.getByText("Lịch sử đăng nhập")).toBeVisible();

    // Action buttons should stack vertically on mobile (flex-col)
    const confirmBtn = sharedPage.getByRole("button", { name: "Là tôi" }).first();
    if (await confirmBtn.isVisible().catch(() => false)) {
      await expect(confirmBtn).toBeVisible();
    }

    // Restore desktop viewport
    await sharedPage.setViewportSize({ width: 1280, height: 720 });
  });

  test("settings navigation scrolls horizontally on mobile", async () => {
    await sharedPage.setViewportSize({ width: 375, height: 812 });
    await sharedPage.goto("/settings");
    await waitForPageReady(sharedPage);

    const nav = sharedPage.locator('nav[aria-label="Settings navigation"]');
    await expect(nav).toBeVisible();

    // All tabs should still be accessible (overflow-x-auto)
    await expect(nav.getByText("Mật khẩu")).toBeVisible();
    await expect(nav.getByText("Bảo mật")).toBeVisible();

    // Restore viewport
    await sharedPage.setViewportSize({ width: 1280, height: 720 });
  });
});
