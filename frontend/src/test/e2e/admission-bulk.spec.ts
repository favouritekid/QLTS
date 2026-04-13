/**
 * E2E Test: Admission Bulk Actions + Export
 *
 * Coverage:
 *   - Bulk approve (2 profiles)
 *   - Bulk reject (1 profile)
 *   - Bulk assign (1 profile to officer)
 *   - Export CSV
 *
 * Project: e2e-workflow (login inline with MFA)
 *
 * Chạy:
 *   npx playwright test admission-bulk --project=e2e-workflow --reporter=list
 */

import { test, expect, type Page, type Cookie } from "@playwright/test";
import * as OTPAuth from "otpauth";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "Admin@12345";
const ADMIN_TOTP_SECRET =
  process.env.E2E_ADMIN_TOTP_SECRET || "WUUT7KVVWRFVMVPZ7K6NGOKL2VYPPFH5";

const OFFICER_USERNAME = process.env.E2E_OFFICER_USERNAME || "vothuhien";
const OFFICER_PASSWORD = process.env.E2E_OFFICER_PASSWORD || "@Matkhau123!";

const API_URL = process.env.E2E_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Shared state across tests (serial execution)
// ---------------------------------------------------------------------------

let adminHeaders: Record<string, string> = {};
let adminCookies: Cookie[] = [];
let officerHeaders: Record<string, string> = {};
let officerCookies: Cookie[] = [];

// Discovery
let unitId: number;
let offeringId: number;
let admissionMethodId: number;
let initialStatusId: string;
let officerId: number;

// Test data: 3 profiles created in beforeAll, used across tests
const profileIds: number[] = [];

// ---------------------------------------------------------------------------
// Helpers (self-contained, no cross-file imports)
// ---------------------------------------------------------------------------

