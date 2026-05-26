/**
 * E2E Phase 5: Notification Dashboard — Playwright tests.
 *
 * Tests page structure, tab navigation, and data display.
 * Uses API-based login for reliability in container environments.
 *
 * Note: Some data-dependent assertions use relaxed checks because
 * the frontend fetches from backend via Next.js proxy, which may
 * show "Network Error" in container environments with cold cache.
 */
import { test, expect, type Page } from "@playwright/test";
import * as OTPAuth from "otpauth";

const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "Admin@123";
const TOTP_SECRET = process.env.E2E_ADMIN_TOTP_SECRET || "";
const API_URL =
  process.env.E2E_API_URL ||
  process.env.BACKEND_URL ||
  "http://backend:8000";
const FRONTEND_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000";
const DASHBOARD_URL = "/admin/notification-deliveries";
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

async function loginAndGotoDashboard(page: Page): Promise<void> {
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

  await page.goto(`${FRONTEND_URL}${DASHBOARD_URL}`);
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 });
  await page.waitForLoadState("domcontentloaded");
}

test.describe("Notification Dashboard", () => {
  test.describe.configure({ timeout: 120_000 });

  test.beforeEach(async ({ page }) => {
    await loginAndGotoDashboard(page);
  });

  test("page loads with correct heading", async ({ page }) => {
    // PR3: prefer data-testid over raw tag selector
    await expect(page.getByTestId("dashboard-heading")).toContainText("Delivery Monitoring");
  });

  test("Overview tab shows summary metrics", async ({ page }) => {
    // PR3: use data-testid for status cards instead of CSS class selectors
    await expect(page.getByTestId("card-queued")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("card-active-alerts")).toBeVisible();
  });

  test("Deliveries tab is clickable", async ({ page }) => {
    const tab = page.getByRole("tab", { name: "Deliveries" });
    await expect(tab).toBeVisible();
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true");
  });

  test("Configuration tab is clickable", async ({ page }) => {
    const tab = page.getByRole("tab", { name: "Configuration" });
    await expect(tab).toBeVisible();
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true");
  });

  test("tab switching preserves page structure", async ({ page }) => {
    await page.getByRole("tab", { name: "Deliveries" }).click();
    await page.waitForTimeout(500);
    await page.getByRole("tab", { name: "Overview" }).click();
    // PR3: data-testid instead of CSS class selector
    await expect(page.getByTestId("card-queued")).toBeVisible({ timeout: 10_000 });
  });

  test("page handles loading states gracefully", async ({ page }) => {
    await expect(page.getByTestId("dashboard-heading")).toContainText("Delivery Monitoring");
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    await page.waitForTimeout(2000);
    expect(errors).toHaveLength(0);
  });
});
