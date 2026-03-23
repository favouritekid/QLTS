import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import * as OTPAuth from "otpauth";

const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "Admin@12345";
const ADMIN_TOTP_SECRET =
  process.env.E2E_ADMIN_TOTP_SECRET || "WUUT7KVVWRFVMVPZ7K6NGOKL2VYPPFH5";

const OFFICER_USERNAME =
  process.env.E2E_OFFICER_USERNAME || process.env.TEST_USERNAME || "vothuhien";
const OFFICER_PASSWORD =
  process.env.E2E_OFFICER_PASSWORD || process.env.TEST_PASSWORD || "@Matkhau123!";

const API_URL = process.env.E2E_API_URL || "http://localhost:8000";
const FRONTEND_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000";

const LEADS_FILTERS_STORAGE_KEY = "leads_filters";
const LEADS_FILTERS_STORAGE_VERSION = 5;
const STALE_SEARCH_VALUE = "STALE_E2E_FILTER";

function generateTOTP(secret: string): string {
  const totp = new OTPAuth.TOTP({
    secret: OTPAuth.Secret.fromBase32(secret),
    digits: 6,
    period: 30,
    algorithm: "SHA1",
  });
  return totp.generate();
}

function extractAccessToken(
  resp: { headersArray(): Array<{ name: string; value: string }> },
): string | null {
  for (const header of resp.headersArray()) {
    if (header.name.toLowerCase() !== "set-cookie") continue;
    const match = header.value.match(/^access_token=([^;]+)/);
    if (match) return match[1];
  }

  return null;
}

async function getCSRFToken(page: Page): Promise<string | undefined> {
  const cookies = await page.context().cookies();
  return cookies.find((cookie) => cookie.name === "csrf_token")?.value;
}

async function extractAndAddCookies(
  page: Page,
  resp: { headersArray(): Array<{ name: string; value: string }> },
): Promise<string> {
  const apiHost = new URL(API_URL).hostname;
  let csrf = "";

  for (const header of resp.headersArray()) {
    if (header.name.toLowerCase() !== "set-cookie") continue;

    const cookieMatch = header.value.match(/^([^=]+)=([^;]*)/);
    if (!cookieMatch) continue;

    const pathMatch = header.value.match(/path=([^;]*)/i);
    await page.context().addCookies([
      {
        name: cookieMatch[1].trim(),
        value: cookieMatch[2],
        domain: apiHost,
        path: pathMatch ? pathMatch[1].trim() : "/",
        httpOnly: /httponly/i.test(header.value),
        secure: /secure/i.test(header.value),
      },
    ]);

    if (cookieMatch[1].trim() === "csrf_token") {
      csrf = cookieMatch[2];
    }
  }

  if (!csrf) {
    const fallback = await getCSRFToken(page);
    if (fallback) csrf = fallback;
  }

  return csrf;
}

async function loginViaAPI(
  page: Page,
  username: string,
  password: string,
  opts?: { totpSecret?: string },
): Promise<void> {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await page.context().clearCookies();

    const loginResp = await page.request.post(`${API_URL}/api/auth/login`, {
      form: { username, password },
    });

    if (loginResp.status() === 429) {
      await page.waitForTimeout(65_000);
      continue;
    }

    expect(loginResp.ok()).toBeTruthy();
    const loginBody = await loginResp.json();
    let authResp = loginResp;

    if (loginBody.mfa_required) {
      if (!opts?.totpSecret) {
        throw new Error(`MFA required for ${username} but no TOTP secret was provided`);
      }

      const mfaResp = await page.request.post(`${API_URL}/api/auth/verify-mfa`, {
        data: {
          mfa_token: loginBody.mfa_token,
          code: generateTOTP(opts.totpSecret),
        },
      });

      if (!mfaResp.ok()) {
        await page.waitForTimeout(31_000);
        continue;
      }

      authResp = mfaResp;
    }

    await extractAndAddCookies(page, authResp);
    return;
  }

  throw new Error(`Unable to login as ${username} after 3 attempts`);
}

