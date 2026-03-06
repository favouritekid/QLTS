/**
 * Smoke Test — All Pages
 *
 * Quét toàn bộ ứng dụng QLTS theo role để phát hiện:
 *   - Page crash / blank render
 *   - JS console errors (TypeError, ReferenceError, etc.)
 *   - API 5xx responses
 *   - Auth redirect (session hết hạn)
 *
 * Chạy:
 *   npx playwright test smoke-all-pages --project=e2e-workflow --reporter=list
 *   npx playwright test smoke-all-pages --project=e2e-workflow --headed
 *   npx playwright test smoke-all-pages -g "Admin" --project=e2e-workflow
 */

import { test, expect, type Page } from "@playwright/test";
import * as OTPAuth from "otpauth";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "Admin@12345";
// Prefer TOTP secret (reusable) over backup code (single-use)
const ADMIN_TOTP_SECRET = process.env.E2E_ADMIN_TOTP_SECRET || "WUUT7KVVWRFVMVPZ7K6NGOKL2VYPPFH5";
const ADMIN_MFA_CODE = process.env.E2E_ADMIN_MFA_CODE || "";

const OFFICER_USERNAME = process.env.E2E_OFFICER_USERNAME || "vothuhien";
const OFFICER_PASSWORD = process.env.E2E_OFFICER_PASSWORD || "@Matkhau123!";

const CTV_USERNAME = process.env.E2E_CTV_USERNAME || "";
const CTV_PASSWORD = process.env.E2E_CTV_PASSWORD || "";

const API_URL = process.env.E2E_API_URL || "http://localhost:8000";
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000";

// ---------------------------------------------------------------------------
// Page lists by role
// ---------------------------------------------------------------------------

interface PageEntry {
  name: string;
  path: string;
}

const ADMIN_PAGES: PageEntry[] = [
  // Dashboard
  { name: "Dashboard", path: "/dashboard" },
  { name: "Officer Dashboard", path: "/dashboard/officer" },
  // Leads
  { name: "Leads", path: "/leads" },
  { name: "Leads Pipeline", path: "/leads/pipeline" },
  // Admissions
  { name: "Admissions", path: "/admissions" },
  // Finance
  { name: "Finance", path: "/finance" },
  { name: "Finance Fees", path: "/finance/fees" },
  { name: "Finance Invoices", path: "/finance/invoices" },
  { name: "Finance Payments", path: "/finance/payments" },
  { name: "Finance Accounting", path: "/finance/accounting" },
  // Notifications
  { name: "Notifications", path: "/notifications" },
  // Admin - Users
  { name: "Admin Users", path: "/admin/users" },
  // Admin - CTV
  { name: "Admin Collaborators", path: "/admin/collaborators" },
  { name: "Admin Commissions", path: "/admin/commissions" },
  { name: "Admin Commission Policies", path: "/admin/commission-policies" },
  // Admin - Config
  { name: "Admin Config", path: "/admin/config" },
  { name: "Admin Admission Config", path: "/admin/admission-config" },
  { name: "Admin Pipeline", path: "/admin/pipeline" },
  // Admin - Org
  { name: "Admin Organization", path: "/admin/organization" },
  { name: "Admin Organization Tree", path: "/admin/organization-tree" },
  // Admin - Finance
  { name: "Admin Tuition Discount", path: "/admin/tuition-discount" },
  { name: "Admin Installment Plans", path: "/admin/installment-plans" },
  // Admin - Notifications
  { name: "Admin Notification Rules", path: "/admin/notification-rules" },
  { name: "Admin Notification Templates", path: "/admin/notification-templates" },
  // Admin - System
  { name: "Admin Audit Logs", path: "/admin/audit-logs" },
  { name: "Admin Deleted Items", path: "/admin/deleted-items" },
  { name: "Admin Monitoring", path: "/admin/monitoring" },
  // Admin - Advanced
  { name: "Admin Distribution", path: "/admin/distribution" },
  { name: "Admin KPI Config", path: "/admin/kpi-config" },
  { name: "Admin Policies", path: "/admin/policies" },
  // Settings
  { name: "Settings", path: "/settings" },
  { name: "Settings MFA", path: "/settings/mfa" },
  { name: "Settings Sessions", path: "/settings/sessions" },
  { name: "Settings Login History", path: "/settings/login-history" },
  { name: "Settings Notifications", path: "/settings/notifications" },
  // Other
  { name: "Profile", path: "/profile" },
  { name: "Guideline", path: "/guideline" },
];

