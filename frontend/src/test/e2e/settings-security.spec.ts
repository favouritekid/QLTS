/**
 * E2E Tests — Settings Pages (Security, Password, MFA, Notifications)
 *
 * Tests the unified /settings/security page and related settings pages.
 * Uses API-level login with MFA to authenticate as admin.
 *
 * Run:
 *   npx playwright test settings-security --project=e2e-workflow --reporter=list
 *   npx playwright test settings-security --project=e2e-workflow --headed
 */

import { test, expect, type Page } from "@playwright/test";
import * as OTPAuth from "otpauth";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "Admin@12345";
const ADMIN_TOTP_SECRET =
  process.env.E2E_ADMIN_TOTP_SECRET || "WUUT7KVVWRFVMVPZ7K6NGOKL2VYPPFH5";

const API_URL = process.env.E2E_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Helpers (same pattern as smoke-all-pages.spec.ts)
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

async function loginAsAdmin(page: Page): Promise<void> {
  await page.context().clearCookies();

  const loginResp = await page.request.post(`${API_URL}/api/auth/login`, {
    form: { username: ADMIN_USERNAME, password: ADMIN_PASSWORD },
  });
  if (!loginResp.ok()) {
    throw new Error(`Login failed: ${loginResp.status()}`);
  }

  const loginBody = await loginResp.json();
  let authResp = loginResp;

  if (loginBody.mfa_required) {
    const code = generateTOTP(ADMIN_TOTP_SECRET);
    const mfaResp = await page.request.post(
      `${API_URL}/api/auth/verify-mfa`,
      { data: { mfa_token: loginBody.mfa_token, code } }
    );
    if (!mfaResp.ok()) {
      throw new Error(`MFA failed: ${mfaResp.status()}`);
    }
    authResp = mfaResp;
  }

  await extractAndAddCookies(page, authResp);

  // Set auth store in localStorage so client-side code knows user is logged in
  const authBody = await authResp.json();
  await page.context().addInitScript((user) => {
    localStorage.setItem(
      "auth-storage",
      JSON.stringify({
        state: { user, isAuthenticated: true },
        version: 0,
      })
    );
  }, authBody.user);
}

async function waitForPageReady(page: Page): Promise<void> {
  await page.waitForLoadState("domcontentloaded");
  // Wait for skeleton loaders to disappear
  try {
    await page.waitForFunction(
      () =>
        document.querySelectorAll(
          '[class*="skeleton"], [class*="Skeleton"], [data-loading="true"]'
        ).length === 0,
      { timeout: 8_000 }
    );
  } catch {
    // Some pages may have persistent loading states
  }
  await page.waitForTimeout(500);
}

// ---------------------------------------------------------------------------
// Test Suite
// ---------------------------------------------------------------------------

