import {
  test,
  expect,
  type Locator,
  type Page,
} from "@playwright/test";
import * as OTPAuth from "otpauth";

const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "Admin@12345";
const ADMIN_TOTP_SECRET =
  process.env.E2E_ADMIN_TOTP_SECRET || "WUUT7KVVWRFVMVPZ7K6NGOKL2VYPPFH5";

const OFFICER_18_USERNAME =
  process.env.E2E_OFFICER18_USERNAME ||
  process.env.E2E_OFFICER_USERNAME ||
  "vothithuthuhien";
const OFFICER_18_PASSWORD =
  process.env.E2E_OFFICER18_PASSWORD ||
  process.env.E2E_OFFICER_PASSWORD ||
  "@Matkhau123!";

const OFFICER_16_USERNAME =
  process.env.E2E_OFFICER16_USERNAME || "nguyenhuuhieu";
const OFFICER_16_PASSWORD =
  process.env.E2E_OFFICER16_PASSWORD || "Officer@12345";

const MANAGER_22_USERNAME =
  process.env.E2E_MANAGER_USERNAME || "phanthithuyvan";
const MANAGER_22_PASSWORD =
  process.env.E2E_MANAGER_PASSWORD || "Manager@12345";

const API_URL = process.env.E2E_API_URL || "http://localhost:8000";
const FRONTEND_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000";
const BROWSER_LOCAL_API_ORIGIN = "http://localhost:8000";

const LEADS_FILTERS_STORAGE_KEY = "leads_filters";
const LEADS_FILTERS_STORAGE_VERSION = 5;
const AUTH_STORAGE_KEY = "auth-storage";
const AUTH_STORAGE_VERSION = 1;
const STALE_SEARCH_VALUE = "STALE_E2E_FILTER";

const OFFICER_18_ID = 18;
const OFFICER_16_ID = 16;
const DRILLDOWN_PAGE_SIZE = 20;

function generateTOTP(secret: string): string {
  const totp = new OTPAuth.TOTP({
    secret: OTPAuth.Secret.fromBase32(secret),
    digits: 6,
    period: 30,
    algorithm: "SHA1",
  });
  return totp.generate();
}

function normalizeText(value: string): string {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase()
    .replace(/[^a-z0-9%/]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
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
    let authUser = loginBody.user;

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
      authUser = (await mfaResp.json()).user;
    }

    await extractAndAddCookies(page, authResp);
    if (!authUser) {
      throw new Error(`Login response for ${username} did not include a user payload`);
    }

    await page.addInitScript(
      ({ key, value }) => {
        window.localStorage.setItem(key, value);
      },
      {
        key: AUTH_STORAGE_KEY,
        value: JSON.stringify({
          state: { user: authUser },
          version: AUTH_STORAGE_VERSION,
        }),
      },
    );
    return;
  }

  throw new Error(`Unable to login as ${username} after 3 attempts`);
}

async function installBrowserApiRewrite(page: Page): Promise<void> {
  const targetOrigin = new URL(API_URL).origin;
  if (targetOrigin === BROWSER_LOCAL_API_ORIGIN) {
    return;
  }

  await page.addInitScript(
    ({ localOrigin, apiOrigin }) => {
      const rewriteUrl = (value: string) =>
        value.startsWith(localOrigin) ? `${apiOrigin}${value.slice(localOrigin.length)}` : value;

      const originalFetch = window.fetch.bind(window);
      window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
        if (typeof input === "string") {
          return originalFetch(rewriteUrl(input), init);
        }

        if (input instanceof URL) {
          return originalFetch(new URL(rewriteUrl(input.toString())), init);
        }

        const rewritten = rewriteUrl(input.url);
        if (rewritten === input.url) {
          return originalFetch(input, init);
        }

        return originalFetch(new Request(rewritten, input), init);
      }) as typeof window.fetch;

      const originalOpen = XMLHttpRequest.prototype.open;
      XMLHttpRequest.prototype.open = function (
        method: string,
        url: string | URL,
        async?: boolean,
        username?: string | null,
        password?: string | null,
      ) {
        const rewritten = rewriteUrl(typeof url === "string" ? url : url.toString());
        return originalOpen.call(this, method, rewritten, async ?? true, username ?? null, password ?? null);
      };
    },
    {
      localOrigin: BROWSER_LOCAL_API_ORIGIN,
      apiOrigin: targetOrigin,
    },
  );
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

