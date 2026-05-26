/**
 * E2E Runtime Test: Finance Notification Workflow
 *
 * Verifies browser notifications for finance events on real runtime flows.
 * Validates both inbox UI (/notifications) and delivery ops API.
 *
 * Covered runtime scenarios:
 * - payment_verified (notifies assigned officer via specific_users resolver)
 *
 * Flow: officer owns lead/profile → admin records payment → manager verifies
 *       → officer receives payment_verified notification
 */
import {
  test,
  expect,
  type BrowserContext,
  type Page,
} from "@playwright/test";
import * as OTPAuth from "otpauth";

const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "Admin@123";
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
  user: { id: number; username: string; full_name?: string | null; role?: string | null; unit_id?: number | null };
};

type TempUser = { id: number; username: string; password: string; fullName: string; unitId: number };

type DiscoveryConfig = {
  admissionRoundId: number;
  offeringId: number;
  unitId: number;
  admissionMethodId: number;
  initialStatusId: string;
};

// ---- Helpers (reuse pattern from admissions/lead specs) ----

function generatePhone(): string {
  const prefixes = ["091", "093", "097", "098", "035", "036", "085", "086"];
  const prefix = prefixes[Math.floor(Math.random() * prefixes.length)];
  return `${prefix}${Math.floor(Math.random() * 10_000_000).toString().padStart(7, "0")}`;
}

function generateCitizenId(): string {
  return Array.from({ length: 12 }, () => Math.floor(Math.random() * 10)).join("");
}

function generateTOTP(secret: string): string {
  return new OTPAuth.TOTP({ secret: OTPAuth.Secret.fromBase32(secret), digits: 6, period: 30, algorithm: "SHA1" }).generate();
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
      name: match[1].trim(), value: match[2],
      path: pathMatch ? pathMatch[1].trim() : "/",
      httpOnly: /httponly/i.test(header.value), secure: /secure/i.test(header.value),
    };
    await page.context().addCookies([{ ...cookie, domain: apiHost }]);
    if (frontendHost !== apiHost) await page.context().addCookies([{ ...cookie, domain: frontendHost }]);
    if (match[1].trim() === "csrf_token") csrf = match[2];
  }
  return csrf;
}

async function loginViaAPI(
  page: Page, username: string, password: string, opts?: { totpSecret?: string },
): Promise<AuthResult> {
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.context().clearCookies();
    const loginResp = await page.request.post(`${API_URL}/api/auth/login`, { form: { username, password } });
    if (loginResp.status() === 429) { await page.waitForTimeout(65_000); continue; }
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
      authResp = mfaResp; authUser = (await mfaResp.json()).user;
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
    { key: AUTH_STORAGE_KEY, value: JSON.stringify({ state: { user: auth.user, isAuthenticated: true }, version: AUTH_STORAGE_VERSION }) },
  );
  await page.goto(`${FRONTEND_URL}/notifications`);
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 });
  await page.waitForLoadState("domcontentloaded");
}

async function loginAndBootstrap(
  page: Page, username: string, password: string, opts?: { totpSecret?: string },
): Promise<AuthResult> {
  const auth = await loginViaAPI(page, username, password, opts);
  await bootstrapUiSession(page, auth);
  return auth;
}

async function createTempUser(
  page: Page, headers: Record<string, string>, role: string, unitId: number, prefix: string,
): Promise<TempUser> {
  const suffix = `${Date.now()}_${Math.floor(Math.random() * 1000)}`;
  const username = `${prefix}_${suffix}`;
  const password = "Test@1234567!";
  const fullName = `PW ${prefix} ${suffix}`;
  const createResp = await page.request.post(`${API_URL}/api/admin/users`, {
    headers, form: { username, email: `${username}@example.com`, password, full_name: fullName, role, status: "active" },
  });
  if (!createResp.ok() && createResp.status() !== 201) {
    throw new Error(`Create user failed: ${createResp.status()} ${(await createResp.text()).slice(0, 300)}`);
  }
  const created = await createResp.json();
  const updateResp = await page.request.put(`${API_URL}/api/admin/users/${created.id}`, {
    headers, form: { unit_id: String(unitId), max_capacity: "100", status: "active" },
  });
  expect(updateResp.ok()).toBeTruthy();
  return { id: created.id, username, password, fullName, unitId };
}

async function deactivateUser(page: Page, headers: Record<string, string>, userId: number): Promise<void> {
  await page.request.put(`${API_URL}/api/admin/users/${userId}`, { headers, form: { status: "inactive" } });
}