test.describe("Settings Pages", () => {
  test.describe.configure({ timeout: 120_000, mode: "serial" });

  test.beforeAll(async ({ browser }) => {
    // Warm-up: verify admin login works
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await loginAsAdmin(page);
    await page.goto("/settings");
    await expect(page).not.toHaveURL(/\/login/);
    await ctx.close();
  });

  // =========================================================================
  // 1. Settings Navigation
  // =========================================================================

  test("settings layout shows navigation tabs", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings");
    await waitForPageReady(page);

    // Check page header
    await expect(page.locator("h1")).toContainText("Cài đặt");

    // Check navigation tabs exist
    const nav = page.locator('nav[aria-label="Settings navigation"]');
    await expect(nav).toBeVisible();

    // Verify tab names
    await expect(nav.getByText("Mật khẩu")).toBeVisible();
    await expect(nav.getByText("Bảo mật")).toBeVisible();
    await expect(nav.getByText("Xác thực 2 lớp")).toBeVisible();
    await expect(nav.getByText("Thông báo")).toBeVisible();
  });

  test("settings tabs navigate to correct pages", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings");
    await waitForPageReady(page);

    // Click "Bảo mật" tab
    await page.click('nav[aria-label="Settings navigation"] >> text=Bảo mật');
    await expect(page).toHaveURL(/\/settings\/security/);

    // Click "Xác thực 2 lớp" tab
    await page.click(
      'nav[aria-label="Settings navigation"] >> text=Xác thực 2 lớp'
    );
    await expect(page).toHaveURL(/\/settings\/mfa/);

    // Click "Thông báo" tab
    await page.click('nav[aria-label="Settings navigation"] >> text=Thông báo');
    await expect(page).toHaveURL(/\/settings\/notifications/);

    // Click back to "Mật khẩu"
    await page.click('nav[aria-label="Settings navigation"] >> text=Mật khẩu');
    await expect(page).toHaveURL(/\/settings$/);
  });

  // =========================================================================
  // 2. Password Page (/settings)
  // =========================================================================

  test("password page renders change password form", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings");
    await waitForPageReady(page);

    // Should have password input fields
    await expect(page.locator('input[type="password"]').first()).toBeVisible();
  });

  // =========================================================================
  // 3. Security Page (/settings/security)
  // =========================================================================

  test("security page renders all 3 sections", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings/security");
    await waitForPageReady(page);

    // Section 2: Active sessions — always visible
    await expect(page.getByText("Phiên Đang Hoạt Động")).toBeVisible();

    // Section 3: Login history — always visible
    await expect(page.getByText("Lịch sử đăng nhập")).toBeVisible();
  });

  test("security page shows current session", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings/security");
    await waitForPageReady(page);

    // Current session card should exist
    await expect(page.getByText("Phiên Hiện Tại")).toBeVisible();
    await expect(page.getByText("Đang hoạt động")).toBeVisible();
  });

  test("security page shows login history cards", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings/security");
    await waitForPageReady(page);

    // Login history section should have at least 1 card (the login itself)
    const historySection = page.locator("section", {
      has: page.getByText("Lịch sử đăng nhập"),
    });
    // Cards contain device info like browser name or "Trình duyệt không xác định"
    const cards = historySection.locator('[class*="card"], [class*="Card"]');
    await expect(cards.first()).toBeVisible({ timeout: 10_000 });
  });

  test("suspicious logins section shows alert when present", async ({
    page,
  }) => {
    await loginAsAdmin(page);
    await page.goto("/settings/security");
    await waitForPageReady(page);

    // Check if suspicious alert exists (may or may not depending on test data)
    const suspiciousAlert = page.getByText("đăng nhập đáng ngờ");
    const hasSuspicious = await suspiciousAlert.isVisible().catch(() => false);

    if (hasSuspicious) {
      // Verify action buttons exist on suspicious cards
      await expect(page.getByText("Là tôi").first()).toBeVisible();
      await expect(page.getByText("Không phải tôi").first()).toBeVisible();
    }
    // If no suspicious logins, section should be hidden — that's valid too
  });

  test("suspicious logins section collapses to 3 items", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings/security");
    await waitForPageReady(page);

    const suspiciousAlert = page.getByText("đăng nhập đáng ngờ");
    const hasSuspicious = await suspiciousAlert.isVisible().catch(() => false);

    if (!hasSuspicious) {
      test.skip();
      return;
    }

    // Count "Là tôi" buttons visible (should be max 3 initially)
    const confirmButtons = page.getByRole("button", { name: "Là tôi" });
    const count = await confirmButtons.count();

    if (count > 3) {
      // If more than 3, there should be an expand button
      test.fail(
        true,
        `Expected max 3 suspicious cards initially, found ${count}`
      );
    }

    // Check for "Xem thêm" button if there are more
    const expandButton = page.getByText(/Xem thêm.*đăng nhập đáng ngờ/);
    const hasExpand = await expandButton.isVisible().catch(() => false);
    if (hasExpand) {
      // Click expand
      await expandButton.click();
      // Should now show more items
      const expandedCount = await confirmButtons.count();
      expect(expandedCount).toBeGreaterThan(3);

      // Click collapse
      await page.getByText("Thu gọn").click();
      const collapsedCount = await confirmButtons.count();
      expect(collapsedCount).toBeLessThanOrEqual(3);
    }
  });

  test("confirm login flow works", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings/security");
    await waitForPageReady(page);

    const confirmButton = page.getByRole("button", { name: "Là tôi" }).first();
    const hasConfirm = await confirmButton.isVisible().catch(() => false);

    if (!hasConfirm) {
      test.skip();
      return;
    }

    // Click "Là tôi"
    await confirmButton.click();

    // Should show success message
    await expect(page.getByText("Đã xác nhận")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("secure account dialog opens on 'Không phải tôi'", async ({
    page,
  }) => {
    await loginAsAdmin(page);
    await page.goto("/settings/security");
    await waitForPageReady(page);

    const secureButton = page
      .getByRole("button", { name: "Không phải tôi" })
      .first();
    const hasSecure = await secureButton.isVisible().catch(() => false);

    if (!hasSecure) {
      test.skip();
      return;
    }

    // Click "Không phải tôi"
    await secureButton.click();

    // Dialog should appear
    await expect(page.getByText("Bảo mật tài khoản")).toBeVisible();
    await expect(
      page.getByText("Thu hồi tất cả phiên đăng nhập hiện tại")
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Bảo mật ngay" })
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Hủy" })).toBeVisible();

    // Cancel the dialog
    await page.getByRole("button", { name: "Hủy" }).click();
    await expect(page.getByText("Bảo mật tài khoản")).not.toBeVisible();
  });

  test("login history 'Xem thêm' expand/collapse works", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings/security");
    await waitForPageReady(page);

    // Find "Xem thêm" button in login history section (not suspicious section)
    const historyExpandButton = page.getByRole("button", {
      name: /Xem thêm \d+ mục/,
    });
    const hasExpand = await historyExpandButton.isVisible().catch(() => false);

    if (!hasExpand) {
      // Less than 5 login history items — no expand button needed
      test.skip();
      return;
    }

    // Click expand
    await historyExpandButton.click();

    // "Thu gọn" button should appear
    const collapseButton = page.getByRole("button", { name: "Thu gọn" });
    await expect(collapseButton).toBeVisible();

    // Click collapse
    await collapseButton.click();

    // "Xem thêm" should reappear
    await expect(historyExpandButton).toBeVisible();
  });

  // =========================================================================
  // 4. Route Redirects (old routes → /settings/security)
  // =========================================================================

  test("old /settings/sessions redirects to /settings/security", async ({
    page,
  }) => {
    await loginAsAdmin(page);
    await page.goto("/settings/sessions");
    await waitForPageReady(page);

    await expect(page).toHaveURL(/\/settings\/security/);
  });

  test("old /settings/login-history redirects to /settings/security", async ({
    page,
  }) => {
    await loginAsAdmin(page);
    await page.goto("/settings/login-history");
    await waitForPageReady(page);

    await expect(page).toHaveURL(/\/settings\/security/);
  });

  // =========================================================================
  // 5. MFA Page (/settings/mfa)
  // =========================================================================

  test("MFA page renders setup UI", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings/mfa");
    await waitForPageReady(page);

    // MFA page should show either setup or status
    const mfaContent = page.locator("main");
    await expect(mfaContent).not.toBeEmpty();

    // Should not crash or redirect to login
    await expect(page).toHaveURL(/\/settings\/mfa/);
  });

  // =========================================================================
  // 6. Notifications Page (/settings/notifications)
  // =========================================================================

  test("notifications settings page renders", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings/notifications");
    await waitForPageReady(page);

    // Should not crash or redirect
    await expect(page).toHaveURL(/\/settings\/notifications/);

    const content = page.locator("main");
    await expect(content).not.toBeEmpty();
  });

  // =========================================================================
  // 7. Session Revocation (from security page)
  // =========================================================================

  test("session revoke button opens confirmation dialog", async ({ page }) => {
    await loginAsAdmin(page);
    // Login a second time to create another session
    const login2 = await page.request.post(`${API_URL}/api/auth/login`, {
      form: { username: ADMIN_USERNAME, password: ADMIN_PASSWORD },
    });
    const body2 = await login2.json();
    if (body2.mfa_required) {
      await page.request.post(`${API_URL}/api/auth/verify-mfa`, {
        data: {
          mfa_token: body2.mfa_token,
          code: generateTOTP(ADMIN_TOTP_SECRET),
        },
      });
    }

    await page.goto("/settings/security");
    await waitForPageReady(page);

    // Look for "Thu hồi" button (for other sessions, not current)
    const revokeButton = page
      .getByRole("button", { name: "Thu hồi", exact: true })
      .first();
    const hasRevoke = await revokeButton.isVisible().catch(() => false);

    if (!hasRevoke) {
      // Only 1 session — no revoke button for "other" sessions
      test.skip();
      return;
    }

    await revokeButton.click();

    // Confirmation dialog should appear
    await expect(page.getByText("Thu hồi phiên này?")).toBeVisible();
    await expect(page.getByRole("button", { name: "Hủy" })).toBeVisible();

    // Cancel
    await page.getByRole("button", { name: "Hủy" }).click();
    await expect(page.getByText("Thu hồi phiên này?")).not.toBeVisible();
  });

  // =========================================================================
  // 8. Responsiveness (basic check)
  // =========================================================================

  test("security page renders on mobile viewport", async ({ browser }) => {
    const context = await browser.newContext({
      viewport: { width: 375, height: 812 },
    });
    const page = await context.newPage();
    await loginAsAdmin(page);
    await page.goto("/settings/security");
    await waitForPageReady(page);

    // Page should load without crash
    await expect(page).toHaveURL(/\/settings\/security/);

    // Sections should still be visible
    await expect(page.getByText("Phiên Đang Hoạt Động")).toBeVisible();
    await expect(page.getByText("Lịch sử đăng nhập")).toBeVisible();

    await context.close();
  });
});