async function getAllAriaLabels(page: Page): Promise<string[]> {
  return page
    .locator("button[aria-label]")
    .evaluateAll((elements) =>
      elements
        .map((element) => element.getAttribute("aria-label") || "")
        .filter(Boolean),
    );
}

async function findMetricAriaLabel(
  page: Page,
  metricPrefix: string,
): Promise<string> {
  const normalizedPrefix = normalizeText(metricPrefix);
  const labels = await getAllAriaLabels(page);
  const label = labels.find((candidate) => {
    const normalized = normalizeText(candidate);
    return normalized.startsWith(`${normalizedPrefix} `) || normalized.startsWith(`${normalizedPrefix}:`);
  });

  if (!label) {
    throw new Error(
      `Unable to find dashboard metric button for "${metricPrefix}". Labels seen: ${labels.join(" | ")}`,
    );
  }

  return label;
}

async function tryFindMetricAriaLabel(
  page: Page,
  metricPrefix: string,
): Promise<string | null> {
  const normalizedPrefix = normalizeText(metricPrefix);
  const labels = await getAllAriaLabels(page);
  return labels.find((candidate) => {
    const normalized = normalizeText(candidate);
    return normalized.startsWith(`${normalizedPrefix} `) || normalized.startsWith(`${normalizedPrefix}:`);
  }) ?? null;
}

async function getMetricButton(
  page: Page,
  metricPrefix: string,
): Promise<Locator> {
  const ariaLabel = await findMetricAriaLabel(page, metricPrefix);
  return page.getByRole("button", { name: ariaLabel });
}

async function getMetricValue(
  page: Page,
  metricPrefix: string,
): Promise<string> {
  const ariaLabel = await findMetricAriaLabel(page, metricPrefix);
  return ariaLabel.split(":").slice(1).join(":").trim();
}

function extractFirstInteger(value: string): number {
  const match = value.match(/(\d[\d.,]*)/);
  if (!match) {
    throw new Error(`Unable to extract integer from "${value}"`);
  }

  return Number(match[1].replace(/[.,]/g, ""));
}

function extractFirstDecimal(value: string): number {
  const match = value.match(/(\d[\d.,]*)/);
  if (!match) {
    throw new Error(`Unable to extract decimal from "${value}"`);
  }

  return Number(match[1].replace(/\./g, "").replace(",", "."));
}

async function expectMetricValue(
  page: Page,
  metricPrefix: string,
  expected: string,
): Promise<Locator> {
  const button = await getMetricButton(page, metricPrefix);
  await expect(button).toBeVisible();
  await expect.poll(() => getMetricValue(page, metricPrefix)).toBe(expected);
  return button;
}

async function expectMetricFirstNumber(
  page: Page,
  metricPrefix: string,
  expected: number,
): Promise<Locator> {
  const button = await getMetricButton(page, metricPrefix);
  await expect(button).toBeVisible();
  await expect.poll(async () => extractFirstInteger(await getMetricValue(page, metricPrefix))).toBe(expected);
  return button;
}

async function expectMetricNotClickable(
  page: Page,
  metricPrefix: string,
): Promise<void> {
  const labels = await getAllAriaLabels(page);
  const normalizedPrefix = normalizeText(metricPrefix);
  const found = labels.some((candidate) => {
    const normalized = normalizeText(candidate);
    return normalized.startsWith(`${normalizedPrefix} `) || normalized.startsWith(`${normalizedPrefix}:`);
  });
  expect(found).toBeFalsy();
}

