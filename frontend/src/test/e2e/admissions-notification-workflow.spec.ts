/**
 * E2E Runtime Test: Admissions Notification Workflow
 *
 * Goal:
 * - Verify browser notifications for the first admissions batch on real runtime flows
 * - Validate both inbox UI (/notifications) and delivery ops API visibility
 *
 * Covered runtime scenarios:
 * - application_created
 * - application_status_changed: draft -> submitted
 * - application_status_changed: submitted -> approved
 * - application_status_changed: approved -> confirmed (public confirm flow)
 */

import {
  test,
  expect,
  type BrowserContext,
  type Cookie,
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
    email?: string | null;
    role?: string | null;
    unit_id?: number | null;
  };
};

type DiscoveryConfig = {
  offeringId: number;
  unitId: number;
  admissionMethodId: number;
  initialStatusId: string;
};

type TempOfficer = {
  id: number;
  username: string;
  password: string;
  fullName: string;
  email: string;
  unitId: number;
};

type DraftAdmission = {
  leadId: number;
  leadName: string;
  citizenId: string;
  profileId: number;
  version: number;
};

let adminContext: BrowserContext;
let adminPage: Page;
let adminAuth: AuthResult;

let officerContext: BrowserContext;
let officerPage: Page;
let officerAuth: AuthResult;

let discovery: DiscoveryConfig;
let tempOfficer: TempOfficer | null = null;

function generatePhone(): string {
  const prefixes = ["091", "093", "097", "098", "035", "036", "085", "086"];
  const prefix = prefixes[Math.floor(Math.random() * prefixes.length)];
  const suffix = Math.floor(Math.random() * 10_000_000)
    .toString()
    .padStart(7, "0");
  return `${prefix}${suffix}`;
}