const CTV_PAGES: PageEntry[] = [
  { name: "CTV Dashboard", path: "/ctv" },
  { name: "Notifications", path: "/notifications" },
  { name: "Settings", path: "/settings" },
];

const OFFICER_PAGES: PageEntry[] = [
  { name: "Officer Dashboard", path: "/dashboard/officer" },
  { name: "Leads", path: "/leads" },
  { name: "Leads Pipeline", path: "/leads/pipeline" },
  { name: "Admissions", path: "/admissions" },
  { name: "Notifications", path: "/notifications" },
  { name: "Settings", path: "/settings" },
  { name: "Profile", path: "/profile" },
];

// ---------------------------------------------------------------------------
// Helpers (reuse pattern from fee-lifecycle.spec.ts)
// ---------------------------------------------------------------------------

async function getCSRFToken(page: Page): Promise<string | undefined> {
  const cookies = await page.context().cookies();
  return cookies.find((c) => c.name === "csrf_token")?.value;
}

async function extractAndAddCookies(
  page: Page,
  resp: { headersArray(): Array<{ name: string; value: string }> }
): Promise<string> {
  const apiHost = new URL(API_URL).hostname;
  let csrf = "";

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
    if (m[1].trim() === "csrf_token") csrf = m[2];
  }

  if (!csrf) {
    const fallback = await getCSRFToken(page);
    if (fallback) csrf = fallback;
  }
  return csrf;
}

function generateTOTP(secret: string): string {
  const totp = new OTPAuth.TOTP({
    secret: OTPAuth.Secret.fromBase32(secret),
    digits: 6,
    period: 30,
    algorithm: "SHA1",
  });
  return totp.generate();
}

async function loginViaAPI(
  page: Page,
  username: string,
  password: string,
  opts?: { totpSecret?: string; backupCode?: string }
): Promise<void> {
  await page.context().clearCookies();

  const loginResp = await page.request.post(`${API_URL}/api/auth/login`, {
    form: { username, password },
  });
  if (!loginResp.ok()) {
    const body = (await loginResp.text()).slice(0, 300);
    throw new Error(`Login failed for ${username}: ${loginResp.status()} ${body}`);
  }

  let loginBody = await loginResp.json();
  let authResp = loginResp;

  if (loginBody.mfa_required) {
    // Prefer TOTP secret (reusable), fallback to backup code (single-use)
    const mfaCode = opts?.totpSecret
      ? generateTOTP(opts.totpSecret)
      : opts?.backupCode;

    if (!mfaCode) {
      throw new Error(
        `MFA required for ${username} but no TOTP secret or backup code provided`
      );
    }

    const mfaResp = await page.request.post(
      `${API_URL}/api/auth/verify-mfa`,
      { data: { mfa_token: loginBody.mfa_token, code: mfaCode } }
    );
    if (!mfaResp.ok()) {
      throw new Error(`MFA failed for ${username}: ${mfaResp.status()}`);
    }
    authResp = mfaResp;
  }

  await extractAndAddCookies(page, authResp);
}

// ---------------------------------------------------------------------------
// Console error noise filter
// ---------------------------------------------------------------------------

const NOISE_PATTERNS = [
  /favicon\.ico/i,
  /\[Fast Refresh\]/i,
  /Download the React DevTools/i,
  /hydration/i,
  /Failed to load resource/i,
  /Warning:/,
  /DevTools/i,
  /ERR_BLOCKED_BY_CLIENT/i,
  /net::ERR_/i,
  /ResizeObserver loop/i,
];

function isNoise(text: string): boolean {
  return NOISE_PATTERNS.some((re) => re.test(text));
}

// ---------------------------------------------------------------------------
// Result tracking
// ---------------------------------------------------------------------------

interface PageResult {
  name: string;
  path: string;
  status: "OK" | "JS_ERROR" | "API_500" | "BLANK" | "AUTH_REDIRECT" | "CRASH";
  errors: string[];
  durationMs: number;
}

// ---------------------------------------------------------------------------
// Core: visit a page and verify
// ---------------------------------------------------------------------------

