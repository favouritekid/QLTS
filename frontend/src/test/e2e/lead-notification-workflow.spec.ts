/**
 * E2E Runtime Test: Lead Notification Workflow
 *
 * Verifies browser notifications for lead events on real runtime flows.
 * Validates both inbox UI (/notifications) and delivery ops API.
 *
 * Covered runtime scenarios:
 * - lead_created (notifies unit managers)
 * - lead_assigned (notifies assigned officer)
 * - lead_status_changed (notifies lead owner via consultation status update)
 */
import {
  test,
  expect,
  type BrowserContext,
  type Page,
} from "@playwright/test";
import * as OTPAuth from "otpauth";

const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "@Abc12345!";
const ADMIN_TOTP_SECRET = process.env.E2E_ADMIN_TOTP_SECRET || "";

const API_URL =
  process.env.E2E_API_URL ||
  process.env.BACKEND_URL ||
  "http://backend:8000";
const FRONTEND_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000";
const AUTH_STORAGE_KEY = "auth-storage";
const AUTH_STORAGE_VERSION = 1;

type AuthResult = {
  headers: Record<string, string>;
  user: {
    id: number;
    username: string;
    full_name?: string | null;
    role?: string | null;
    unit_id?: number | null;
  };
};

type DiscoveryConfig = {
  offeringId: number;
  unitId: number;
  initialStatusId: string;
  secondStatusId: string | null;
};

type TempUser = {
  id: number;
  username: string;
  password: string;
  fullName: string;
  unitId: number;
};

// --- Helpers ---

function generatePhone(): string {
  const prefixes = ["091", "093", "097", "098", "035", "036", "085", "086"];
  const prefix = prefixes[Math.floor(Math.random() * prefixes.length)];
  const suffix = Math.floor(Math.random() * 10_000_000)
    .toString()
    .padStart(7, "0");
  return `${prefix}${suffix}`;
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

async function loginViaAPI(
  page: Page,
  username: string,
  password: string,
  opts?: { totpSecret?: string },
): Promise<AuthResult> {
  for (let attempt = 0; attempt < 3; attempt++) {
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
      if (!opts?.totpSecret) throw new Error(`MFA required for ${username} but no TOTP secret`);
      const mfaResp = await page.request.post(`${API_URL}/api/auth/verify-mfa`, {
        data: { mfa_token: loginBody.mfa_token, code: generateTOTP(opts.totpSecret) },
      });
      if (!mfaResp.ok()) { await page.waitForTimeout(31_000); continue; }
      authResp = mfaResp;
      authUser = (await mfaResp.json()).user;
    }

    const csrf = await extractAndAddCookies(page, authResp);
    if (!authUser) throw new Error(`Login for ${username} returned no user`);
    return { headers: csrf ? { "X-CSRF-Token": csrf } : {}, user: authUser };
  }
  throw new Error(`Unable to login as ${username} after 3 attempts`);
}

async function bootstrapUiSession(page: Page, auth: AuthResult): Promise<void> {
  await page.addInitScript(
    ({ key, value }) => window.localStorage.setItem(key, value),
    {
      key: AUTH_STORAGE_KEY,
      value: JSON.stringify({
        state: { user: auth.user, isAuthenticated: true },
        version: AUTH_STORAGE_VERSION,
      }),
    },
  );
  await page.goto(`${FRONTEND_URL}/notifications`);
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 });
  await page.waitForLoadState("domcontentloaded");
}

async function loginAndBootstrap(
  page: Page,
  username: string,
  password: string,
  opts?: { totpSecret?: string },
): Promise<AuthResult> {
  const auth = await loginViaAPI(page, username, password, opts);
  await bootstrapUiSession(page, auth);
  return auth;
}

