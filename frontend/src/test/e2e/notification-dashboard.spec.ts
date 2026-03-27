/**
 * E2E Phase 5: Notification Dashboard — Playwright tests.
 *
 * Tests tab navigation, component rendering, and data display.
 * Uses admin login with TOTP for admin-only page access.
 */
import { test, expect, type Page, type Cookie } from "@playwright/test";
import * as OTPAuth from "otpauth";

const ADMIN_USERNAME = "admin";
const ADMIN_PASSWORD = "Admin@12345";
const TOTP_SECRET = "WUUT7KVVWRFVMVPZ7K6NGOKL2VYPPFH5";
const DASHBOARD_URL = "/admin/notification-deliveries";

function generateTOTP(secret: string): string {
  const totp = new OTPAuth.TOTP({
    secret: OTPAuth.Secret.fromBase32(secret),
    digits: 6,
    period: 30,
  });
  return totp.generate();
}

// Admin login helper
async function adminLogin(page: Page): Promise<void> {
  await page.goto("/login");
  await page.fill('input[placeholder="Tên đăng nhập"]', ADMIN_USERNAME);
  await page.fill('input[type="password"]', ADMIN_PASSWORD);
  await page.click('button[type="submit"]');

  // MFA step
  try {
    await page.waitForSelector('input[placeholder*="OTP"], input[name*="otp"], input[inputmode="numeric"]', { timeout: 5000 });
    const code = generateTOTP(TOTP_SECRET);
    const otpInput = page.locator('input[placeholder*="OTP"], input[name*="otp"], input[inputmode="numeric"]').first();
    await otpInput.fill(code);
    // Auto-submit or click verify
    const verifyBtn = page.locator('button:has-text("Xác nhận"), button:has-text("Verify")');
    if (await verifyBtn.isVisible()) {
      await verifyBtn.click();
    }
  } catch {
    // No MFA prompt — continue
  }

  await expect(page).not.toHaveURL(/\/login/, { timeout: 15000 });
  await page.waitForLoadState("networkidle");
}

test.describe.configure({ mode: "serial" });

test.describe("Notification Dashboard", () => {
  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await adminLogin(page);
    await page.context().storageState({ path: "src/test/.auth/admin.json" });
    await page.close();
  });

  test.use({ storageState: "src/test/.auth/admin.json" });

  test("page loads with correct heading", async ({ page }) => {
    await page.goto(DASHBOARD_URL);
    await expect(page.locator("h1")).toContainText("Delivery Monitoring");
  });

  test("Overview tab shows channel health panel", async ({ page }) => {
    await page.goto(DASHBOARD_URL);
    // Overview is default tab — check for channel names
    await expect(page.locator("text=browser").first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator("text=email").first()).toBeVisible();
  });

  test("Deliveries tab shows table", async ({ page }) => {
    await page.goto(DASHBOARD_URL);
    // Click Deliveries tab
    await page.click('button[role="tab"]:has-text("Deliveries")');
    // Should show table or empty state
    const table = page.locator("table");
    const emptyState = page.locator("text=Chưa có dữ liệu, text=No data, text=Không có");
    await expect(table.or(emptyState).first()).toBeVisible({ timeout: 10000 });
  });

  test("Configuration tab renders health info", async ({ page }) => {
    await page.goto(DASHBOARD_URL);
    await page.click('button[role="tab"]:has-text("Configuration")');
    // Should show channel health (same component as Overview)
    await expect(page.locator("text=browser").first()).toBeVisible({ timeout: 10000 });
  });

  test("tab switching preserves content", async ({ page }) => {
    await page.goto(DASHBOARD_URL);
    // Switch to Deliveries
    await page.click('button[role="tab"]:has-text("Deliveries")');
    await page.waitForTimeout(500);
    // Switch back to Overview
    await page.click('button[role="tab"]:has-text("Overview")');
    // Overview content should still be present
    await expect(page.locator("text=browser").first()).toBeVisible({ timeout: 10000 });
  });

  test("page handles loading states gracefully", async ({ page }) => {
    await page.goto(DASHBOARD_URL);
    // Page should not crash — check no error boundary
    await expect(page.locator("h1")).toContainText("Delivery Monitoring");
    // No unhandled errors
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    await page.waitForTimeout(2000);
    expect(errors).toHaveLength(0);
  });
});