function generateCitizenId(): string {
  return Array.from({ length: 12 }, () => Math.floor(Math.random() * 10)).join("");
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

async function getCSRFToken(page: Page): Promise<string | undefined> {
  const cookies = await page.context().cookies();
  return cookies.find((cookie) => cookie.name === "csrf_token")?.value;
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

    if (match[1].trim() === "csrf_token") {
      csrf = match[2];
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
): Promise<AuthResult> {
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

    const csrf = await extractAndAddCookies(page, authResp);
    if (!authUser) {
      throw new Error(`Login response for ${username} did not include a user payload`);
    }

    return {
      headers: csrf ? { "X-CSRF-Token": csrf } : {},
      user: authUser,
    };
  }

  throw new Error(`Unable to login as ${username} after 3 attempts`);
}

async function bootstrapUiSession(page: Page, auth: AuthResult): Promise<void> {
  await page.addInitScript(
    ({ key, value }) => {
      window.localStorage.setItem(key, value);
    },
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

async function discoverAdmissionsConfig(page: Page): Promise<DiscoveryConfig> {
  const pipelineResp = await page.request.get(`${API_URL}/api/pipeline/all`);
  expect(pipelineResp.ok()).toBeTruthy();
  const pipeline = await pipelineResp.json();
  const initialStatusId = pipeline.statuses?.[0]?.id;
  expect(initialStatusId).toBeTruthy();

  const unitsResp = await page.request.get(`${API_URL}/api/organization-units`);
  expect(unitsResp.ok()).toBeTruthy();
  const units = await unitsResp.json();

  const offeringsResp = await page.request.get(
    `${API_URL}/api/program-offerings?is_active=true&limit=20`,
  );
  expect(offeringsResp.ok()).toBeTruthy();
  const offerings = await offeringsResp.json();
  expect(Array.isArray(offerings) && offerings.length > 0).toBeTruthy();

  let offeringId = offerings[0].id as number;
  let unitId = units[0]?.id as number;

  for (const offering of offerings) {
    const previewResp = await page.request.get(
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

  expect(offeringId).toBeTruthy();
  expect(unitId).toBeTruthy();

  const methodsResp = await page.request.get(
    `${API_URL}/api/admission-config/methods?active_only=true`,
  );
  expect(methodsResp.ok()).toBeTruthy();
  const methodsBody = await methodsResp.json();
  const methods = methodsBody.methods || methodsBody;
  expect(Array.isArray(methods) && methods.length > 0).toBeTruthy();

  return {
    offeringId,
    unitId,
    admissionMethodId: methods[0].id,
    initialStatusId,
  };
}

async function createTempOfficerUser(
  page: Page,
  unitId: number,
): Promise<TempOfficer> {
  const suffix = `${Date.now()}_${Math.floor(Math.random() * 1000)}`;
  const username = `e2e_adm_notif_${suffix}`;
  const email = `${username}@example.com`;
  const password = "Officer@12345!";
  const fullName = `E2E Admissions Officer ${suffix}`;

  const createResp = await page.request.post(`${API_URL}/api/admin/users`, {
    headers: adminAuth.headers,
    form: {
      username,
      email,
      password,
      full_name: fullName,
      role: "officer",
      status: "active",
    },
  });
  expect(createResp.ok() || createResp.status() === 201).toBeTruthy();
  const created = await createResp.json();

  const updateResp = await page.request.put(`${API_URL}/api/admin/users/${created.id}`, {
    headers: adminAuth.headers,
    form: {
      unit_id: String(unitId),
      max_capacity: "100",
      status: "active",
    },
  });
  expect(updateResp.ok()).toBeTruthy();

  return {
    id: created.id,
    username,
    password,
    fullName,
    email,
    unitId,
  };
}

async function deactivateTempOfficer(page: Page, officer: TempOfficer): Promise<void> {
  const resp = await page.request.put(`${API_URL}/api/admin/users/${officer.id}`, {
    headers: adminAuth.headers,
    form: {
      status: "inactive",
    },
  });

  if (!resp.ok()) {
    console.warn(`Failed to deactivate temp officer ${officer.id}: ${resp.status()} ${await resp.text()}`);
  }
}

async function createMinimalDraftAdmission(
  page: Page,
  headers: Record<string, string>,
  config: DiscoveryConfig,
): Promise<DraftAdmission> {
  const leadName = `PW_AdmNotif_${Date.now()}`;
  const phone = generatePhone();
  const citizenId = generateCitizenId();

  const leadResp = await page.request.post(`${API_URL}/api/leads`, {
    headers,
    data: {
      full_name: leadName,
      phone,
      source: "walk_in",
      offering_id: config.offeringId,
    },
  });
  expect(leadResp.ok() || leadResp.status() === 201).toBeTruthy();
  const lead = await leadResp.json();
  const leadId = lead.id as number;

  const consultationResp = await page.request.post(
    `${API_URL}/api/leads/${leadId}/consultations`,
    {
      headers,
      data: {
        status_id: config.initialStatusId,
        method: "phone",
        notes: "Admissions notification runtime test",
      },
    },
  );
  expect(consultationResp.ok() || consultationResp.status() === 201).toBeTruthy();

  const profileResp = await page.request.post(`${API_URL}/api/admissions`, {
    headers,
    data: {
      lead_id: leadId,
      admission_method_id: config.admissionMethodId,
    },
  });
  if (!profileResp.ok() && profileResp.status() !== 201) {
    throw new Error(
      `Admission profile creation failed: ${profileResp.status()} ${(await profileResp.text()).slice(0, 500)}`,
    );
  }

  const profile = await profileResp.json();
  return {
    leadId,
    leadName,
    citizenId,
    profileId: profile.id as number,
    version: profile.version as number,
  };
}

async function hydrateAdmissionProfileForSubmit(
  page: Page,
  headers: Record<string, string>,
  profileId: number,
  version: number,
  citizenId: string,
): Promise<number> {
  const getBeforeResp = await page.request.get(`${API_URL}/api/admissions/${profileId}`, {
    headers,
  });
  expect(getBeforeResp.ok()).toBeTruthy();
  const freshProfile = await getBeforeResp.json();

  const allowedSubjects: string[] = freshProfile.applied_rules?.allowed_subject_codes || [];
  const subjectScores: Record<string, number> = {};
  for (const subject of allowedSubjects.slice(0, 3)) {
    subjectScores[subject] = 7 + Math.random() * 2;
  }

  const updateResp = await page.request.put(`${API_URL}/api/admissions/${profileId}`, {
    headers,
    data: {
      version,
      citizen_id: citizenId,
      gender: "female",
      dob: "2001-06-20",
      nationality: "Viet Nam",
      ethnicity: "Kinh",
      place_of_birth: "TP Ho Chi Minh",
      family_info: [
        {
          relationship: "Cha",
          full_name: "Nguyen Van A",
          phone: "0901234567",
          occupation: "Kinh doanh",
          is_primary_guardian: true,
        },
        {
          relationship: "Me",
          full_name: "Tran Thi B",
          phone: "0901234568",
          occupation: "Giao vien",
          is_primary_guardian: false,
        },
      ],
      academic_history: [
        {
          school_name: "THPT Nguyen Du",
          year_from: 2019,
          year_to: 2022,
          gpa: 8.5,
          graduation_type: "THPT",
        },
      ],
      admission_scores: {
        subject_scores: subjectScores,
        gpa: 8.5,
      },
    },
  });
  expect(updateResp.ok()).toBeTruthy();

  const getAfterResp = await page.request.get(`${API_URL}/api/admissions/${profileId}`, {
    headers,
  });
  expect(getAfterResp.ok()).toBeTruthy();
  const updatedProfile = await getAfterResp.json();

  const missingMandatoryDocs = (updatedProfile.documents_checklist || []).filter(
    (doc: { is_mandatory?: boolean; status?: string }) =>
      doc.is_mandatory && doc.status === "missing",
  );

  for (const doc of missingMandatoryDocs) {
    if (doc.requires_upload === false) {
      const paperResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId}/documents/${doc.code}/paper-submitted`,
        {
          headers,
          data: {
            actual_submission_format: "original",
          },
        },
      );
      expect(paperResp.ok()).toBeTruthy();
      continue;
    }

    const uploadResp = await page.request.post(
      `${API_URL}/api/admissions/${profileId}/documents/${doc.code}/upload`,
      {
        headers,
        multipart: {
          file: {
            name: `${doc.code}.pdf`,
            mimeType: "application/pdf",
            buffer: Buffer.from(`%PDF-1.4\n%%EOF\n% admissions-notification:${doc.code}`),
          },
          actual_submission_format: "photo",
        },
      },
    );
    expect(uploadResp.ok()).toBeTruthy();
  }

  const freshResp = await page.request.get(`${API_URL}/api/admissions/${profileId}`, {
    headers,
  });
  expect(freshResp.ok()).toBeTruthy();
  const fresh = await freshResp.json();
  return fresh.version as number;
}

async function waitForNotification(
  page: Page,
  matcher: { title: string; messageIncludes?: string },
): Promise<{ id: number; title: string; message: string }> {
  const deadline = Date.now() + 45_000;

  while (Date.now() < deadline) {
    const resp = await page.request.get(`${API_URL}/api/notifications`, {
      params: {
        page: 1,
        page_size: 100,
      },
    });

    if (resp.ok()) {
      const body = await resp.json();
      const match = (body.notifications || []).find(
        (notification: { id: number; title: string; message: string }) =>
          notification.title === matcher.title &&
          (!matcher.messageIncludes ||
            notification.message.includes(matcher.messageIncludes)),
      );

      if (match) {
        return match;
      }
    }

    await page.waitForTimeout(1_000);
  }

  throw new Error(
    `Notification not found: title="${matcher.title}" messageIncludes="${matcher.messageIncludes || ""}"`,
  );
}

async function waitForDeliveryUsers(
  page: Page,
  query: {
    event: string;
    sourceType: string;
    sourceId: number;
    expectedUserIds: number[];
  },
): Promise<Array<{ user_id: number; status: string; channel: string }>> {
  const deadline = Date.now() + 45_000;

  while (Date.now() < deadline) {
    const resp = await page.request.get(`${API_URL}/api/notification-deliveries`, {
      params: {
        page: 1,
        page_size: 50,
        event: query.event,
        channel: "browser",
        source_type: query.sourceType,
        source_id: query.sourceId,
      },
    });

    if (resp.ok()) {
      const body = await resp.json();
      const deliveries = body.deliveries || [];
      const deliveredUserIds = new Set(
        deliveries
          .filter((item: { channel: string }) => item.channel === "browser")
          .map((item: { user_id: number }) => item.user_id),
      );

      if (query.expectedUserIds.every((userId) => deliveredUserIds.has(userId))) {
        return deliveries;
      }
    }

    await page.waitForTimeout(1_000);
  }

  throw new Error(
    `Delivery rows not found for event=${query.event} source=${query.sourceType}:${query.sourceId}`,
  );
}

async function getDeliveryCount(
  page: Page,
  query: { event: string; sourceType: string; sourceId: number },
): Promise<number> {
  const resp = await page.request.get(`${API_URL}/api/notification-deliveries`, {
    params: {
      page: 1,
      page_size: 50,
      event: query.event,
      source_type: query.sourceType,
      source_id: query.sourceId,
    },
  });
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  return body.total_count || 0;
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

  const visibleTitle = page
    .locator("a:visible, span:visible, p:visible")
    .filter({ hasText: matcher.title })
    .first();
  await expect(visibleTitle).toBeVisible({ timeout: 15_000 });

  if (matcher.messageIncludes) {
    const visibleMessage = page
      .locator("div:visible, p:visible, span:visible, td:visible")
      .filter({ hasText: matcher.messageIncludes })
      .first();
    await expect(visibleMessage).toBeVisible({ timeout: 15_000 });
  }
}

test.describe("Admissions Notification Runtime Workflow", () => {
  test.describe.configure({ timeout: 600_000, mode: "serial" });

  test.beforeAll(async ({ browser }) => {
    adminContext = await browser.newContext();
    adminPage = await adminContext.newPage();
    adminAuth = await loginAndBootstrap(
      adminPage,
      ADMIN_USERNAME,
      ADMIN_PASSWORD,
      ADMIN_TOTP_SECRET ? { totpSecret: ADMIN_TOTP_SECRET } : undefined,
    );

    discovery = await discoverAdmissionsConfig(adminPage);
    tempOfficer = await createTempOfficerUser(adminPage, discovery.unitId);

    officerContext = await browser.newContext();
    officerPage = await officerContext.newPage();
    officerAuth = await loginAndBootstrap(
      officerPage,
      tempOfficer.username,
      tempOfficer.password,
    );
  });

  test.afterAll(async () => {
    if (adminPage && tempOfficer) {
      await deactivateTempOfficer(adminPage, tempOfficer);
    }

    await officerContext?.close();
    await adminContext?.close();
  });

test("application_created notifies assigned officer and records browser delivery", async () => {
    if (!tempOfficer) throw new Error("Temp officer was not created");

    const draft = await createMinimalDraftAdmission(officerPage, officerAuth.headers, discovery);
    const title = `Có hồ sơ mới: #${draft.profileId}`;
    const message = `Hồ sơ #${draft.profileId}`;

    await waitForNotification(officerPage, {
      title,
      messageIncludes: message,
    });

    await waitForDeliveryUsers(adminPage, {
      event: "application_created",
      sourceType: "admission_profile",
      sourceId: draft.profileId,
      expectedUserIds: [tempOfficer.id],
    });

    await assertNotificationVisibleInInbox(officerPage, {
      title,
      messageIncludes: message,
    });
  });

  test("draft -> submitted notifies assigned officer", async () => {
    if (!tempOfficer) throw new Error("Temp officer was not created");

    const draft = await createMinimalDraftAdmission(officerPage, officerAuth.headers, discovery);
    const version = await hydrateAdmissionProfileForSubmit(
      officerPage,
      officerAuth.headers,
      draft.profileId,
      draft.version,
      draft.citizenId,
    );

    const submitResp = await officerPage.request.post(
      `${API_URL}/api/admissions/${draft.profileId}/submit`,
      {
        headers: officerAuth.headers,
      },
    );
    expect(submitResp.ok()).toBeTruthy();
    const submitBody = await submitResp.json();
    expect(submitBody.status).toBe("submitted");

    const submittedTitle = `Hồ sơ cập nhật trạng thái: #${draft.profileId}`;
    const submittedMessage = `Hồ sơ #${draft.profileId} đã chuyển từ draft sang submitted.`;

    await waitForNotification(officerPage, {
      title: submittedTitle,
      messageIncludes: "draft sang submitted",
    });

    await waitForDeliveryUsers(adminPage, {
      event: "application_status_changed",
      sourceType: "admission_profile",
      sourceId: draft.profileId,
      expectedUserIds: [tempOfficer.id],
    });

    await assertNotificationVisibleInInbox(officerPage, {
      title: submittedTitle,
      messageIncludes: submittedMessage,
    });
  });

  test.fixme("submitted -> approved should notify assigned officer", async () => {
    if (!tempOfficer) throw new Error("Temp officer was not created");

    const draft = await createMinimalDraftAdmission(officerPage, officerAuth.headers, discovery);
    const version = await hydrateAdmissionProfileForSubmit(
      officerPage,
      officerAuth.headers,
      draft.profileId,
      draft.version,
      draft.citizenId,
    );

    const submitResp = await officerPage.request.post(
      `${API_URL}/api/admissions/${draft.profileId}/submit`,
      {
        headers: officerAuth.headers,
      },
    );
    expect(submitResp.ok()).toBeTruthy();

    const profileResp = await adminPage.request.get(`${API_URL}/api/admissions/${draft.profileId}`, {
      headers: adminAuth.headers,
    });
    expect(profileResp.ok()).toBeTruthy();
    const profile = await profileResp.json();

    const approveResp = await adminPage.request.post(
      `${API_URL}/api/admissions/${draft.profileId}/approve`,
      {
        headers: adminAuth.headers,
        data: {
          notes: "Admissions notification runtime test approval",
          version: profile.version ?? version,
        },
      },
    );
    expect(approveResp.ok()).toBeTruthy();
    const approveBody = await approveResp.json();
    expect(approveBody.status).toBe("approved");

    const submittedTitle = `Hồ sơ cập nhật trạng thái: #${draft.profileId}`;
    const approvedMessage = `Hồ sơ #${draft.profileId} đã chuyển từ submitted sang approved.`;
    await waitForNotification(officerPage, {
      title: submittedTitle,
      messageIncludes: "submitted sang approved",
    });

    await assertNotificationVisibleInInbox(officerPage, {
      title: submittedTitle,
      messageIncludes: approvedMessage,
    });
  });

  test.fixme("approved -> confirmed via public flow notifies assigned officer and does not emit new lead_status_changed delivery", async ({ browser }) => {
    if (!tempOfficer) throw new Error("Temp officer was not created");

    const draft = await createMinimalDraftAdmission(officerPage, officerAuth.headers, discovery);
    const version = await hydrateAdmissionProfileForSubmit(
      officerPage,
      officerAuth.headers,
      draft.profileId,
      draft.version,
      draft.citizenId,
    );

    const submitResp = await officerPage.request.post(
      `${API_URL}/api/admissions/${draft.profileId}/submit`,
      {
        headers: officerAuth.headers,
      },
    );
    expect(submitResp.ok()).toBeTruthy();

    const profileResp = await adminPage.request.get(`${API_URL}/api/admissions/${draft.profileId}`, {
      headers: adminAuth.headers,
    });
    expect(profileResp.ok()).toBeTruthy();
    const profile = await profileResp.json();

    const approveResp = await adminPage.request.post(
      `${API_URL}/api/admissions/${draft.profileId}/approve`,
      {
        headers: adminAuth.headers,
        data: {
          notes: "Admissions notification runtime test confirm flow",
          version: profile.version ?? version,
        },
      },
    );
    expect(approveResp.ok()).toBeTruthy();

    const leadStatusBefore = await getDeliveryCount(adminPage, {
      event: "lead_status_changed",
      sourceType: "lead",
      sourceId: draft.leadId,
    });

    const sendConfirmationResp = await adminPage.request.post(
      `${API_URL}/api/admissions/${draft.profileId}/send-confirmation`,
      {
        headers: adminAuth.headers,
      },
    );
    expect(sendConfirmationResp.ok()).toBeTruthy();
    const sendConfirmationBody = await sendConfirmationResp.json();
    const confirmToken = sendConfirmationBody.token_value;
    expect(confirmToken).toBeTruthy();

    const publicContext = await browser.newContext();
    const publicPage = await publicContext.newPage();

    const confirmResp = await publicPage.request.post(
      `${API_URL}/api/admissions/confirm/${confirmToken}`,
      {
        data: {
          last_digits_citizen_id: draft.citizenId.slice(-4),
        },
      },
    );
    expect(confirmResp.ok()).toBeTruthy();
    const confirmBody = await confirmResp.json();
    expect(confirmBody.status).toBe("confirmed");

    await publicContext.close();

    const confirmedTitle = `Hồ sơ cập nhật trạng thái: #${draft.profileId}`;
    const confirmedMessage = `Hồ sơ #${draft.profileId} đã chuyển từ approved sang confirmed.`;

    await waitForNotification(officerPage, {
      title: confirmedTitle,
      messageIncludes: "approved sang confirmed",
    });

    await assertNotificationVisibleInInbox(officerPage, {
      title: confirmedTitle,
      messageIncludes: confirmedMessage,
    });

    const leadStatusAfter = await getDeliveryCount(adminPage, {
      event: "lead_status_changed",
      sourceType: "lead",
      sourceId: draft.leadId,
    });
    expect(leadStatusAfter).toBe(leadStatusBefore);
  });
});