async function createTempUser(
  page: Page,
  headers: Record<string, string>,
  role: string,
  unitId: number,
  prefix: string,
): Promise<TempUser> {
  const suffix = `${Date.now()}_${Math.floor(Math.random() * 1000)}`;
  const username = `${prefix}_${suffix}`;
  const password = "Test@1234567!";
  const fullName = `PW ${prefix} ${suffix}`;

  const createResp = await page.request.post(`${API_URL}/api/admin/users`, {
    headers,
    form: { username, email: `${username}@example.com`, password, full_name: fullName, role, status: "active" },
  });
  if (!createResp.ok() && createResp.status() !== 201) {
    throw new Error(`Create user failed: ${createResp.status()} ${(await createResp.text()).slice(0, 300)}`);
  }
  const created = await createResp.json();

  // Assign unit + capacity
  const updateResp = await page.request.put(`${API_URL}/api/admin/users/${created.id}`, {
    headers,
    form: { unit_id: String(unitId), max_capacity: "100", status: "active" },
  });
  expect(updateResp.ok()).toBeTruthy();

  return { id: created.id, username, password, fullName, unitId };
}

async function deactivateUser(page: Page, headers: Record<string, string>, userId: number): Promise<void> {
  await page.request.put(`${API_URL}/api/admin/users/${userId}`, {
    headers,
    form: { status: "inactive" },
  });
}

async function waitForNotification(
  page: Page,
  matcher: { title: string; messageIncludes?: string },
): Promise<{ id: number; title: string; message: string }> {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    const resp = await page.request.get(`${API_URL}/api/notifications`, {
      params: { page: 1, page_size: 100 },
    });
    if (resp.ok()) {
      const body = await resp.json();
      const match = (body.notifications || []).find(
        (n: { title: string; message: string }) =>
          n.title === matcher.title &&
          (!matcher.messageIncludes || n.message.includes(matcher.messageIncludes)),
      );
      if (match) return match;
    }
    await page.waitForTimeout(1_000);
  }
  throw new Error(`Notification not found: title="${matcher.title}" msg="${matcher.messageIncludes || ""}"`);
}

async function waitForDeliveryUsers(
  page: Page,
  query: { event: string; sourceType: string; sourceId: number; expectedUserIds: number[] },
): Promise<Array<{ user_id: number; status: string; channel: string }>> {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    const resp = await page.request.get(`${API_URL}/api/notification-deliveries`, {
      params: { page: 1, page_size: 50, event: query.event, channel: "browser", source_type: query.sourceType, source_id: query.sourceId },
    });
    if (resp.ok()) {
      const body = await resp.json();
      const ids = new Set((body.deliveries || []).map((d: { user_id: number }) => d.user_id));
      if (query.expectedUserIds.every((uid) => ids.has(uid))) return body.deliveries;
    }
    await page.waitForTimeout(1_000);
  }
  throw new Error(`Delivery not found: event=${query.event} source=${query.sourceType}:${query.sourceId}`);
}

async function assertNotificationVisibleInInbox(
  page: Page,
  matcher: { title: string; messageIncludes?: string },
): Promise<void> {
  await page.goto(`${FRONTEND_URL}/notifications`);
  await page.waitForLoadState("domcontentloaded");
  const searchInput = page.getByPlaceholder("Tìm kiếm thông báo...");
  await expect(searchInput).toBeVisible({ timeout: 15_000 });
  await searchInput.fill(matcher.title);
  await page.waitForTimeout(500);
  await expect(
    page.locator("a:visible, span:visible, p:visible").filter({ hasText: matcher.title }).first(),
  ).toBeVisible({ timeout: 15_000 });
}

// --- Test Suite ---

let adminContext: BrowserContext;
let adminPage: Page;
let adminAuth: AuthResult;

let managerContext: BrowserContext;
let managerPage: Page;
let managerAuth: AuthResult;

let officerContext: BrowserContext;
let officerPage: Page;
let officerAuth: AuthResult;

let discovery: DiscoveryConfig;
let tempManager: TempUser | null = null;
let tempOfficer: TempUser | null = null;

