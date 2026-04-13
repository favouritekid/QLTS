/**
 * E2E Test: CTV Registration + Commission Lifecycle
 *
 * Coverage:
 *   - CTV self-registration → Admin approval → Auto-create user account
 *   - CTV submits lead → Admin approves claim → Lead status triggers commission
 *   - Commission approve → pay → CTV verifies dashboard
 *   - Rejection paths: claim rejection, commission rejection
 *   - Regression cancellation: lead status regress → commission auto-cancelled
 *
 * Chạy:
 *   npx playwright test ctv-commission-workflow --project=e2e-workflow --reporter=list
 *   npx playwright test ctv-commission-workflow --project=e2e-workflow --headed
 *   npx playwright test ctv-commission-workflow -g "Happy path" --project=e2e-workflow
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

const API_URL = process.env.E2E_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Shared state across tests (serial execution within describe)
// ---------------------------------------------------------------------------

let adminHeaders: Record<string, string> = {};
let adminCookies: Cookie[] = [];
let ctvHeaders: Record<string, string> = {};
let ctvCookies: Cookie[] = [];

// CTV data
let ctvCollaboratorId: number;
let ctvCode: string;
let ctvUsername: string;
let ctvTempPassword: string;
const ctvPhone = generatePhone();
const ctvName = `E2E_CTV_${Date.now()}`;

// Pipeline & offering
let triggerStatusId: string;
let initialStatusId: string;
let unitId: number;

// Leads & claims
let leadId1: number;
let claimId1: number;
let leadId2: number;
let claimId2: number;
let leadId3: number;
let claimId3: number;
let leadId4: number;
let claimId4: number;

// Commission
let commissionPolicyId: number;
let commissionRecordId1: number;
let commissionRecordId3: number;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generatePhone(): string {
  const prefixes = ["091", "093", "097", "098", "035", "036", "085", "086"];
  const prefix = prefixes[Math.floor(Math.random() * prefixes.length)];
  const suffix = Math.floor(Math.random() * 10_000_000)
    .toString()
    .padStart(7, "0");
  return prefix + suffix;
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

/**
 * Ensure a CSRF token cookie exists. If not, do a GET to /api/health to obtain one.
 * Returns headers with X-CSRF-Token for subsequent mutation requests.
 */
async function ensureCSRFHeaders(
  page: Page
): Promise<Record<string, string>> {
  let csrf = await getCSRFToken(page);
  if (!csrf) {
    // Any GET request triggers CSRF cookie set by middleware
    const resp = await page.request.get(`${API_URL}/health`);
    csrf = await extractAndAddCookies(page, resp);
  }
  if (!csrf) {
    csrf = await getCSRFToken(page);
  }
  return csrf ? { "X-CSRF-Token": csrf } : {};
}