async function loginWithBearer(
  request: APIRequestContext,
  username: string,
  password: string,
  opts?: { totpSecret?: string },
): Promise<Record<string, string>> {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const loginResp = await request.post(`${API_URL}/api/auth/login`, {
      form: { username, password },
    });

    if (loginResp.status() === 429) {
      await new Promise((resolve) => setTimeout(resolve, 65_000));
      continue;
    }

    expect(loginResp.ok()).toBeTruthy();
    const loginBody = await loginResp.json();

    if (loginBody.mfa_required) {
      if (!opts?.totpSecret) {
        throw new Error(`MFA required for ${username} but no TOTP secret was provided`);
      }

      const mfaResp = await request.post(`${API_URL}/api/auth/verify-mfa`, {
        data: {
          mfa_token: loginBody.mfa_token,
          code: generateTOTP(opts.totpSecret),
        },
      });

      if (!mfaResp.ok()) {
        await new Promise((resolve) => setTimeout(resolve, 31_000));
        continue;
      }

      const token = extractAccessToken(mfaResp);
      expect(token).toBeTruthy();
      return { Authorization: `Bearer ${token}` };
    }

    const token = extractAccessToken(loginResp);
    expect(token).toBeTruthy();
    return { Authorization: `Bearer ${token}` };
  }

  throw new Error(`Unable to login as ${username} after 3 attempts`);
}

async function getCurrentUserId(
  request: APIRequestContext,
  headers: Record<string, string>,
): Promise<number> {
  const response = await request.get(`${API_URL}/api/users/me`, { headers });
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(typeof body.id).toBe("number");
  return body.id;
}