async function visitAndVerify(
  page: Page,
  entry: PageEntry,
  jsErrors: string[],
  apiFailures: string[]
): Promise<PageResult> {
  const result: PageResult = {
    name: entry.name,
    path: entry.path,
    status: "OK",
    errors: [],
    durationMs: 0,
  };

  const start = Date.now();

  // Track page-specific errors
  const pageJsErrors: string[] = [];
  const pageApiFailures: string[] = [];

  const onConsole = (msg: import("@playwright/test").ConsoleMessage) => {
    if (msg.type() === "error") {
      const text = msg.text();
      if (!isNoise(text)) {
        pageJsErrors.push(text);
      }
    }
  };

  const onResponse = (resp: import("@playwright/test").Response) => {
    if (resp.status() >= 500) {
      pageApiFailures.push(`${resp.request().method()} ${resp.url()} → ${resp.status()}`);
    }
  };

  page.on("console", onConsole);
  page.on("response", onResponse);

  try {
    // Navigate
    const response = await page.goto(entry.path, {
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    });

    // Check for navigation failure
    if (!response) {
      result.status = "CRASH";
      result.errors.push("No response from navigation");
      return result;
    }

    // Wait for skeleton loaders to disappear (max 8s)
    try {
      await page.waitForFunction(
        () => document.querySelectorAll('[class*="skeleton"], [class*="Skeleton"], [data-loading="true"]').length === 0,
        { timeout: 8_000 }
      );
    } catch {
      // Timeout is OK — some pages may have persistent loading states
    }

    // Hydration buffer
    await page.waitForTimeout(1_000);

    // Check URL — auth redirect?
    const currentUrl = page.url();
    const pathname = new URL(currentUrl).pathname;
    if (pathname === "/login" || pathname.startsWith("/login?")) {
      result.status = "AUTH_REDIRECT";
      result.errors.push(`Redirected to login: ${currentUrl}`);
      return result;
    }

    // Check blank page (body content < 50 chars)
    const bodyLength = await page.evaluate(() => {
      return document.body?.innerText?.trim().length ?? 0;
    });

    if (bodyLength < 50) {
      result.status = "BLANK";
      result.errors.push(`Page body too short: ${bodyLength} chars`);
    }

    // Collect errors
    if (pageApiFailures.length > 0) {
      result.status = "API_500";
      for (const f of pageApiFailures) {
        result.errors.push(`API_500: ${f}`);
        apiFailures.push(`[${entry.name}] ${f}`);
      }
    }

    if (pageJsErrors.length > 0) {
      if (result.status === "OK") result.status = "JS_ERROR";
      for (const e of pageJsErrors) {
        result.errors.push(`JS_ERROR: ${e.slice(0, 200)}`);
        jsErrors.push(`[${entry.name}] ${e.slice(0, 200)}`);
      }
    }
  } catch (err) {
    result.status = "CRASH";
    result.errors.push(`CRASH: ${String(err).slice(0, 300)}`);
  } finally {
    page.removeListener("console", onConsole);
    page.removeListener("response", onResponse);
    result.durationMs = Date.now() - start;
  }

  return result;
}

// ---------------------------------------------------------------------------
// Report printer
// ---------------------------------------------------------------------------