async function loginViaAPI(
  page: Page,
  username: string,
  password: string,
  opts?: { totpSecret?: string }
): Promise<Record<string, string>> {
  // Outer retry loop: handles rate limiting (429) and TOTP collision (restart from scratch)
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
        console.log(`MFA failed for ${username} (${mfaResp.status()}), waiting 31s and retrying login...`);
        await new Promise((r) => setTimeout(r, 31_000));
        continue; // restart from login
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
 * Submit a lead via CTV and return { leadId, claimId }.
 * Caller must be logged in as CTV before calling.
 */
async function ctvSubmitLead(
  page: Page,
  headers: Record<string, string>,
  phone: string,
  name: string
): Promise<{ leadId: number; claimId: number }> {
  const resp = await page.request.post(`${API_URL}/api/ctv/leads/submit`, {
    headers,
    data: {
      lead_data: { full_name: name, phone, notes: "E2E commission test" },
    },
  });
  expect(resp.ok() || resp.status() === 201, `CTV submit lead: ${resp.status()}`).toBeTruthy();
  const claim = await resp.json();
  expect(claim.status).toBe("pending");
  return { leadId: claim.lead_id, claimId: claim.id };
}

/**
 * Admin approves a lead claim. Caller must be logged in as admin.
 */
async function adminApproveClaim(
  page: Page,
  headers: Record<string, string>,
  claimId: number
): Promise<void> {
  const resp = await page.request.post(
    `${API_URL}/api/collaborators/claims/${claimId}/review`,
    { headers, data: { status: "approved" } }
  );
  expect(resp.ok(), `Approve claim ${claimId}: ${resp.status()}`).toBeTruthy();
  const claim = await resp.json();
  expect(claim.status).toBe("approved");
}

/**
 * Admin adds a consultation to set status on a lead.
 * Returns the consultation ID for subsequent updates.
 */
async function adminAddConsultation(
  page: Page,
  headers: Record<string, string>,
  leadId: number,
  statusId: string,
  notes = "E2E test consultation"
): Promise<number> {
  const resp = await page.request.post(
    `${API_URL}/api/leads/${leadId}/consultations`,
    {
      headers,
      data: { status_id: statusId, method: "phone", notes },
    }
  );
  if (!resp.ok() && resp.status() !== 201) {
    const body = (await resp.text()).slice(0, 500);
    throw new Error(`Add consultation to lead ${leadId}: ${resp.status()} ${body}`);
  }
  const consultation = await resp.json();
  return consultation.id;
}

/**
 * Admin updates an existing consultation's status (Path 3 → triggers commission check).
 * PUT /api/leads/{lead_id}/consultations/{consultation_id}
 */
async function adminUpdateConsultation(
  page: Page,
  headers: Record<string, string>,
  leadId: number,
  consultationId: number,
  statusId: string,
  notes = "E2E status change"
): Promise<void> {
  const resp = await page.request.put(
    `${API_URL}/api/leads/${leadId}/consultations/${consultationId}`,
    {
      headers,
      data: { status_id: statusId, method: "phone", notes },
    }
  );
  if (!resp.ok()) {
    const body = (await resp.text()).slice(0, 500);
    throw new Error(
      `Update consultation ${consultationId} on lead ${leadId} to ${statusId}: ${resp.status()} ${body}`
    );
  }
}

/**
 * Wait for commission to be created after status change (async post-commit).
 * Filters by collaborator + status + optionally lead_id.
 * Returns the commission record or null.
 */
async function waitForCommission(
  page: Page,
  headers: Record<string, string>,
  collaboratorId: number,
  status: string,
  leadId?: number,
  maxWaitMs = 5000
): Promise<{ id: number; lead_id: number; amount: string; status: string } | null> {
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    const resp = await page.request.get(
      `${API_URL}/api/admin/commissions?collaborator_id=${collaboratorId}&status=${status}`,
      { headers }
    );
    if (resp.ok()) {
      const body = await resp.json();
      const records = body.records || body.commissions || body.items || [];
      if (Array.isArray(records) && records.length > 0) {
        if (leadId) {
          // Filter by lead_id to find the specific commission
          const match = records.find(
            (r: { lead_id: number }) => r.lead_id === leadId
          );
          if (match) return match;
        } else {
          return records[records.length - 1]; // latest
        }
      }
    }
    await page.waitForTimeout(1000);
  }
  return null;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("CTV Commission Workflow", () => {
  test.describe.configure({ timeout: 300_000, mode: "serial" });

  // =========================================================================
  // TEST 1: Happy Path
  // =========================================================================
  test("Happy path: Register → Approve → Lead → Commission → Pay", async ({
    page,
  }) => {
    // --- Step 1: Admin login + fetch pipeline & offerings ---
    await test.step("Admin login + discover pipeline statuses", async () => {
      adminHeaders = await loginViaAPI(page, ADMIN_USERNAME, ADMIN_PASSWORD, {
        totpSecret: ADMIN_TOTP_SECRET,
      });
      adminCookies = await page.context().cookies();
      console.log("Admin logged in (TOTP, session saved)");

      // Fetch pipeline statuses
      const pipelineResp = await page.request.get(`${API_URL}/api/pipeline/all`);
      expect(pipelineResp.ok()).toBeTruthy();
      const pipeline = await pipelineResp.json();
      const statuses = pipeline.statuses;
      expect(statuses.length).toBeGreaterThanOrEqual(2);

      initialStatusId = statuses[0].id;
      // Pick a trigger status that isn't the initial one and is selectable
      const trigger = statuses.find(
        (s: { id: string; selectable_mode?: string }) =>
          s.id !== initialStatusId && s.selectable_mode !== "system"
      );
      expect(trigger, "Need at least 2 selectable pipeline statuses").toBeTruthy();
      triggerStatusId = trigger!.id;

      // Fetch an organization unit for CTV registration
      const unitsResp = await page.request.get(
        `${API_URL}/api/organization-units`
      );
      expect(unitsResp.ok()).toBeTruthy();
      const units = await unitsResp.json();
      expect(units.length).toBeGreaterThan(0);
      unitId = units[0].id;

      console.log(
        `Pipeline: initial=${initialStatusId}, trigger=${triggerStatusId}, unitId=${unitId}`
      );
    });

    // --- Step 2: Create commission policy (fixed 500K) ---
    await test.step("Create commission policy (fixed 500,000 VND)", async () => {
      const today = new Date().toISOString().split("T")[0];
      const resp = await page.request.post(
        `${API_URL}/api/admin/commission-policies`,
        {
          headers: adminHeaders,
          data: {
            name: `E2E_Policy_${Date.now()}`,
            description: "E2E test commission policy - fixed 500K",
            trigger_status_id: triggerStatusId,
            calculation_type: "fixed",
            fixed_amount: 500000,
            effective_from: today,
            is_active: true,
          },
        }
      );
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      const policy = await resp.json();
      commissionPolicyId = policy.id;
      expect(policy.trigger_status_id).toBe(triggerStatusId);
      console.log(`Commission policy created: id=${commissionPolicyId}, trigger=${triggerStatusId}`);
    });

    // --- Step 3: CTV self-register (public, no auth) ---
    await test.step("CTV self-register", async () => {
      // Public endpoint — need CSRF token but no auth
      // Use admin cookies which already have csrf_token set
      const csrfHeaders = await ensureCSRFHeaders(page);
      const resp = await page.request.post(`${API_URL}/api/ctv-register`, {
        headers: csrfHeaders,
        data: {
          full_name: ctvName,
          phone: ctvPhone,
          email: `e2e_ctv_${Date.now()}@example.com`,
          notes: "E2E commission workflow test",
          unit_id: unitId,
        },
      });
      if (!resp.ok() && resp.status() !== 201) {
        const body = (await resp.text()).slice(0, 300);
        throw new Error(`CTV register failed: ${resp.status()} ${body}`);
      }
      const body = await resp.json();
      ctvCode = body.code;
      expect(body.status).toBe("pending");
      console.log(`CTV registered: code=${ctvCode}, phone=${ctvPhone}`);
    });

    // --- Step 4: Admin finds & approves CTV ---
    await test.step("Admin approves CTV registration", async () => {
      // Restore admin session
      adminHeaders = await restoreCookies(page, adminCookies);

      // Search for the CTV by phone
      const searchResp = await page.request.get(
        `${API_URL}/api/collaborators?status=pending&search=${ctvPhone}`,
        { headers: adminHeaders }
      );
      expect(searchResp.ok()).toBeTruthy();
      const searchBody = await searchResp.json();
      const collaborators = searchBody.collaborators || searchBody.items || searchBody;
      expect(collaborators.length).toBeGreaterThan(0);
      ctvCollaboratorId = collaborators[0].id;

      // Approve
      const approveResp = await page.request.post(
        `${API_URL}/api/collaborators/${ctvCollaboratorId}/approve`,
        { headers: adminHeaders }
      );
      expect(approveResp.ok()).toBeTruthy();
      const approveBody = await approveResp.json();
      expect(approveBody.account_created).toBe(true);
      ctvUsername = approveBody.username;
      ctvTempPassword = approveBody.temp_password;
      expect(ctvUsername).toBeTruthy();
      expect(ctvTempPassword).toBeTruthy();

      // Save admin cookies again (may have rotated CSRF)
      adminCookies = await page.context().cookies();
      console.log(
        `CTV approved: id=${ctvCollaboratorId}, username=${ctvUsername}, account_created=true`
      );
    });

    // --- Step 5: CTV login with temp credentials ---
    await test.step("CTV login with temp credentials", async () => {
      ctvHeaders = await loginViaAPI(page, ctvUsername, ctvTempPassword);
      ctvCookies = await page.context().cookies();

      // Verify CTV profile
      const profileResp = await page.request.get(`${API_URL}/api/ctv/profile`, {
        headers: ctvHeaders,
      });
      expect(profileResp.ok()).toBeTruthy();
      const profile = await profileResp.json();
      expect(profile.status).toBe("active");
      console.log(`CTV logged in: profile.status=${profile.status}`);
    });

    // --- Step 6: CTV checks phone & submits lead ---
    await test.step("CTV submits lead #1", async () => {
      const leadPhone = generatePhone();

      // Check phone availability
      const checkResp = await page.request.get(
        `${API_URL}/api/ctv/leads/check-phone?phone=${leadPhone}`,
        { headers: ctvHeaders }
      );
      expect(checkResp.ok()).toBeTruthy();
      const checkBody = await checkResp.json();
      expect(checkBody.available).toBe(true);

      // Submit lead
      const result = await ctvSubmitLead(
        page,
        ctvHeaders,
        leadPhone,
        `E2E_Lead1_${Date.now()}`
      );
      leadId1 = result.leadId;
      claimId1 = result.claimId;

      // Verify lead appears in CTV's lead list
      const leadsResp = await page.request.get(`${API_URL}/api/ctv/leads`, {
        headers: ctvHeaders,
      });
      expect(leadsResp.ok()).toBeTruthy();

      console.log(`Lead #1 submitted: leadId=${leadId1}, claimId=${claimId1}`);
    });

    // --- Step 7: Admin approves lead claim ---
    await test.step("Admin approves lead claim #1", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      await adminApproveClaim(page, adminHeaders, claimId1);
      adminCookies = await page.context().cookies();
      console.log(`Claim #1 approved: claimId=${claimId1}`);
    });

    // --- Step 8: Admin adds consultation + updates to trigger status ---
    let consultationId1: number;
    await test.step("Admin sets initial consultation + progresses to trigger", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // Add initial consultation (sets lead status)
      consultationId1 = await adminAddConsultation(
        page,
        adminHeaders,
        leadId1,
        initialStatusId,
        "E2E: initial consultation"
      );
      console.log(`Lead #1 initial consultation: id=${consultationId1}, status=${initialStatusId}`);

      // Update consultation status to trigger (Path 3 → commission check)
      await adminUpdateConsultation(
        page,
        adminHeaders,
        leadId1,
        consultationId1,
        triggerStatusId,
        "E2E: progress to trigger status"
      );
      adminCookies = await page.context().cookies();
      console.log(`Lead #1 consultation updated to trigger: ${triggerStatusId}`);
    });

    // --- Step 9: Verify commission created ---
    await test.step("Verify commission created (pending)", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // Wait for async commission creation (post-commit callback)
      const commission = await waitForCommission(
        page,
        adminHeaders,
        ctvCollaboratorId,
        "pending",
        leadId1
      );
      expect(commission, "Commission should be created after lead reaches trigger status").toBeTruthy();
      commissionRecordId1 = commission!.id;

      expect(parseFloat(commission!.amount)).toBe(500000);
      expect(commission!.status).toBe("pending");

      adminCookies = await page.context().cookies();
      console.log(
        `Commission created: id=${commissionRecordId1}, amount=${commission!.amount}, status=${commission!.status}`
      );
    });

    // --- Step 10: Admin approves commission ---
    await test.step("Admin approves commission", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.post(
        `${API_URL}/api/admin/commissions/${commissionRecordId1}/approve`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      const record = await resp.json();
      expect(record.status).toBe("approved");

      adminCookies = await page.context().cookies();
      console.log(`Commission approved: id=${commissionRecordId1}`);
    });

    // --- Step 11: Admin marks commission as paid ---
    await test.step("Admin marks commission as paid", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.post(
        `${API_URL}/api/admin/commissions/${commissionRecordId1}/pay`,
        {
          headers: adminHeaders,
          data: { payment_reference: `E2E_PAY_${Date.now()}` },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const record = await resp.json();
      expect(record.status).toBe("paid");
      expect(record.payment_reference).toBeTruthy();

      adminCookies = await page.context().cookies();
      console.log(`Commission paid: id=${commissionRecordId1}, ref=${record.payment_reference}`);
    });

    // --- Step 12: CTV verifies commission in dashboard ---
    await test.step("CTV verifies commission in dashboard", async () => {
      ctvHeaders = await restoreCookies(page, ctvCookies);

      const resp = await page.request.get(`${API_URL}/api/ctv/commissions`, {
        headers: ctvHeaders,
      });
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      const records = body.records || body.commissions || body.items || [];
      expect(Array.isArray(records)).toBeTruthy();

      const paidRecord = records.find(
        (r: { id: number; status: string }) =>
          r.id === commissionRecordId1 && r.status === "paid"
      );
      expect(paidRecord, "CTV should see paid commission").toBeTruthy();
      expect(parseFloat(paidRecord.amount)).toBe(500000);

      ctvCookies = await page.context().cookies();
      console.log(`CTV sees paid commission: id=${paidRecord.id}, amount=${paidRecord.amount}`);
    });

    // --- Step 13: CTV checks commission stats ---
    await test.step("CTV verifies commission stats", async () => {
      ctvHeaders = await restoreCookies(page, ctvCookies);

      const statsResp = await page.request.get(
        `${API_URL}/api/ctv/commissions/stats`,
        { headers: ctvHeaders }
      );
      expect(statsResp.ok()).toBeTruthy();
      const stats = await statsResp.json();
      expect(parseFloat(stats.total_paid)).toBeGreaterThanOrEqual(500000);

      const ctvStatsResp = await page.request.get(`${API_URL}/api/ctv/stats`, {
        headers: ctvHeaders,
      });
      expect(ctvStatsResp.ok()).toBeTruthy();
      const ctvStats = await ctvStatsResp.json();
      expect(ctvStats.total_leads).toBeGreaterThanOrEqual(1);

      ctvCookies = await page.context().cookies();
      console.log(
        `CTV stats: total_paid=${stats.total_paid}, total_leads=${ctvStats.total_leads}, valid=${ctvStats.valid_leads}`
      );
    });
  });

  // =========================================================================
  // TEST 2: Rejection Paths
  // =========================================================================
  test("Rejection paths: claim rejected + commission rejected", async ({
    page,
  }) => {
    // --- Step 1: CTV submits lead #2 ---
    await test.step("CTV submits lead #2", async () => {
      ctvHeaders = await restoreCookies(page, ctvCookies);

      const result = await ctvSubmitLead(
        page,
        ctvHeaders,
        generatePhone(),
        `E2E_Lead2_${Date.now()}`
      );
      leadId2 = result.leadId;
      claimId2 = result.claimId;

      ctvCookies = await page.context().cookies();
      console.log(`Lead #2 submitted: leadId=${leadId2}, claimId=${claimId2}`);
    });

    // --- Step 2: Admin rejects lead claim #2 ---
    await test.step("Admin rejects lead claim #2", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.post(
        `${API_URL}/api/collaborators/claims/${claimId2}/review`,
        {
          headers: adminHeaders,
          data: {
            status: "rejected",
            rejection_reason: "E2E test: duplicate lead for rejection path test",
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const claim = await resp.json();
      expect(claim.status).toBe("rejected");

      // Verify lead attribution removed (referrer_id should be null)
      const leadResp = await page.request.get(
        `${API_URL}/api/leads/${leadId2}`,
        { headers: adminHeaders }
      );
      if (leadResp.ok()) {
        const lead = await leadResp.json();
        expect(lead.referrer_id).toBeFalsy();
        console.log(`Claim #2 rejected: lead.referrer_id=${lead.referrer_id} (attribution removed)`);
      }

      adminCookies = await page.context().cookies();
    });

    // --- Step 3: CTV submits lead #3 → Admin approves → trigger commission ---
    await test.step("CTV submits lead #3 → full flow → commission pending", async () => {
      // CTV submits lead #3
      ctvHeaders = await restoreCookies(page, ctvCookies);
      const result = await ctvSubmitLead(
        page,
        ctvHeaders,
        generatePhone(),
        `E2E_Lead3_${Date.now()}`
      );
      leadId3 = result.leadId;
      claimId3 = result.claimId;
      ctvCookies = await page.context().cookies();

      // Admin approves claim + adds consultation + progresses to trigger
      adminHeaders = await restoreCookies(page, adminCookies);
      await adminApproveClaim(page, adminHeaders, claimId3);

      // Add initial consultation
      const consultId3 = await adminAddConsultation(page, adminHeaders, leadId3, initialStatusId, "E2E: initial");

      // Update consultation to trigger status (Path 3 → commission check)
      await adminUpdateConsultation(page, adminHeaders, leadId3, consultId3, triggerStatusId, "E2E: trigger");

      // Wait for commission
      const commission = await waitForCommission(
        page,
        adminHeaders,
        ctvCollaboratorId,
        "pending",
        leadId3
      );
      expect(commission, "Commission should be created for lead #3").toBeTruthy();
      commissionRecordId3 = commission!.id;

      adminCookies = await page.context().cookies();
      console.log(
        `Lead #3 full flow: leadId=${leadId3}, commissionId=${commissionRecordId3}, status=${commission!.status}`
      );
    });

    // --- Step 4: Admin rejects commission ---
    await test.step("Admin rejects commission for lead #3", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.post(
        `${API_URL}/api/admin/commissions/${commissionRecordId3}/reject`,
        {
          headers: adminHeaders,
          data: {
            rejection_reason: "E2E test: commission rejected for rejection path test",
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const record = await resp.json();
      expect(record.status).toBe("rejected");
      expect(record.rejection_reason).toContain("E2E test");

      adminCookies = await page.context().cookies();
      console.log(`Commission rejected: id=${commissionRecordId3}, status=${record.status}`);
    });
  });

  // =========================================================================
  // TEST 3: Regression Cancellation
  // =========================================================================
  test("Regression cancellation: lead status regress → commission auto-cancelled", async ({
    page,
  }) => {
    let consultationId4: number;
    // --- Step 1: CTV submits lead #4 → Admin approves claim ---
    await test.step("CTV submits lead #4 → Admin approves claim", async () => {
      ctvHeaders = await restoreCookies(page, ctvCookies);
      const result = await ctvSubmitLead(
        page,
        ctvHeaders,
        generatePhone(),
        `E2E_Lead4_${Date.now()}`
      );
      leadId4 = result.leadId;
      claimId4 = result.claimId;
      ctvCookies = await page.context().cookies();

      // Admin approves + sets initial status
      adminHeaders = await restoreCookies(page, adminCookies);
      await adminApproveClaim(page, adminHeaders, claimId4);

      // Add initial consultation
      consultationId4 = await adminAddConsultation(page, adminHeaders, leadId4, initialStatusId, "E2E: initial");
      adminCookies = await page.context().cookies();

      console.log(`Lead #4: leadId=${leadId4}, claimId=${claimId4}, consultId=${consultationId4} (approved, initial status set)`);
    });

    // --- Step 2: Admin progresses lead to trigger → commission created ---
    let regressionCommissionId: number;
    await test.step("Admin progresses lead #4 to trigger status", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // Update consultation to trigger status (Path 3 → commission check)
      await adminUpdateConsultation(page, adminHeaders, leadId4, consultationId4, triggerStatusId, "E2E: trigger");

      // Wait for commission creation
      const commission = await waitForCommission(
        page,
        adminHeaders,
        ctvCollaboratorId,
        "pending",
        leadId4
      );
      expect(commission, "Commission should be created for lead #4").toBeTruthy();
      regressionCommissionId = commission!.id;

      adminCookies = await page.context().cookies();
      console.log(
        `Lead #4 progressed: commissionId=${regressionCommissionId}, status=${commission!.status}`
      );
    });

    // --- Step 3: Admin regresses lead status → commission auto-cancelled ---
    await test.step("Admin regresses lead #4 → commission auto-cancelled", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // Regress lead back to initial status via consultation update (Path 3)
      await adminUpdateConsultation(page, adminHeaders, leadId4, consultationId4, initialStatusId, "E2E: regress status");

      // Wait for cancellation (async post-commit)
      await page.waitForTimeout(3000);

      // Check commission status
      const resp = await page.request.get(
        `${API_URL}/api/admin/commissions/${regressionCommissionId}`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      const record = await resp.json();
      expect(record.status).toBe("cancelled");
      expect(record.cancellation_reason).toBeTruthy();

      adminCookies = await page.context().cookies();
      console.log(
        `Commission auto-cancelled: id=${regressionCommissionId}, ` +
          `status=${record.status}, reason="${record.cancellation_reason}"`
      );
    });
  });

  // =========================================================================
  // Cleanup log
  // =========================================================================
  test.afterAll(() => {
    console.log("\n========== CTV COMMISSION WORKFLOW RESULTS ==========");
    console.log(`CTV: phone=${ctvPhone}, code=${ctvCode}, collaboratorId=${ctvCollaboratorId}`);
    console.log(`Policy: id=${commissionPolicyId}`);
    console.log(`Lead #1: id=${leadId1}, claim=${claimId1}, commission=${commissionRecordId1} (paid)`);
    console.log(`Lead #2: id=${leadId2}, claim=${claimId2} (claim rejected)`);
    console.log(`Lead #3: id=${leadId3}, claim=${claimId3}, commission=${commissionRecordId3} (rejected)`);
    console.log(`Lead #4: id=${leadId4}, claim=${claimId4} (regression cancelled)`);
    console.log("=====================================================\n");
  });
});