async function seedStaleLeadsFilters(page: Page): Promise<void> {
  const staleFilters = JSON.stringify({
    version: LEADS_FILTERS_STORAGE_VERSION,
    data: {
      page: 3,
      search: STALE_SEARCH_VALUE,
      statusFilters: ["new"],
      sourceFilters: ["website"],
      validityFilters: ["valid"],
      offeringFilters: ["999"],
      stageFilters: ["stale-stage"],
      officerFilters: ["42"],
      unitId: "24",
      dateFrom: "2026-01-01",
      dateTo: "2026-01-31",
      dateField: "created_at",
      scoreMin: 10,
      scoreMax: 80,
      sortBy: "updated_at",
      sortOrder: "asc",
    },
  });

  await page.addInitScript(
    ({ key, value }) => {
      window.localStorage.setItem(key, value);
    },
    {
      key: LEADS_FILTERS_STORAGE_KEY,
      value: staleFilters,
    },
  );
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function extractFirstNumber(value: string): number {
  const match = value.match(/(\d[\d.,]*)/);
  if (!match) {
    throw new Error(`Unable to extract number from "${value}"`);
  }

  return Number(match[1].replace(/[.,]/g, ""));
}

async function extractButtonMetricCount(locator: ReturnType<Page["getByRole"]>): Promise<number> {
  const ariaLabel = await locator.getAttribute("aria-label");
  if (!ariaLabel) {
    throw new Error("Button is missing aria-label");
  }

  const metricPart = ariaLabel.split(":").slice(1).join(":").trim();
  const firstValue = metricPart.split("/")[0]?.trim() || metricPart;
  return extractFirstNumber(firstValue);
}

async function extractBadgeCount(page: Page): Promise<number> {
  const badge = page.getByText(/\d+\s+bản ghi/).first();
  await expect(badge).toBeVisible();
  const text = (await badge.textContent()) || "";
  return extractFirstNumber(text);
}

async function expectLeadsContextWithoutStaleFilters(page: Page): Promise<void> {
  const searchInput = page.locator('input[placeholder*="ki"]').first();
  await expect(searchInput).toHaveValue("");
  await expect(page.getByText(STALE_SEARCH_VALUE)).toHaveCount(0);
  await expect(page.getByRole("button", { name: /context/i })).toBeVisible();
}

test.describe("Dashboard Phase A/B regression", () => {
  test.describe.configure({ mode: "serial", timeout: 300_000 });

  test("Phase A: deep-link leads context beats stale localStorage and survives reload", async ({
    page,
  }) => {
    await seedStaleLeadsFilters(page);
    await loginViaAPI(page, OFFICER_USERNAME, OFFICER_PASSWORD);

    const deepLink =
      `${FRONTEND_URL}/leads?nav_source=dashboard` +
      "&metric_key=active_leads" +
      "&scope=personal" +
      "&status=new,assigned";

    await page.goto(deepLink);

    await expect(page).toHaveURL(/\/leads\?nav_source=dashboard/);
    await expect(page).toHaveURL(/status=new%2Cassigned|status=new,assigned/);
    await expectLeadsContextWithoutStaleFilters(page);

    await page.reload();

    await expect(page).toHaveURL(/\/leads\?nav_source=dashboard/);
    await expect(page).toHaveURL(/status=new%2Cassigned|status=new,assigned/);
    await expectLeadsContextWithoutStaleFilters(page);
  });

  test("Phase A: dashboard quick action opens create dialog and can exit dashboard context", async ({
    page,
  }) => {
    await loginViaAPI(page, OFFICER_USERNAME, OFFICER_PASSWORD);

    await page.goto(`${FRONTEND_URL}/dashboard/officer`);

    const quickAction = page.getByRole("button", { name: /Lead/i }).filter({ hasText: "Lead" }).last();
    await expect(quickAction).toBeVisible();
    await quickAction.click();

    await expect(page).toHaveURL(/\/leads\?nav_source=dashboard&action=create/);
    await expect(page.getByRole("button", { name: /Tạo Lead/i })).toBeVisible();

    await page.getByRole("button", { name: /Hủy/i }).click();
    await page.getByRole("button", { name: /context/i }).click();

    await expect(page).toHaveURL(`${FRONTEND_URL}/leads`);
    await expect(page.getByRole("button", { name: /context/i })).toHaveCount(0);
  });

  test("Phase B: consultations and enrollments drilldowns keep exact totals", async ({
    page,
  }) => {
    await loginViaAPI(page, OFFICER_USERNAME, OFFICER_PASSWORD);

    await page.goto(`${FRONTEND_URL}/dashboard/officer`);

    const consultationsCard = page.getByRole("button", {
      name: /^(Tư vấn hôm nay|TB tư vấn\/ngày):/i,
    });
    await expect(consultationsCard).toBeVisible();

    const consultationsCount = await extractButtonMetricCount(consultationsCard);
    await consultationsCard.click();

    await expect(page).toHaveURL(/\/dashboard\/drilldown\/consultations/);
    await expect(page).toHaveURL(/metric_key=consultations_today/);
    await expect(page.getByText(/Metric key:/)).toContainText("consultations_today");
    expect(await extractBadgeCount(page)).toBe(consultationsCount);

    await page.goto(`${FRONTEND_URL}/dashboard/officer`);

    const enrollmentsButton = page.getByRole("button", { name: /^Nhập học:/i });
    await expect(enrollmentsButton).toBeVisible();

    const enrollmentsCount = await extractButtonMetricCount(enrollmentsButton);
    await enrollmentsButton.click();

    await expect(page).toHaveURL(/\/dashboard\/drilldown\/transitions/);
    await expect(page).toHaveURL(/metric_key=enrollments_monthly/);
    await expect(page).toHaveURL(/final_only=1/);
    await expect(page).toHaveURL(/outcome=positive/);
    await expect(page.getByText(/Metric key:/)).toContainText("enrollments_monthly");
    expect(await extractBadgeCount(page)).toBe(enrollmentsCount);
  });

  test("Phase A: admin personal officer drilldown keeps officer scope in leads snapshot", async ({
    page,
    request,
  }) => {
    const officerHeaders = await loginWithBearer(request, OFFICER_USERNAME, OFFICER_PASSWORD);
    const officerId = await getCurrentUserId(request, officerHeaders);

    await loginViaAPI(page, ADMIN_USERNAME, ADMIN_PASSWORD, {
      totpSecret: ADMIN_TOTP_SECRET,
    });

    await page.goto(`${FRONTEND_URL}/dashboard/officer?scope=personal&officer=${officerId}`);

    const activeLeadsCard = page.getByRole("button", {
      name: new RegExp(`^${escapeRegExp("Leads đang xử lý")}:`, "i"),
    });
    await expect(activeLeadsCard).toBeVisible();
    await activeLeadsCard.click();

    await expect(page).toHaveURL(/\/leads\?/);
    await expect(page).toHaveURL(/nav_source=dashboard/);
    await expect(page).toHaveURL(/metric_key=active_leads/);
    await expect(page).toHaveURL(/scope=personal/);
    await expect(page).toHaveURL(new RegExp(`scope_officer_id=${officerId}`));
    await expect(page.getByRole("button", { name: /context/i })).toBeVisible();
  });
});