async function getValueNearLabel(page: Page, label: string): Promise<string> {
  const value = await page.evaluate((needle) => {
    const normalize = (input: string) =>
      input
        .normalize("NFD")
        .replace(/\p{Diacritic}/gu, "")
        .replace(/đ/g, "d")
        .replace(/Đ/g, "D")
        .toLowerCase()
        .replace(/[^a-z0-9%/]+/g, " ")
        .replace(/\s+/g, " ")
        .trim();

    const target = normalize(needle);
    const elements = Array.from(document.querySelectorAll("body *"));

    for (const element of elements) {
      const text = (element.textContent || "").trim();
      if (!text || normalize(text) !== target) continue;

      let current: HTMLElement | null = element as HTMLElement;
      for (let depth = 0; current && depth < 5; depth += 1) {
        const lines = (current.innerText || "")
          .split(/\n+/)
          .map((line) => line.trim())
          .filter(Boolean);

        const index = lines.findIndex((line) => normalize(line) === target);
        if (index !== -1) {
          for (let i = index + 1; i < lines.length; i += 1) {
            if (normalize(lines[i]) !== target) {
              return lines[i];
            }
          }
        }

        current = current.parentElement;
      }
    }

    return null;
  }, label);

  if (!value) {
    throw new Error(`Unable to find value near dashboard label "${label}"`);
  }

  return value;
}

async function expectLabeledValue(
  page: Page,
  label: string,
  expected: string,
): Promise<void> {
  await expect.poll(() => getValueNearLabel(page, label)).toBe(expected);
}

async function readBadgeCount(page: Page): Promise<number> {
  const badge = page.locator("main").getByText(/\d[\d.,]*\s+bản ghi/u).first();
  const text = (await badge.textContent())?.trim() || "";
  if (!text) {
    throw new Error('Unable to find drilldown record count badge inside <main>');
  }

  return extractFirstInteger(text);
}

async function expectDrilldownCount(page: Page, expectedCount: number): Promise<void> {
  await expect.poll(() => readBadgeCount(page)).toBe(expectedCount);

  if (expectedCount === 0) {
    await expect(page.getByText(/Không có dữ liệu/i)).toBeVisible();
    return;
  }

  await expect
    .poll(() => page.locator("tbody tr").count())
    .toBe(Math.min(expectedCount, DRILLDOWN_PAGE_SIZE));
}

async function expectLeadsRowCount(page: Page, expectedCount: number): Promise<void> {
  await expect.poll(async () => {
    const rowCount = await page.locator("tbody tr[data-index]").count();
    if (expectedCount === 0) {
      return rowCount === 0;
    }

    return rowCount > 0 && rowCount <= expectedCount;
  }).toBeTruthy();
}

async function readLeadsTotalCount(page: Page): Promise<number> {
  const footer = page.locator("main").getByText(/Hiển thị\s+\d+-\d+\s*\/\s*\d+\s+lead/u).first();
  const text = (await footer.textContent())?.trim() || "";
  const match = text.match(/\/\s*(\d[\d.,]*)\s+lead/u);
  if (!match) {
    throw new Error(`Unable to parse leads total count from footer: "${text}"`);
  }

  return extractFirstInteger(match[1]);
}

async function getTableColumnTexts(
  page: Page,
  columnIndex: number,
): Promise<string[]> {
  return (await page.locator(`tbody tr td:nth-child(${columnIndex})`).allTextContents())
    .map((value) => value.trim())
    .filter(Boolean);
}

async function clickBackToDashboard(page: Page): Promise<void> {
  await page.getByRole("button", { name: /Quay lại/i }).click();
  await expect(page).toHaveURL(/\/dashboard\/officer/);
  await waitForDashboardReady(page);
}

async function waitForDashboardReady(page: Page): Promise<void> {
  await expect
    .poll(() => tryFindMetricAriaLabel(page, "leads dang xu ly"), {
      timeout: 30_000,
      message: "Dashboard KPI cards did not finish hydrating",
    })
    .not.toBeNull();
  const activeLeadsButton = await getMetricButton(page, "leads dang xu ly");
  await expect(activeLeadsButton).toBeVisible();
}

async function openDashboard(
  page: Page,
  creds: {
    username: string;
    password: string;
    totpSecret?: string;
  },
  path: string = "/dashboard/officer",
): Promise<void> {
  await installBrowserApiRewrite(page);
  await loginViaAPI(page, creds.username, creds.password, {
    totpSecret: creds.totpSecret,
  });
  await page.goto(`${FRONTEND_URL}${path}`);
  await waitForDashboardReady(page);
}