async function waitForNotification(
  page: Page, matcher: { title: string; messageIncludes?: string },
): Promise<{ id: number; title: string; message: string }> {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    const resp = await page.request.get(`${API_URL}/api/notifications`, { params: { page: 1, page_size: 100 } });
    if (resp.ok()) {
      const body = await resp.json();
      const match = (body.notifications || []).find(
        (n: { title: string; message: string }) =>
          n.title === matcher.title && (!matcher.messageIncludes || n.message.includes(matcher.messageIncludes)),
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
  page: Page, matcher: { title: string; messageIncludes?: string },
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

// ---- Setup approved profile + fee + invoice (reuse from finance-lifecycle) ----

async function setupApprovedProfileWithFee(
  adminPage: Page, adminHeaders: Record<string, string>,
  officerPage: Page, officerHeaders: Record<string, string>,
  config: DiscoveryConfig,
): Promise<{ profileId: number; leadId: number; feeId: number; invoiceId: number; feeAmount: string }> {
  const leadName = `PW_FinNotif_${Date.now()}`;
  const phone = generatePhone();
  const citizenId = generateCitizenId();

  // 1. Officer creates lead
  const leadResp = await officerPage.request.post(`${API_URL}/api/leads`, {
    headers: officerHeaders,
    data: { full_name: leadName, phone, source: "walk_in", offering_id: config.offeringId },
  });
  expect(leadResp.ok() || leadResp.status() === 201).toBeTruthy();
  const lead = await leadResp.json();

  // 2. Consultation
  await officerPage.request.post(`${API_URL}/api/leads/${lead.id}/consultations`, {
    headers: officerHeaders,
    data: { status_id: config.initialStatusId, method: "phone", notes: "Finance notification test" },
  });

  // 3. Create admission profile
  const profileResp = await officerPage.request.post(`${API_URL}/api/admissions`, {
    headers: officerHeaders,
    data: {
      lead_id: lead.id,
      admission_method_id: config.admissionMethodId,
      admission_round_id: config.admissionRoundId,
      academic_year: 2026,
    },
  });
  if (!profileResp.ok() && profileResp.status() !== 201) {
    throw new Error(`Admission profile creation failed: ${profileResp.status()} ${(await profileResp.text()).slice(0, 300)}`);
  }
  const profile = await profileResp.json();

  // 4. Hydrate for submit (minimal)
  const getProfile = await officerPage.request.get(`${API_URL}/api/admissions/${profile.id}`, { headers: officerHeaders });
  const fresh = await getProfile.json();
  const subjects: Record<string, number> = {};
  for (const s of (fresh.applied_rules?.allowed_subject_codes || []).slice(0, 3)) subjects[s] = 8.0;

  await officerPage.request.put(`${API_URL}/api/admissions/${profile.id}`, {
    headers: officerHeaders,
    data: {
      version: fresh.version, citizen_id: citizenId, gender: "male", dob: "2001-01-15",
      nationality: "Viet Nam", ethnicity: "Kinh", place_of_birth: "Ha Noi",
      family_info: [{ relationship: "Cha", full_name: "PW Parent", phone: "0901234567", occupation: "Kỹ sư", is_primary_guardian: true }],
      academic_history: [{ school_name: "THPT Test", year_from: 2019, year_to: 2022, gpa: 8.0, graduation_type: "THPT" }],
      admission_scores: { subject_scores: subjects, gpa: 8.0 },
    },
  });

  // Handle mandatory docs
  const getAfter = await officerPage.request.get(`${API_URL}/api/admissions/${profile.id}`, { headers: officerHeaders });
  const updated = await getAfter.json();
  for (const doc of (updated.documents_checklist || []).filter((d: { is_mandatory?: boolean; status?: string }) => d.is_mandatory && d.status === "missing")) {
    if (doc.requires_upload === false) {
      await officerPage.request.post(`${API_URL}/api/admissions/${profile.id}/documents/${doc.code}/paper-submitted`, {
        headers: officerHeaders, data: { actual_submission_format: "original" },
      });
    } else {
      await officerPage.request.post(`${API_URL}/api/admissions/${profile.id}/documents/${doc.code}/upload`, {
        headers: officerHeaders,
        multipart: {
          file: { name: `${doc.code}.pdf`, mimeType: "application/pdf", buffer: Buffer.from(`%PDF-1.4\n%%EOF\n% fin-notif:${doc.code}`) },
          actual_submission_format: "photo",
        },
      });
    }
  }

  // 5. Submit
  const submitResp = await officerPage.request.post(`${API_URL}/api/admissions/${profile.id}/submit`, { headers: officerHeaders });
  expect(submitResp.ok()).toBeTruthy();

  // 6. Admin approves
  const getForApprove = await adminPage.request.get(`${API_URL}/api/admissions/${profile.id}`, { headers: adminHeaders });
  const forApprove = await getForApprove.json();
  const approveResp = await adminPage.request.post(`${API_URL}/api/admissions/${profile.id}/approve`, {
    headers: adminHeaders,
    data: { notes: "Finance notification test approval", version: forApprove.version },
  });
  expect(approveResp.ok()).toBeTruthy();

  // 7. Calculate fee
  const feeResp = await adminPage.request.post(`${API_URL}/api/fees/calculate`, {
    headers: adminHeaders,
    data: { admission_profile_id: profile.id, fee_type: "tuition", installment_plan_code: "FULL" },
  });
  if (!feeResp.ok()) {
    throw new Error(`Fee calculation failed: ${feeResp.status()} ${(await feeResp.text()).slice(0, 500)}`);
  }
  const fee = await feeResp.json();

  // 8. Issue invoice
  const invoiceId = fee.invoices?.[0]?.id || fee.invoice_id;
  if (invoiceId) {
    await adminPage.request.put(`${API_URL}/api/invoices/${invoiceId}/issue`, { headers: adminHeaders });
  }

  return {
    profileId: profile.id,
    leadId: lead.id,
    feeId: fee.id,
    invoiceId: invoiceId || 0,
    feeAmount: String(fee.total_amount || fee.final_amount || "0"),
  };
}

// ---- Test Suite ----

let adminContext: BrowserContext;
let adminPage: Page;
let adminAuth: AuthResult;

let officerContext: BrowserContext;
let officerPage: Page;
let officerAuth: AuthResult;

let managerContext: BrowserContext;
let managerPage: Page;
let managerAuth: AuthResult;

let discovery: DiscoveryConfig;
let tempOfficer: TempUser | null = null;
let tempManager: TempUser | null = null;

test.describe("Finance Notification Runtime Workflow", () => {
  test.describe.configure({ timeout: 600_000, mode: "serial" });

  test.beforeAll(async ({ browser }, testInfo) => {
    testInfo.setTimeout(300_000);

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
    const initialStatusId = pipeline.statuses?.[0]?.id;
    expect(initialStatusId).toBeTruthy();

    const unitsResp = await adminPage.request.get(`${API_URL}/api/organization-units`);
    const units = await unitsResp.json();

    const offeringsResp = await adminPage.request.get(`${API_URL}/api/program-offerings?is_active=true&limit=20`);
    const offerings = await offeringsResp.json();
    expect(Array.isArray(offerings) && offerings.length > 0).toBeTruthy();

    let offeringId = offerings[0].id as number;
    let unitId = units[0]?.id as number;
    for (const offering of offerings) {
      const previewResp = await adminPage.request.get(`${API_URL}/api/leads/distribution-preview?offering_id=${offering.id}`);
      if (!previewResp.ok()) continue;
      const preview = await previewResp.json();
      if (preview?.next_unit_id) { offeringId = offering.id; unitId = preview.next_unit_id; break; }
    }

    const methodsResp = await adminPage.request.get(`${API_URL}/api/admission-config/methods?active_only=true`);
    const methodsBody = await methodsResp.json();
    const methods = methodsBody.methods || methodsBody;

    // Plan B contract: admission_round_id required on profile create.
    const pathsResp = await adminPage.request.get(
      `${API_URL}/api/admission-config/paths/for-offering/${offeringId}`,
    );
    const pathsBody = await pathsResp.json();
    const paths = pathsBody.items || [];
    if (!paths.length) throw new Error(`No paths for offering ${offeringId}`);
    const admissionRoundId = paths[0].admission_round_id as number;

    discovery = { offeringId, unitId, admissionMethodId: methods[0].id, admissionRoundId, initialStatusId };

    // Temp officer (owns lead, receives notification)
    tempOfficer = await createTempUser(adminPage, adminAuth.headers, "officer", discovery.unitId, "e2e_fin_off");
    // Temp manager (verifies payment — maker-checker requires different user from admin who records)
    tempManager = await createTempUser(adminPage, adminAuth.headers, "manager", discovery.unitId, "e2e_fin_mgr");

    officerContext = await browser.newContext();
    officerPage = await officerContext.newPage();
    officerAuth = await loginAndBootstrap(officerPage, tempOfficer.username, tempOfficer.password);

    managerContext = await browser.newContext();
    managerPage = await managerContext.newPage();
    managerAuth = await loginAndBootstrap(managerPage, tempManager.username, tempManager.password);
  });

  test.afterAll(async () => {
    if (adminPage && tempOfficer) await deactivateUser(adminPage, adminAuth.headers, tempOfficer.id);
    if (adminPage && tempManager) await deactivateUser(adminPage, adminAuth.headers, tempManager.id);
    await managerContext?.close();
    await officerContext?.close();
    await adminContext?.close();
  });

  test("payment_received notifies assigned officer when payment is recorded", async () => {
    if (!tempOfficer || !tempManager) throw new Error("Temp users not created");

    const finance = await setupApprovedProfileWithFee(
      adminPage, adminAuth.headers,
      officerPage, officerAuth.headers,
      discovery,
    );

    const methodsResp = await adminPage.request.get(`${API_URL}/api/payments/methods`, { headers: adminAuth.headers });
    expect(methodsResp.ok()).toBeTruthy();
    const methods = await methodsResp.json();
    const paymentMethodId = (methods.methods || methods)[0]?.id;
    expect(paymentMethodId).toBeTruthy();

    // Admin records payment → triggers payment_received
    const payResp = await adminPage.request.post(`${API_URL}/api/payments`, {
      headers: adminAuth.headers,
      data: {
        invoice_id: finance.invoiceId,
        method_id: paymentMethodId,
        amount: finance.feeAmount,
        reference_code: `E2E_FINNOTIF_RCV_${Date.now()}`,
        payer_name: "PW Finance Received Test",
      },
    });
    if (!payResp.ok()) {
      throw new Error(`Payment creation failed: ${payResp.status()} ${(await payResp.text()).slice(0, 500)}`);
    }
    const payment = await payResp.json();
    expect(payment.status).toBe("pending");

    // Officer should receive payment_received notification
    const title = "Thanh toán mới được ghi nhận";
    await waitForNotification(officerPage, { title, messageIncludes: "chờ xác nhận" });

    // Delivery ops: verify row with admission_profile traceability
    await waitForDeliveryUsers(adminPage, {
      event: "payment_received",
      sourceType: "admission_profile",
      sourceId: finance.profileId,
      expectedUserIds: [tempOfficer.id],
    });

    // Inbox UI verification
    await assertNotificationVisibleInInbox(officerPage, { title });
  });

  test("payment_verified notifies assigned officer and records delivery", async () => {
    if (!tempOfficer || !tempManager) throw new Error("Temp users not created");

    // Build full state: lead → profile → approved → fee → invoice
    const finance = await setupApprovedProfileWithFee(
      adminPage, adminAuth.headers,
      officerPage, officerAuth.headers,
      discovery,
    );

    // Get payment method
    const methodsResp = await adminPage.request.get(`${API_URL}/api/payments/methods`, { headers: adminAuth.headers });
    expect(methodsResp.ok()).toBeTruthy();
    const methods = await methodsResp.json();
    const paymentMethodId = (methods.methods || methods)[0]?.id;
    expect(paymentMethodId).toBeTruthy();

    // Admin records payment (maker)
    const payResp = await adminPage.request.post(`${API_URL}/api/payments`, {
      headers: adminAuth.headers,
      data: {
        invoice_id: finance.invoiceId,
        method_id: paymentMethodId,
        amount: finance.feeAmount,
        reference_code: `E2E_FINNOTIF_${Date.now()}`,
        payer_name: "PW Finance Test",
      },
    });
    if (!payResp.ok()) {
      throw new Error(`Payment creation failed: ${payResp.status()} ${(await payResp.text()).slice(0, 500)}`);
    }
    const payment = await payResp.json();
    expect(payment.status).toBe("pending");

    // Manager verifies payment (checker — different user satisfies maker-checker)
    const verifyResp = await managerPage.request.put(
      `${API_URL}/api/payments/${payment.id}/verify`,
      { headers: managerAuth.headers },
    );
    if (!verifyResp.ok()) {
      throw new Error(`Payment verify failed: ${verifyResp.status()} ${(await verifyResp.text()).slice(0, 500)}`);
    }
    const verified = await verifyResp.json();
    expect(verified.status).toBe("verified");

    // Officer should receive payment_verified notification
    const title = "Thanh toán đã được xác nhận";
    await waitForNotification(officerPage, { title, messageIncludes: "xác nhận thành công" });

    // Delivery ops: verify row with admission_profile traceability
    await waitForDeliveryUsers(adminPage, {
      event: "payment_verified",
      sourceType: "admission_profile",
      sourceId: finance.profileId,
      expectedUserIds: [tempOfficer.id],
    });

    // Inbox UI verification
    await assertNotificationVisibleInInbox(officerPage, { title });
  });
});