function printReport(
  roleName: string,
  results: PageResult[],
  jsErrors: string[],
  apiFailures: string[]
) {
  const total = results.length;
  const ok = results.filter((r) => r.status === "OK").length;
  const errors = results.filter((r) => r.status !== "OK");
  const blanks = results.filter((r) => r.status === "BLANK").length;
  const authRedirects = results.filter((r) => r.status === "AUTH_REDIRECT").length;
  const crashes = results.filter((r) => r.status === "CRASH").length;

  console.log("");
  console.log("=".repeat(50));
  console.log(`  SMOKE TEST RESULTS — ${roleName}`);
  console.log("=".repeat(50));
  console.log(`  ${total}/${total} pages visited`);
  console.log(`    OK:             ${ok}`);
  console.log(`    JS Errors:      ${results.filter((r) => r.status === "JS_ERROR").length}`);
  console.log(`    API 5xx:        ${results.filter((r) => r.status === "API_500").length}`);
  console.log(`    Blank Pages:    ${blanks}`);
  console.log(`    Auth Redirects: ${authRedirects}`);
  console.log(`    Crashes:        ${crashes}`);

  if (errors.length > 0) {
    console.log("");
    console.log("  ERRORS:");
    for (const r of errors) {
      for (const e of r.errors) {
        console.log(`    [${r.name}] ${e}`);
      }
    }
  }

  if (jsErrors.length > 0) {
    console.log("");
    console.log(`  All JS Errors (${jsErrors.length}):`);
    for (const e of jsErrors) {
      console.log(`    ${e}`);
    }
  }

  if (apiFailures.length > 0) {
    console.log("");
    console.log(`  All API 5xx (${apiFailures.length}):`);
    for (const f of apiFailures) {
      console.log(`    ${f}`);
    }
  }

  console.log("=".repeat(50));
  console.log("");
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Smoke Test — All Pages", () => {
  test.describe.configure({ timeout: 300_000 }); // 5 minutes

  test("Admin: all pages load without crash", async ({ page }) => {
    await test.step("Login as admin", async () => {
      await loginViaAPI(page, ADMIN_USERNAME, ADMIN_PASSWORD, {
        totpSecret: ADMIN_TOTP_SECRET || undefined,
        backupCode: ADMIN_MFA_CODE || undefined,
      });
      // Verify login by visiting dashboard
      await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
      const url = page.url();
      expect(new URL(url).pathname).not.toBe("/login");
    });

    const results: PageResult[] = [];
    const jsErrors: string[] = [];
    const apiFailures: string[] = [];

    for (const entry of ADMIN_PAGES) {
      await test.step(`Visit: ${entry.name} (${entry.path})`, async () => {
        const result = await visitAndVerify(page, entry, jsErrors, apiFailures);
        results.push(result);

        // Screenshot on failure
        if (result.status !== "OK") {
          const screenshotName = `smoke-admin-${entry.name.replace(/\s+/g, "-").toLowerCase()}`;
          await page.screenshot({
            path: `test-results/smoke/${screenshotName}.png`,
            fullPage: true,
          });
        }
      });
    }

    printReport("ADMIN", results, jsErrors, apiFailures);

    // Assert: no crashes or blank pages (these are critical)
    const critical = results.filter(
      (r) => r.status === "CRASH" || r.status === "BLANK" || r.status === "AUTH_REDIRECT"
    );
    expect(
      critical,
      `Critical failures:\n${critical.map((r) => `  ${r.name}: ${r.errors.join(", ")}`).join("\n")}`
    ).toHaveLength(0);
  });

  test("CTV: pages load without crash", async ({ page }) => {
    test.skip(!CTV_USERNAME || !CTV_PASSWORD, "CTV credentials not provided");

    await test.step("Login as CTV", async () => {
      await loginViaAPI(page, CTV_USERNAME, CTV_PASSWORD);
      await page.goto("/ctv", { waitUntil: "domcontentloaded" });
      expect(new URL(page.url()).pathname).not.toBe("/login");
    });

    const results: PageResult[] = [];
    const jsErrors: string[] = [];
    const apiFailures: string[] = [];

    for (const entry of CTV_PAGES) {
      await test.step(`Visit: ${entry.name} (${entry.path})`, async () => {
        const result = await visitAndVerify(page, entry, jsErrors, apiFailures);
        results.push(result);

        if (result.status !== "OK") {
          const screenshotName = `smoke-ctv-${entry.name.replace(/\s+/g, "-").toLowerCase()}`;
          await page.screenshot({
            path: `test-results/smoke/${screenshotName}.png`,
            fullPage: true,
          });
        }
      });
    }

    printReport("CTV", results, jsErrors, apiFailures);

    const critical = results.filter(
      (r) => r.status === "CRASH" || r.status === "BLANK" || r.status === "AUTH_REDIRECT"
    );
    expect(
      critical,
      `Critical failures:\n${critical.map((r) => `  ${r.name}: ${r.errors.join(", ")}`).join("\n")}`
    ).toHaveLength(0);
  });

  test("Officer: pages load without crash", async ({ page }) => {
    await test.step("Login as officer", async () => {
      await loginViaAPI(page, OFFICER_USERNAME, OFFICER_PASSWORD);
      await page.goto("/dashboard/officer", { waitUntil: "domcontentloaded" });
      expect(new URL(page.url()).pathname).not.toBe("/login");
    });

    const results: PageResult[] = [];
    const jsErrors: string[] = [];
    const apiFailures: string[] = [];

    for (const entry of OFFICER_PAGES) {
      await test.step(`Visit: ${entry.name} (${entry.path})`, async () => {
        const result = await visitAndVerify(page, entry, jsErrors, apiFailures);
        results.push(result);

        if (result.status !== "OK") {
          const screenshotName = `smoke-officer-${entry.name.replace(/\s+/g, "-").toLowerCase()}`;
          await page.screenshot({
            path: `test-results/smoke/${screenshotName}.png`,
            fullPage: true,
          });
        }
      });
    }

    printReport("OFFICER", results, jsErrors, apiFailures);

    const critical = results.filter(
      (r) => r.status === "CRASH" || r.status === "BLANK" || r.status === "AUTH_REDIRECT"
    );
    expect(
      critical,
      `Critical failures:\n${critical.map((r) => `  ${r.name}: ${r.errors.join(", ")}`).join("\n")}`
    ).toHaveLength(0);
  });
});