async function expectOfficer18Snapshot(page: Page): Promise<void> {
  await expectMetricFirstNumber(page, "tu van hom nay", 0);
  await expectMetricValue(page, "leads dang xu ly", "13");
  await expectMetricValue(page, "ti le chot don", "100,0%");
  await expectMetricValue(page, "chuyen doi lead moi", "27,8%");
  await expectMetricValue(page, "hieu qua tu van", "100,0%");
  await expectMetricValue(page, "nhap hoc", "5");
  await expectLabeledValue(page, "tuan thu sla", "94,1%");
  await expectLabeledValue(page, "thoi gian phan hoi", "5,9h");
  await expectMetricNotClickable(page, "tuan thu sla");
  await expectMetricNotClickable(page, "thoi gian phan hoi");
}

async function expectOfficer16Snapshot(page: Page): Promise<void> {
  await expectMetricFirstNumber(page, "tu van hom nay", 0);
  await expectMetricValue(page, "leads dang xu ly", "14");
  await expectMetricValue(page, "ti le chot don", "0,0%");
  await expectMetricValue(page, "chuyen doi lead moi", "0,0%");
  await expectMetricValue(page, "hieu qua tu van", "0,0%");
  await expectMetricValue(page, "nhap hoc", "0");
  await expectLabeledValue(page, "tuan thu sla", "100,0%");
  await expectLabeledValue(page, "thoi gian phan hoi", "0,0h");
  await expectMetricNotClickable(page, "tuan thu sla");
  await expectMetricNotClickable(page, "thoi gian phan hoi");
}

async function expectManager22ZeroSnapshot(page: Page): Promise<void> {
  await expectMetricFirstNumber(page, "tu van hom nay", 0);
  await expectMetricValue(page, "leads dang xu ly", "0");
  await expectMetricValue(page, "ti le chot don", "0,0%");
  await expectMetricValue(page, "chuyen doi lead moi", "0,0%");
  await expectMetricValue(page, "hieu qua tu van", "0,0%");
  await expectMetricValue(page, "nhap hoc", "0");
  await expectLabeledValue(page, "tuan thu sla", "0,0%");
  await expectLabeledValue(page, "thoi gian phan hoi", "0,0h");
  await expectMetricNotClickable(page, "tuan thu sla");
  await expectMetricNotClickable(page, "thoi gian phan hoi");
}

async function expectAdminOrganizationSnapshot(page: Page): Promise<void> {
  await expectMetricFirstNumber(page, "tu van hom nay", 0);
  await expectMetricValue(page, "leads dang xu ly", "27");
  await expectMetricValue(page, "ti le chot don", "100,0%");
  await expectMetricValue(page, "chuyen doi lead moi", "15,6%");
  await expectMetricValue(page, "hieu qua tu van", "100,0%");
  await expectMetricValue(page, "nhap hoc", "5");
  await expectLabeledValue(page, "tuan thu sla", "96,0%");
  const responseTime = await getValueNearLabel(page, "thoi gian phan hoi");
  const responseHours = extractFirstDecimal(responseTime);
  expect(responseHours).toBeGreaterThanOrEqual(3);
  expect(responseHours).toBeLessThanOrEqual(4);
  await expectMetricNotClickable(page, "tuan thu sla");
  await expectMetricNotClickable(page, "thoi gian phan hoi");
}

async function expectWinRateDrilldown(page: Page, expectedRows: number): Promise<void> {
  const winRateButton = await getMetricButton(page, "ti le chot don");
  await winRateButton.click();

  await page.waitForURL(/\/dashboard\/drilldown\/transitions/, { timeout: 15_000 });
  await expect(page).toHaveURL(/metric_key=win_rate/, { timeout: 15_000 });
  await expect(page).toHaveURL(/final_only=1/, { timeout: 15_000 });
  await expectDrilldownCount(page, expectedRows);

  if (expectedRows > 0) {
    const outcomes = await getTableColumnTexts(page, 5);
    expect(outcomes).toHaveLength(expectedRows);
    expect(outcomes.every((value) => normalizeText(value) === "positive")).toBeTruthy();
  }
}