test.describe("Lead Notification Runtime Workflow", () => {
  test.describe.configure({ timeout: 600_000, mode: "serial" });

  test.beforeAll(async ({ browser }, testInfo) => {
    testInfo.setTimeout(300_000); // beforeAll needs time for rate-limit retries
    // Admin context (shared, used for setup + delivery ops queries)
    adminContext = await browser.newContext();
    adminPage = await adminContext.newPage();
    adminAuth = await loginAndBootstrap(
      adminPage, ADMIN_USERNAME, ADMIN_PASSWORD,
      ADMIN_TOTP_SECRET ? { totpSecret: ADMIN_TOTP_SECRET } : undefined,
    );

    // Discover config
    const pipelineResp = await adminPage.request.get(`${API_URL}/api/pipeline/all`);
    expect(pipelineResp.ok()).toBeTruthy();
    const pipeline = await pipelineResp.json();
    const statuses = pipeline.statuses || [];
    expect(statuses.length).toBeGreaterThan(0);

    const unitsResp = await adminPage.request.get(`${API_URL}/api/organization-units`);
    expect(unitsResp.ok()).toBeTruthy();
    const units = await unitsResp.json();

    const offeringsResp = await adminPage.request.get(`${API_URL}/api/program-offerings?is_active=true&limit=20`);
    expect(offeringsResp.ok()).toBeTruthy();
    const offerings = await offeringsResp.json();
    expect(Array.isArray(offerings) && offerings.length > 0).toBeTruthy();

    let offeringId = offerings[0].id as number;
    let unitId = units[0]?.id as number;

    for (const offering of offerings) {
      const previewResp = await adminPage.request.get(
        `${API_URL}/api/leads/distribution-preview?offering_id=${offering.id}`,
      );
      if (!previewResp.ok()) continue;
      const preview = await previewResp.json();
      if (preview?.next_unit_id) {
        offeringId = offering.id;
        unitId = preview.next_unit_id;
        break;
      }
    }

    discovery = {
      offeringId,
      unitId,
      initialStatusId: statuses[0].id,
      secondStatusId: statuses.length > 1 ? statuses[1].id : null,
    };

    // Create temp manager (for unit_managers notifications)
    tempManager = await createTempUser(adminPage, adminAuth.headers, "manager", discovery.unitId, "e2e_lead_mgr");
    // Create temp officer (for lead_owner notifications)
    tempOfficer = await createTempUser(adminPage, adminAuth.headers, "officer", discovery.unitId, "e2e_lead_off");

    // Login manager
    managerContext = await browser.newContext();
    managerPage = await managerContext.newPage();
    managerAuth = await loginAndBootstrap(managerPage, tempManager.username, tempManager.password);

    // Login officer
    officerContext = await browser.newContext();
    officerPage = await officerContext.newPage();
    officerAuth = await loginAndBootstrap(officerPage, tempOfficer.username, tempOfficer.password);
  });

  test.afterAll(async () => {
    if (adminPage && tempOfficer) await deactivateUser(adminPage, adminAuth.headers, tempOfficer.id);
    if (adminPage && tempManager) await deactivateUser(adminPage, adminAuth.headers, tempManager.id);
    await officerContext?.close();
    await managerContext?.close();
    await adminContext?.close();
  });

  // =========================================================================
  // Flow 1: lead_created → unit_managers
  // =========================================================================

  test("lead_created notifies unit manager and records delivery", async () => {
    if (!tempManager || !tempOfficer) throw new Error("Temp users not created");

    const leadName = `PW_LeadNotif_${Date.now()}`;
    const phone = generatePhone();

    // Admin creates lead in the same unit as tempManager
    const leadResp = await adminPage.request.post(`${API_URL}/api/leads`, {
      headers: adminAuth.headers,
      data: { full_name: leadName, phone, source: "walk_in", offering_id: discovery.offeringId },
    });
    expect(leadResp.ok() || leadResp.status() === 201).toBeTruthy();
    const lead = await leadResp.json();
    const leadId = lead.id as number;

    // Manager should receive lead_created notification
    const title = `Lead mới: ${leadName}`;
    await waitForNotification(managerPage, { title, messageIncludes: leadName });

    // Delivery ops: verify row
    await waitForDeliveryUsers(adminPage, {
      event: "lead_created",
      sourceType: "lead",
      sourceId: leadId,
      expectedUserIds: [tempManager.id],
    });

    // Inbox UI verification
    await assertNotificationVisibleInInbox(managerPage, { title });
  });

  // =========================================================================
  // Flow 2: lead_assigned → lead_owner (officer)
  // =========================================================================

  test("lead_assigned notifies officer and records delivery", async () => {
    if (!tempOfficer) throw new Error("Temp officer not created");

    const leadName = `PW_LeadNotif_${Date.now()}`;
    const phone = generatePhone();

    // Create lead
    const leadResp = await adminPage.request.post(`${API_URL}/api/leads`, {
      headers: adminAuth.headers,
      data: { full_name: leadName, phone, source: "walk_in", offering_id: discovery.offeringId },
    });
    expect(leadResp.ok() || leadResp.status() === 201).toBeTruthy();
    const lead = await leadResp.json();
    const leadId = lead.id as number;

    // Assign to temp officer
    const assignResp = await adminPage.request.post(`${API_URL}/api/leads/${leadId}/assign`, {
      headers: adminAuth.headers,
      data: { officer_id: tempOfficer.id },
    });
    expect(assignResp.ok()).toBeTruthy();

    // Officer should receive lead_assigned notification
    const title = `Lead được phân công: ${leadName}`;
    await waitForNotification(officerPage, { title, messageIncludes: leadName });

    // Delivery ops: verify row
    await waitForDeliveryUsers(adminPage, {
      event: "lead_assigned",
      sourceType: "lead",
      sourceId: leadId,
      expectedUserIds: [tempOfficer.id],
    });

    // Inbox UI verification
    await assertNotificationVisibleInInbox(officerPage, { title });
  });

  // =========================================================================
  // Flow 3: lead_status_changed → lead_owner (officer)
  // =========================================================================

  test("lead_status_changed notifies officer and records delivery", async () => {
    if (!tempOfficer) throw new Error("Temp officer not created");
    if (!discovery.secondStatusId) {
      console.warn("Only 1 consultation status in pipeline — skipping status change test");
      return;
    }

    const leadName = `PW_LeadNotif_${Date.now()}`;
    const phone = generatePhone();

    // Create lead
    const leadResp = await adminPage.request.post(`${API_URL}/api/leads`, {
      headers: adminAuth.headers,
      data: { full_name: leadName, phone, source: "walk_in", offering_id: discovery.offeringId },
    });
    expect(leadResp.ok() || leadResp.status() === 201).toBeTruthy();
    const lead = await leadResp.json();
    const leadId = lead.id as number;

    // Assign to officer first (officer needs to own the lead)
    const assignResp = await adminPage.request.post(`${API_URL}/api/leads/${leadId}/assign`, {
      headers: adminAuth.headers,
      data: { officer_id: tempOfficer.id },
    });
    expect(assignResp.ok()).toBeTruthy();

    // Set initial status via FSM endpoint
    const getResp = await adminPage.request.get(`${API_URL}/api/leads/${leadId}`, {
      headers: adminAuth.headers,
    });
    expect(getResp.ok()).toBeTruthy();
    const freshLead = await getResp.json();

    const statusResp = await adminPage.request.patch(`${API_URL}/api/leads/${leadId}/status`, {
      headers: adminAuth.headers,
      data: {
        consultation_status_id: discovery.initialStatusId,
        version: freshLead.version,
      },
    });
    if (!statusResp.ok()) {
      throw new Error(`Initial status set failed: ${statusResp.status()} ${(await statusResp.text()).slice(0, 500)}`);
    }

    // Now change to second status → triggers LEAD_STATUS_CHANGED
    const getResp2 = await adminPage.request.get(`${API_URL}/api/leads/${leadId}`, {
      headers: adminAuth.headers,
    });
    const lead2 = await getResp2.json();

    const status2Resp = await adminPage.request.patch(`${API_URL}/api/leads/${leadId}/status`, {
      headers: adminAuth.headers,
      data: {
        consultation_status_id: discovery.secondStatusId,
        version: lead2.version,
      },
    });
    if (!status2Resp.ok()) {
      throw new Error(`Status change failed: ${status2Resp.status()} ${(await status2Resp.text()).slice(0, 500)}`);
    }

    // Officer should receive lead_status_changed notification
    const title = `Lead cập nhật trạng thái: ${leadName}`;
    await waitForNotification(officerPage, { title, messageIncludes: leadName });

    // Delivery ops: verify row
    await waitForDeliveryUsers(adminPage, {
      event: "lead_status_changed",
      sourceType: "lead",
      sourceId: leadId,
      expectedUserIds: [tempOfficer.id],
    });

    // Inbox UI verification
    await assertNotificationVisibleInInbox(officerPage, { title });
  });
});