function generatePhone(): string {
  const prefixes = ["091", "093", "097", "098", "035", "036", "085", "086"];
  const prefix = prefixes[Math.floor(Math.random() * prefixes.length)];
  const suffix = Math.floor(Math.random() * 10_000_000)
    .toString()
    .padStart(7, "0");
  return prefix + suffix;
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

async function loginViaAPI(
  page: Page,
  username: string,
  password: string,
  opts?: { totpSecret?: string }
): Promise<Record<string, string>> {
  for (let outerAttempt = 0; outerAttempt < 3; outerAttempt++) {
    await page.context().clearCookies();

    const loginResp = await page.request.post(`${API_URL}/api/auth/login`, {
      form: { username, password },
    });
    if (loginResp.status() === 429) {
      console.log(`Login rate limited for ${username}, waiting 65s (attempt ${outerAttempt + 1})...`);
      await new Promise((r) => setTimeout(r, 65_000));
      continue;
    }
    if (!loginResp.ok()) {
      const body = (await loginResp.text()).slice(0, 300);
      throw new Error(`Login failed for ${username}: ${loginResp.status()} ${body}`);
    }

    const loginBody = await loginResp.json();
    let authResp = loginResp;

    if (loginBody.mfa_required) {
      if (!opts?.totpSecret) {
        throw new Error(`MFA required for ${username} but no TOTP secret provided`);
      }
      const mfaResp = await page.request.post(`${API_URL}/api/auth/verify-mfa`, {
        data: { mfa_token: loginBody.mfa_token, code: generateTOTP(opts.totpSecret) },
      });
      if (!mfaResp.ok()) {
        console.log(`MFA failed for ${username} (${mfaResp.status()}), waiting 31s...`);
        await new Promise((r) => setTimeout(r, 31_000));
        continue;
      }
      authResp = mfaResp;
    }

    const csrf = await extractAndAddCookies(page, authResp);
    return csrf ? { "X-CSRF-Token": csrf } : {};
  }
  throw new Error(`Login failed for ${username} after 3 attempts`);
}

async function restoreCookies(
  page: Page,
  cookies: Cookie[]
): Promise<Record<string, string>> {
  await page.context().clearCookies();
  if (cookies.length > 0) {
    await page.context().addCookies(cookies);
  }
  const csrf = await getCSRFToken(page);
  return csrf ? { "X-CSRF-Token": csrf } : {};
}

/**
 * Create a lead + admission profile ready for submission.
 */
async function createAndSubmitProfile(
  page: Page,
  headers: Record<string, string>,
  opts: { offeringId: number; admissionMethodId: number; initialStatusId: string }
): Promise<number> {
  const phone = generatePhone();
  const citizenId = generateCitizenId();
  const name = `E2E_Bulk_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;

  // Create lead
  const leadResp = await page.request.post(`${API_URL}/api/leads`, {
    headers,
    data: { full_name: name, phone, source: "walk_in", offering_id: opts.offeringId },
  });
  const leadId = (await leadResp.json()).id;

  // Consultation
  await page.request.post(`${API_URL}/api/leads/${leadId}/consultations`, {
    headers,
    data: { status_id: opts.initialStatusId, method: "phone", notes: "Bulk E2E test" },
  });

  // Create profile
  const profileResp = await page.request.post(`${API_URL}/api/admissions`, {
    headers,
    data: { lead_id: leadId, admission_method_id: opts.admissionMethodId },
  });
  const profile = await profileResp.json();
  const profileId = profile.id;

  // Fill personal info
  const allowedSubjects: string[] = profile.applied_rules?.allowed_subject_codes || [];
  const subjectScores: Record<string, number> = {};
  for (const subj of allowedSubjects.slice(0, 3)) {
    subjectScores[subj] = 7 + Math.random() * 3;
  }

  await page.request.put(`${API_URL}/api/admissions/${profileId}`, {
    headers,
    data: {
      version: profile.version,
      citizen_id: citizenId,
      gender: "female",
      dob: "2002-03-15",
      nationality: "Viet Nam",
      ethnicity: "Kinh",
      place_of_birth: "Ha Noi",
      family_info: [
        {
          relationship: "Cha",
          full_name: "Nguyen Van C",
          phone: "0901234569",
          occupation: "Cong chuc",
          is_primary_guardian: true,
        },
      ],
      academic_history: [
        { school_name: "THPT Le Hong Phong", year_from: 2020, year_to: 2023, gpa: 8.0, graduation_type: "THPT" },
      ],
      admission_scores: { subject_scores: subjectScores, gpa: 8.0 },
    },
  });

  // Upload mandatory docs
  const getResp = await page.request.get(`${API_URL}/api/admissions/${profileId}`);
  const updatedProfile = await getResp.json();
  const missingDocs = (updatedProfile.documents_checklist || []).filter(
    (d: { is_mandatory: boolean; status: string }) =>
      d.is_mandatory && d.status === "missing"
  );
  for (const doc of missingDocs) {
    await page.request.post(
      `${API_URL}/api/admissions/${profileId}/documents/${doc.code}/upload`,
      {
        headers,
        multipart: {
          file: {
            name: `${doc.code}.pdf`,
            mimeType: "application/pdf",
            buffer: Buffer.from(`%PDF-1.4\n%%EOF\n% Bulk E2E: ${doc.code}`),
          },
          actual_submission_format: "photo",
        },
      }
    );
  }

  // Submit
  const submitResp = await page.request.post(`${API_URL}/api/admissions/${profileId}/submit`, {
    headers,
  });
  const submitBody = await submitResp.json();
  if (submitBody.status !== "submitted") {
    console.log(
      `Submit failed for ${profileId}: ${JSON.stringify(submitBody.validation_errors || submitBody).slice(0, 300)}`
    );
  }
  expect(submitBody.status).toBe("submitted");
  console.log(`Profile ${profileId} submitted for bulk test`);
  return profileId;
}

// ---------------------------------------------------------------------------
// Test Suite
// ---------------------------------------------------------------------------

test.describe("Admission Bulk Actions + Export", () => {
  test.describe.configure({ timeout: 600_000, mode: "serial" });

  // =========================================================================
  // Setup: login + discover config + create 3 submitted profiles
  // =========================================================================
  test("Setup: login, discover config, create 3 submitted profiles", async ({ page }) => {
    // Admin login
    await test.step("Admin login", async () => {
      adminHeaders = await loginViaAPI(page, ADMIN_USERNAME, ADMIN_PASSWORD, {
        totpSecret: ADMIN_TOTP_SECRET,
      });
      adminCookies = await page.context().cookies();
      console.log("Admin logged in");
    });

    // Officer login
    await test.step("Officer login", async () => {
      officerHeaders = await loginViaAPI(page, OFFICER_USERNAME, OFFICER_PASSWORD);
      officerCookies = await page.context().cookies();
      console.log("Officer logged in");
    });

    // Discover config
    await test.step("Discover config", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const pipelineResp = await page.request.get(`${API_URL}/api/pipeline/all`);
      initialStatusId = (await pipelineResp.json()).statuses[0].id;

      const unitsResp = await page.request.get(`${API_URL}/api/organization-units`);
      unitId = (await unitsResp.json())[0]?.id;

      const offeringsResp = await page.request.get(
        `${API_URL}/api/program-offerings?is_active=true&limit=1`
      );
      offeringId = (await offeringsResp.json())[0].id;

      const methodsResp = await page.request.get(
        `${API_URL}/api/admission-config/methods?active_only=true`
      );
      const methodsBody = await methodsResp.json();
      const methods = methodsBody.methods || methodsBody;
      admissionMethodId = methods[0].id;

      // Discover officer's user ID for bulk assign test
      const usersResp = await page.request.get(
        `${API_URL}/api/users?role=officer&limit=5`,
        { headers: adminHeaders }
      );
      if (usersResp.ok()) {
        const usersBody = await usersResp.json();
        const users = usersBody.users || usersBody;
        if (Array.isArray(users) && users.length > 0) {
          officerId = users[0].id;
        }
      }

      console.log(
        `Config: unit=${unitId}, offering=${offeringId}, method=${admissionMethodId}, status=${initialStatusId}, officerId=${officerId}`
      );
    });

    // Create 3 submitted profiles
    await test.step("Create 3 submitted profiles", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      for (let i = 0; i < 3; i++) {
        const pid = await createAndSubmitProfile(page, officerHeaders, {
          offeringId,
          admissionMethodId,
          initialStatusId,
        });
        profileIds.push(pid);
        console.log(`Created profile ${i + 1}/3: id=${pid}`);
      }
      console.log(`All 3 profiles created: ${profileIds.join(", ")}`);
    });
  });

  // =========================================================================
  // Test 1: Bulk approve
  // =========================================================================
  test("Bulk approve: approve 2 profiles simultaneously", async ({ page }) => {
    adminHeaders = await restoreCookies(page, adminCookies);

    expect(profileIds.length).toBeGreaterThanOrEqual(2);
    const idsToApprove = [profileIds[0], profileIds[1]];

    // Fetch current versions for optimistic locking
    const items = [];
    for (const pid of idsToApprove) {
      const profile = await (await page.request.get(`${API_URL}/api/admissions/${pid}`, { headers: adminHeaders })).json();
      items.push({ profile_id: pid, version: profile.version });
    }

    const resp = await page.request.post(`${API_URL}/api/admissions/bulk/approve`, {
      headers: adminHeaders,
      data: { items, notes: "Bulk approve E2E test" },
    });
    const bulkApproveBody = await resp.text();
    console.log(`Bulk approve response: ${resp.status()} ${bulkApproveBody.slice(0, 500)}`);
    expect(resp.ok()).toBeTruthy();
    const body = JSON.parse(bulkApproveBody);
    expect(body.success_count).toBe(2);
    console.log(`Bulk approve: success_count=${body.success_count}, failed=${body.failed_count ?? 0}`);

    // Verify both profiles are now approved
    for (const pid of idsToApprove) {
      const profile = await (await page.request.get(`${API_URL}/api/admissions/${pid}`)).json();
      expect(profile.status).toBe("approved");
      console.log(`  Profile ${pid}: status=${profile.status}`);
    }
  });

  // =========================================================================
  // Test 2: Bulk reject
  // =========================================================================
  test("Bulk reject: reject 1 profile with reason", async ({ page }) => {
    adminHeaders = await restoreCookies(page, adminCookies);

    expect(profileIds.length).toBeGreaterThanOrEqual(3);
    const idsToReject = [profileIds[2]];

    // Fetch current versions for optimistic locking
    const rejectItems = [];
    for (const pid of idsToReject) {
      const profile = await (await page.request.get(`${API_URL}/api/admissions/${pid}`, { headers: adminHeaders })).json();
      rejectItems.push({ profile_id: pid, version: profile.version });
    }

    const resp = await page.request.post(`${API_URL}/api/admissions/bulk/reject`, {
      headers: adminHeaders,
      data: {
        items: rejectItems,
        reason: "Hồ sơ không đáp ứng điều kiện xét tuyển theo tiêu chí của đơn vị",
      },
    });
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    console.log(
      `Bulk reject: success_count=${body.success_count}, failed=${body.failed_count ?? 0}`
    );

    // Verify profile is rejected
    const profile = await (
      await page.request.get(`${API_URL}/api/admissions/${profileIds[2]}`)
    ).json();
    expect(profile.status).toBe("rejected");
    console.log(`  Profile ${profileIds[2]}: status=${profile.status}`);
  });

  // =========================================================================
  // Test 3: Bulk assign
  // =========================================================================
  test("Bulk assign: assign profile to officer", async ({ page }) => {
    adminHeaders = await restoreCookies(page, adminCookies);

    if (!officerId) {
      console.log("No officer ID discovered — skipping bulk assign test");
      return;
    }

    // Create a fresh profile for assignment (existing ones are approved/rejected)
    officerHeaders = await restoreCookies(page, officerCookies);
    const assignPid = await createAndSubmitProfile(page, officerHeaders, {
      offeringId,
      admissionMethodId,
      initialStatusId,
    });
    adminHeaders = await restoreCookies(page, adminCookies);

    const resp = await page.request.post(`${API_URL}/api/admissions/bulk/assign`, {
      headers: adminHeaders,
      data: { profile_ids: [assignPid], officer_id: officerId },
    });
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    console.log(
      `Bulk assign: success_count=${body.success_count}, officer_id=${officerId}`
    );

    // Verify assignment
    const profile = await (
      await page.request.get(`${API_URL}/api/admissions/${assignPid}`)
    ).json();
    expect(profile.assigned_officer_id).toBe(officerId);
    console.log(`  Profile ${assignPid}: assigned_officer_id=${profile.assigned_officer_id}`);
  });

  // =========================================================================
  // Test 4: Export CSV
  // =========================================================================
  test("Export CSV: GET /api/admissions/export returns non-empty CSV", async ({ page }) => {
    adminHeaders = await restoreCookies(page, adminCookies);

    const resp = await page.request.get(`${API_URL}/api/admissions/export`, {
      headers: adminHeaders,
    });
    expect(resp.ok()).toBeTruthy();

    const contentType = resp.headers()["content-type"] || "";
    const isCSV =
      contentType.includes("text/csv") ||
      contentType.includes("application/octet-stream") ||
      contentType.includes("application/csv") ||
      contentType.includes("text/plain");
    expect(isCSV).toBe(true);

    const body = await resp.body();
    expect(body.length).toBeGreaterThan(0);
    console.log(
      `Export CSV: status=${resp.status()}, content-type=${contentType}, size=${body.length} bytes`
    );
  });
});