async function expectEnrollmentsDrilldown(page: Page, expectedRows: number): Promise<void> {
  const enrollmentsButton = await getMetricButton(page, "nhap hoc");
  await enrollmentsButton.click();

  await page.waitForURL(/\/dashboard\/drilldown\/transitions/, { timeout: 15_000 });
  await expect(page).toHaveURL(/metric_key=enrollments_monthly/, { timeout: 15_000 });
  await expect(page).toHaveURL(/final_only=1/, { timeout: 15_000 });
  await expect(page).toHaveURL(/outcome=positive/, { timeout: 15_000 });
  await expectDrilldownCount(page, expectedRows);

  if (expectedRows > 0) {
    const newStageNames = await getTableColumnTexts(page, 4);
    expect(newStageNames).toHaveLength(expectedRows);
    expect(
      newStageNames.every((value) => normalizeText(value) === normalizeText("Đã nhập học")),
    ).toBeTruthy();
  }
}

async function expectCohortsDrilldown(
  page: Page,
  expectedRows: number,
  expectedConverted: number,
  expectedOpen: number,
): Promise<void> {
  const cohortsButton = await getMetricButton(page, "chuyen doi lead moi");
  await cohortsButton.click();

  await page.waitForURL(/\/dashboard\/drilldown\/cohorts/, { timeout: 15_000 });
  await expect(page).toHaveURL(/metric_key=new_lead_conversion/, { timeout: 15_000 });
  await expectDrilldownCount(page, expectedRows);

  if (expectedRows > 0) {
    const visibleRows = Math.min(expectedRows, DRILLDOWN_PAGE_SIZE);
    const cohortResults = await getTableColumnTexts(page, 4);
    expect(cohortResults).toHaveLength(visibleRows);

    // Status distribution can only be verified when all rows fit on one page;
    // paginated results have unpredictable first-page distribution.
    if (expectedRows <= DRILLDOWN_PAGE_SIZE) {
      const convertedCount = cohortResults.filter(
        (value) => normalizeText(value) === "converted",
      ).length;
      const openCount = cohortResults.filter(
        (value) => normalizeText(value) === "open",
      ).length;
      expect(convertedCount).toBe(expectedConverted);
      expect(openCount).toBe(expectedOpen);
    }
  }
}

async function expectConsultationsTodayDrilldown(page: Page, expectedRows: number): Promise<void> {
  const consultationsButton = await getMetricButton(page, "tu van hom nay");
  await consultationsButton.click();

  await page.waitForURL(/\/dashboard\/drilldown\/consultations/, { timeout: 15_000 });
  await expect(page).toHaveURL(/metric_key=consultations_today/, { timeout: 15_000 });
  await expectDrilldownCount(page, expectedRows);
}

async function expectConsultationEffectivenessDrilldown(page: Page, expectedRows: number): Promise<void> {
  const effectivenessButton = await getMetricButton(page, "hieu qua tu van");
  await effectivenessButton.click();

  await page.waitForURL(/\/dashboard\/drilldown\/transitions/, { timeout: 15_000 });
  await expect(page).toHaveURL(/metric_key=consultation_effectiveness/, { timeout: 15_000 });
  await expect(page).toHaveURL(/final_only=1/, { timeout: 15_000 });
  await expect(page).toHaveURL(/consulted_only=1/, { timeout: 15_000 });
  await expectDrilldownCount(page, expectedRows);
}

async function expectActiveLeadsSnapshot(
  page: Page,
  expectedRows: number,
  extraUrlChecks?: RegExp[],
): Promise<void> {
  const activeLeadsButton = await getMetricButton(page, "leads dang xu ly");
  await activeLeadsButton.click();

  await expect(page).toHaveURL(/\/leads\?/);
  await expect(page).toHaveURL(/nav_source=dashboard/);
  await expect(page).toHaveURL(/is_final=false/);

  if (extraUrlChecks) {
    for (const pattern of extraUrlChecks) {
      await expect(page).toHaveURL(pattern);
    }
  }

  await expect.poll(() => readLeadsTotalCount(page)).toBe(expectedRows);
  await expectLeadsRowCount(page, expectedRows);
  await expect(page.getByRole("button", { name: /context/i })).toBeVisible();
}

