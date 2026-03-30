/**
 * E2E: Notification Rule Create Flow
 *
 * Tests the full-page notification rule editor at /admin/notification-rules/new.
 * Uses admin login with TOTP for admin-only page access.
 *
 * Run:
 *   npx playwright test notification-rule-create --project=e2e-workflow --reporter=list
 *   npx playwright test notification-rule-create --project=e2e-workflow --headed
 */
import { test, expect, type Page } from "@playwright/test";
import * as OTPAuth from "otpauth";

const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "Admin@12345";
const TOTP_SECRET = process.env.E2E_ADMIN_TOTP_SECRET || "WUUT7KVVWRFVMVPZ7K6NGOKL2VYPPFH5";

function generateTOTP(secret: string): string {
  const totp = new OTPAuth.TOTP({
    secret: OTPAuth.Secret.fromBase32(secret),
    digits: 6,
    period: 30,
  });
  return totp.generate();
}

async function adminLogin(page: Page): Promise<void> {
  await page.goto("/login");
  await page.fill('input[placeholder="Tên đăng nhập"]', ADMIN_USERNAME);
  await page.fill('input[type="password"]', ADMIN_PASSWORD);
  await page.click('button[type="submit"]');

  try {
    await page.waitForSelector(
      'input[placeholder*="OTP"], input[name*="otp"], input[inputmode="numeric"]',
      { timeout: 5000 }
    );
    const code = generateTOTP(TOTP_SECRET);
    const otpInput = page
      .locator('input[placeholder*="OTP"], input[name*="otp"], input[inputmode="numeric"]')
      .first();
    await otpInput.fill(code);
    const verifyBtn = page.locator('button:has-text("Xác nhận"), button:has-text("Verify")');
    if (await verifyBtn.isVisible()) {
      await verifyBtn.click();
    }
  } catch {
    // No MFA prompt
  }

  await expect(page).not.toHaveURL(/\/login/, { timeout: 15000 });
  await page.waitForLoadState("networkidle");
}

test.describe("Notification Rule Create Flow", () => {
  // Each test gets its own browser context/page — login per test
  test.beforeEach(async ({ page }) => {
    await adminLogin(page);
  });

  test("page loads with step 1 and quick templates", async ({ page }) => {
    await page.goto("/admin/notification-rules/new");
    await page.waitForLoadState("networkidle");

    // Step indicator visible
    await expect(page.getByText("Sự kiện & Điều kiện")).toBeVisible();
    await expect(page.getByText("Soạn nội dung")).toBeVisible();
    await expect(page.getByText("Người nhận & Kênh gửi")).toBeVisible();
    await expect(page.getByText("Kiểm tra & Lưu")).toBeVisible();

    // Quick templates visible
    await expect(page.getByText("Cấu hình nhanh")).toBeVisible();
    await expect(page.getByText("Manager tạo lead → Gửi cho Officers")).toBeVisible();
  });

  test("quick template fills form and navigates to step 2", async ({ page }) => {
    await page.goto("/admin/notification-rules/new");
    await page.waitForLoadState("networkidle");

    // Click quick template
    await page.getByText("Lead được phân công").click();

    // Should be on step 2 — content section visible
    await expect(page.getByText("Bước 2: Nội dung mặc định")).toBeVisible();

    // Template should have pre-filled title
    const titleInput = page.locator("#title_template");
    await expect(titleInput).toHaveValue(/Lead được phân công/);
  });

  test("Next button blocks when step 1 is empty", async ({ page }) => {
    await page.goto("/admin/notification-rules/new");
    await page.waitForLoadState("networkidle");

    // Click Next without selecting an event
    await page.getByText("Tiếp theo").click();

    // Should still be on step 1 — inline error should appear
    await expect(page.locator(".text-destructive").first()).toBeVisible();
  });

  test("can navigate step 2 → 3 → 4 via quick template", async ({ page }) => {
    await page.goto("/admin/notification-rules/new");
    await page.waitForLoadState("networkidle");

    // Use quick template to fill steps 1-3
    await page.getByText("Lead được phân công").click();

    // Step 2 → 3
    await page.getByText("Tiếp theo").click();
    // Verify step 3 rendered (add group button)
    await expect(page.getByText("Thêm nhóm nhân viên")).toBeVisible({ timeout: 5000 });

    // Step 3 → 4
    await page.getByText("Tiếp theo").click();
    // Verify step 4 preview
    await expect(page.getByText("Tóm tắt quy tắc:")).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("Kích hoạt ngay")).toBeVisible();

    // Save button should be visible
    await expect(page.getByRole("button", { name: "Tạo quy tắc" })).toBeVisible();
  });
});