async function openFunnelTable(page: Page): Promise<void> {
  await page.getByRole("button", { name: /^Bảng$/i }).click();
  await expect(page.getByRole("button", { name: /^Chưa tư vấn$/i })).toBeVisible();
}

async function expectOfficerSelectorExcludesUnit14Officers(page: Page): Promise<void> {
  const comboboxes = page.getByRole("combobox");
  const officerSelector = comboboxes.first();
  await officerSelector.click();
  const options = (await page.getByRole("option").allTextContents()).map((value) => value.trim());

  expect(options.some((value) => normalizeText(value) === normalizeText("Võ Thị Thu Thu Hiền"))).toBeFalsy();
  expect(options.some((value) => normalizeText(value) === normalizeText("Nguyễn Hữu Hiệu"))).toBeFalsy();

  await page.keyboard.press("Escape");
}

async function expectMetricPanelScopeLabel(page: Page, expectedLabel: string): Promise<void> {
  await expect(page.getByText(expectedLabel, { exact: true })).toBeVisible();
}

async function expectLeadsContextWithoutStaleFilters(page: Page): Promise<void> {
  const searchInput = page.locator('input[placeholder*="ki"]').first();
  await expect(searchInput).toHaveValue("");
  await expect(page.getByText(STALE_SEARCH_VALUE)).toHaveCount(0);
  await expect(page.getByRole("button", { name: /context/i })).toBeVisible();
}

test.describe("Dashboard Phase A/B regression", () => {
  test.describe.configure({ timeout: 300_000 });

  test("Phase A: deep-link create context beats stale localStorage and survives reload", async ({
    page,
  }) => {
    await installBrowserApiRewrite(page);
    await seedStaleLeadsFilters(page);
    await loginViaAPI(page, OFFICER_18_USERNAME, OFFICER_18_PASSWORD);

    const deepLink = `${FRONTEND_URL}/leads?nav_source=dashboard&action=create&scope=personal`;

    await page.goto(deepLink);

    await expect(page).toHaveURL(/\/leads\?nav_source=dashboard/);
    await expect(page).toHaveURL(/action=create/);
    await expect(page.getByRole("button", { name: /Tạo Lead/i })).toBeVisible();
    await page.getByRole("button", { name: /Hủy/i }).click();
    await expectLeadsContextWithoutStaleFilters(page);

    await page.reload();

    await expect(page).toHaveURL(/\/leads\?nav_source=dashboard/);
    await expect(page).toHaveURL(/action=create/);
    await expect(page.getByRole("button", { name: /Tạo Lead/i })).toBeVisible();
    await page.getByRole("button", { name: /Hủy/i }).click();
    await expectLeadsContextWithoutStaleFilters(page);
  });

  test("Phase A: dashboard quick action opens create dialog and can exit dashboard context", async ({
    page,
  }) => {
    await openDashboard(page, {
      username: OFFICER_18_USERNAME,
      password: OFFICER_18_PASSWORD,
    });

    await page.getByRole("button", { name: /Thêm Lead/i }).click();

    await expect(page).toHaveURL(/\/leads\?nav_source=dashboard&action=create/);
    await expect(page.getByRole("button", { name: /context/i })).toBeVisible();
    await page.getByRole("button", { name: /context/i }).click();

    await expect(page).toHaveURL(`${FRONTEND_URL}/leads`);
    await expect(page.getByRole("button", { name: /context/i })).toHaveCount(0);
  });

  test("Officer 18 personal audit matches KPI cards, drilldowns, funnel stage, and back navigation", async ({
    page,
  }) => {
    await openDashboard(page, {
      username: OFFICER_18_USERNAME,
      password: OFFICER_18_PASSWORD,
    });

    await expectWinRateDrilldown(page, 5);
    await expectMetricPanelScopeLabel(page, "Cá nhân");
    await clickBackToDashboard(page);

    await expectEnrollmentsDrilldown(page, 5);
    await clickBackToDashboard(page);

    await expectCohortsDrilldown(page, 18, 5, 13);
    await clickBackToDashboard(page);

    await expectConsultationEffectivenessDrilldown(page, 5);
    await clickBackToDashboard(page);

    await expectConsultationsTodayDrilldown(page, 0);
    await clickBackToDashboard(page);

    await expectOfficer18Snapshot(page);

    await openFunnelTable(page);
    await page.getByRole("button", { name: /^Chưa tư vấn$/i }).click();
    await expect(page).toHaveURL(/\/leads\?/);
    await expect(page).toHaveURL(/stage=stg01/);
    await expect.poll(() => page.locator("tbody tr[data-index]").count()).toBeGreaterThan(0);
  });

  test("Officer 16 personal audit matches low-conversion expectations", async ({
    page,
  }) => {
    await openDashboard(page, {
      username: OFFICER_16_USERNAME,
      password: OFFICER_16_PASSWORD,
    });

    await expectActiveLeadsSnapshot(page, 14, [/scope=personal/]);

    await page.goto(`${FRONTEND_URL}/dashboard/officer`);
    await waitForDashboardReady(page);

    await expectWinRateDrilldown(page, 0);
    await clickBackToDashboard(page);

    await expectOfficer16Snapshot(page);
  });

  test("Manager 22 stays unit-scoped to zero-data unit 19 and cannot escape to unit 14", async ({
    page,
  }) => {
    await openDashboard(page, {
      username: MANAGER_22_USERNAME,
      password: MANAGER_22_PASSWORD,
    });

    await expectManager22ZeroSnapshot(page);
    await expectOfficerSelectorExcludesUnit14Officers(page);

    await expectActiveLeadsSnapshot(page, 0, [/scope=unit/]);

    await page.goto(`${FRONTEND_URL}/dashboard/officer`);
    await waitForDashboardReady(page);

    await expectWinRateDrilldown(page, 0);
    await clickBackToDashboard(page);

    await page.goto(`${FRONTEND_URL}/dashboard/officer?scope=personal&officer=${OFFICER_18_ID}`);
    await expect(page).toHaveURL(/scope=personal&officer=18/);
    await expect(page.getByText(/Không thể tải thống kê dashboard/i)).toBeVisible();
    await expect(page.getByText("Võ Thị Thu Thu Hiền")).toHaveCount(0);
  });

  test("Admin organization audit aggregates officer 16 and officer 18 data correctly", async ({
    page,
  }) => {
    await openDashboard(page, {
      username: ADMIN_USERNAME,
      password: ADMIN_PASSWORD,
      totpSecret: ADMIN_TOTP_SECRET,
    });

    await expectActiveLeadsSnapshot(page, 27, [/scope=organization/]);

    await page.goto(`${FRONTEND_URL}/dashboard/officer`);
    await waitForDashboardReady(page);

    await expectWinRateDrilldown(page, 5);
    await clickBackToDashboard(page);

    await expectEnrollmentsDrilldown(page, 5);
    await clickBackToDashboard(page);

    await expectCohortsDrilldown(page, 32, 5, 27);
    await clickBackToDashboard(page);

    await expectAdminOrganizationSnapshot(page);
  });

  test("Admin personal drilldown mirrors officer-specific snapshots for officer 18 and officer 16", async ({
    page,
  }) => {
    await openDashboard(page, {
      username: ADMIN_USERNAME,
      password: ADMIN_PASSWORD,
      totpSecret: ADMIN_TOTP_SECRET,
    }, `/dashboard/officer?scope=personal&officer=${OFFICER_18_ID}`);

    await expectActiveLeadsSnapshot(page, 13, [
      /scope=personal/,
      new RegExp(`scope_officer_id=${OFFICER_18_ID}`),
    ]);
    await page.goto(
      `${FRONTEND_URL}/dashboard/officer?scope=personal&officer=${OFFICER_18_ID}`,
    );
    await waitForDashboardReady(page);
    await expectOfficer18Snapshot(page);

    await page.goto(
      `${FRONTEND_URL}/dashboard/officer?scope=personal&officer=${OFFICER_16_ID}`,
    );
    await waitForDashboardReady(page);

    await expectWinRateDrilldown(page, 0);
    await clickBackToDashboard(page);

    await expectOfficer16Snapshot(page);
  });
});
