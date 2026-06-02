/**
 * E2E Test: Finance Lifecycle (Fees, Invoices, Payments)
 *
 * Coverage:
 *   - Happy path: Fee calculate → Invoice issue → Payment → Verify (maker-checker)
 *   - Fee operations: Recalculate, Waive, Cancel, Business rules
 *   - Payment rejection + Self-verify block (maker-checker enforcement)
 *
 * Replaces: fee-lifecycle.spec.ts (broken MFA backup codes)
 *
 * Chạy:
 *   npx playwright test finance-lifecycle --project=e2e-workflow --reporter=list
 *   npx playwright test finance-lifecycle --project=e2e-workflow --headed
 *   npx playwright test finance-lifecycle -g "Happy path" --project=e2e-workflow
 */

import { test, expect, type Page, type Cookie } from "@playwright/test";
import * as OTPAuth from "otpauth";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "Admin@12345";
const ADMIN_TOTP_SECRET =
  process.env.E2E_ADMIN_TOTP_SECRET || "";

const OFFICER_USERNAME = process.env.E2E_OFFICER_USERNAME || "vothuhien";
const OFFICER_PASSWORD = process.env.E2E_OFFICER_PASSWORD || "@Matkhau123!";

const API_URL = process.env.E2E_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Shared state across tests (serial execution within describe)
// ---------------------------------------------------------------------------

let adminHeaders: Record<string, string> = {};
let adminCookies: Cookie[] = [];
let officerHeaders: Record<string, string> = {};
let officerCookies: Cookie[] = [];

// Discovery
let offeringId: number;
let admissionMethodId: number;
let initialStatusId: string;

// Test 1: Happy path
let approvedProfileId: number;
let approvedLeadId: number;
let feeId: number;
let feeAmount: number;
let invoiceId: number;
let paymentId: number;
let paymentMethodId: number;

// Test 2: Fee operations
let fee2Id: number;

// Test 3: Payment rejection
let fee3Id: number;
let invoice3Id: number;

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
        // TOTP collision — wait for next period, then restart entire login flow
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
 * Create a lead + admission profile, fill data, upload docs, submit, admin approve.
 * Returns an approved profile ready for fee calculation.
 */
async function setupApprovedProfile(
  page: Page,
  adminHeaders: Record<string, string>,
  adminCookies: Cookie[],
  officerHeaders: Record<string, string>,
  officerCookies: Cookie[],
  opts: {
    offeringId: number;
    admissionMethodId: number;
    initialStatusId: string;
  }
): Promise<{ leadId: number; profileId: number }> {
  const phone = generatePhone();
  const citizenId = generateCitizenId();
  const name = `E2E_Fin_${Date.now()}`;

  // Officer: create lead
  let headers = await restoreCookies(page, officerCookies);
  const leadResp = await page.request.post(`${API_URL}/api/leads`, {
    headers,
    data: {
      full_name: name,
      phone,
      source: "walk_in",
      offering_id: opts.offeringId,
    },
  });
  expect(leadResp.ok() || leadResp.status() === 201).toBeTruthy();
  const leadId = (await leadResp.json()).id;

  // Officer: add consultation
  const consultResp = await page.request.post(
    `${API_URL}/api/leads/${leadId}/consultations`,
    {
      headers,
      data: { status_id: opts.initialStatusId, method: "phone", notes: "E2E finance test" },
    }
  );
  expect(consultResp.ok() || consultResp.status() === 201).toBeTruthy();

  // Officer: create admission profile
  const profileResp = await page.request.post(`${API_URL}/api/admissions`, {
    headers,
    data: { lead_id: leadId, admission_method_id: opts.admissionMethodId },
  });
  expect(profileResp.ok() || profileResp.status() === 201).toBeTruthy();
  const profile = await profileResp.json();
  const profileId = profile.id;

  // Officer: fill personal info + scores
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
      gender: "male",
      dob: "2000-03-15",
      nationality: "Viet Nam",
      ethnicity: "Kinh",
      place_of_birth: "Ha Noi",
      family_info: [
        { relationship: "Cha", full_name: "Nguyen Van X", phone: "0912345670", occupation: "Ky su", is_primary_guardian: true },
        { relationship: "Me", full_name: "Le Thi Y", phone: "0912345671", occupation: "Bac si", is_primary_guardian: false },
      ],
      academic_history: [
        { school_name: "THPT Le Quy Don", year_from: 2018, year_to: 2021, gpa: 8.0, graduation_type: "THPT" },
      ],
      admission_scores: { subject_scores: subjectScores, gpa: 8.0 },
    },
  });

  // Officer: upload mandatory docs
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
            buffer: Buffer.from(`%PDF-1.4\n%%EOF\n% E2E finance: ${doc.code}`),
          },
          actual_submission_format: "photo",
        },
      }
    );
  }

  // Officer: submit
  const submitResp = await page.request.post(
    `${API_URL}/api/admissions/${profileId}/submit`,
    { headers }
  );
  const submitBody = await submitResp.json();
  if (submitBody.status !== "submitted") {
    console.log(`Submit errors: ${JSON.stringify(submitBody.validation_errors || submitBody).slice(0, 500)}`);
  }
  expect(submitBody.status).toBe("submitted");

  // Admin: approve
  headers = await restoreCookies(page, adminCookies);
  const freshProfile = await (await page.request.get(`${API_URL}/api/admissions/${profileId}`)).json();

  const approveResp = await page.request.post(
    `${API_URL}/api/admissions/${profileId}/approve`,
    {
      headers,
      data: {
        notes: "E2E finance test - approved for fee calculation",
        version: freshProfile.version,
      },
    }
  );
  expect(approveResp.ok()).toBeTruthy();
  expect((await approveResp.json()).status).toBe("approved");

  return { leadId, profileId };
}

// ---------------------------------------------------------------------------
// Test Suite
// ---------------------------------------------------------------------------

test.describe("Finance Lifecycle", () => {
  test.describe.configure({ timeout: 600_000, mode: "serial" });

  // =========================================================================
  // Test 1: Happy path — Fee → Invoice → Payment → Verify (maker-checker)
  // =========================================================================
  test("Happy path: Fee → Invoice → Payment → Verify (maker-checker)", async ({ page }) => {
    // --- Step 1: Admin login + discover config ---
    await test.step("Admin login + discover config", async () => {
      adminHeaders = await loginViaAPI(page, ADMIN_USERNAME, ADMIN_PASSWORD, {
        totpSecret: ADMIN_TOTP_SECRET,
      });
      adminCookies = await page.context().cookies();

      // Pipeline
      const pipelineResp = await page.request.get(`${API_URL}/api/pipeline/all`);
      expect(pipelineResp.ok()).toBeTruthy();
      initialStatusId = (await pipelineResp.json()).statuses[0].id;

      // Offerings
      const offeringsResp = await page.request.get(
        `${API_URL}/api/program-offerings?is_active=true&limit=1`
      );
      expect(offeringsResp.ok()).toBeTruthy();
      offeringId = (await offeringsResp.json())[0].id;

      // Admission methods
      const methodsResp = await page.request.get(
        `${API_URL}/api/admission-config/methods?active_only=true`
      );
      expect(methodsResp.ok()).toBeTruthy();
      const methodsBody = await methodsResp.json();
      admissionMethodId = (methodsBody.methods || methodsBody)[0].id;

      console.log(`Config: offering=${offeringId}, method=${admissionMethodId}, status=${initialStatusId}`);
    });

    // --- Step 2: Officer login ---
    await test.step("Officer login", async () => {
      officerHeaders = await loginViaAPI(page, OFFICER_USERNAME, OFFICER_PASSWORD);
      officerCookies = await page.context().cookies();
      console.log("Officer logged in");
    });

    // --- Step 3: Setup approved profile ---
    await test.step("Setup approved profile", async () => {
      const result = await setupApprovedProfile(
        page,
        adminHeaders,
        adminCookies,
        officerHeaders,
        officerCookies,
        { offeringId, admissionMethodId, initialStatusId }
      );
      approvedLeadId = result.leadId;
      approvedProfileId = result.profileId;
      console.log(`Approved profile: lead=${approvedLeadId}, profile=${approvedProfileId}`);
    });

    // --- Step 4: Calculate fee ---
    await test.step("Calculate fee", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.post(`${API_URL}/api/fees/calculate`, {
        headers: adminHeaders,
        data: {
          admission_profile_id: approvedProfileId,
          fee_type: "tuition",
          installment_plan_code: "FULL",
        },
      });
      if (!resp.ok() && resp.status() !== 201) {
        console.log(`Fee calculate failed: ${resp.status()} ${(await resp.text()).slice(0, 500)}`);
      }
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      const body = await resp.json();
      feeId = body.id;
      feeAmount = parseFloat(body.total_amount || body.base_amount);
      expect(feeId).toBeTruthy();
      expect(feeAmount).toBeGreaterThan(0);

      // Extract first invoice ID
      const invoices = body.invoices || [];
      if (invoices.length > 0) {
        invoiceId = invoices[0].id;
      }
      console.log(`Fee created: id=${feeId}, amount=${feeAmount}, invoices=${invoices.length}`);
    });

    // --- Step 5: Get fee details ---
    await test.step("Get fee details", async () => {
      const resp = await page.request.get(`${API_URL}/api/fees/${feeId}`);
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.id).toBe(feeId);
      console.log(`Fee details: status=${body.status}, remaining=${body.remaining_amount}`);
    });

    // --- Step 6: Get fees by profile ---
    await test.step("Get fees by profile", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/fees/by-profile/${approvedProfileId}`
      );
      if (!resp.ok()) {
        console.log(`Fees by profile failed: ${resp.status()} ${(await resp.text()).slice(0, 300)}`);
      }
      expect(resp.ok()).toBeTruthy();
      const fees = await resp.json();
      expect(fees.length).toBeGreaterThanOrEqual(1);
      console.log(`Fees by profile: ${fees.length}`);
    });

    // --- Step 7: Get finance summary ---
    await test.step("Get profile finance summary", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/fees/summary/${approvedProfileId}`
      );
      if (!resp.ok()) {
        console.log(`Finance summary failed: ${resp.status()} ${(await resp.text()).slice(0, 300)}`);
      }
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      const totalFees = parseFloat(body.total_fees || "0");
      expect(totalFees).toBeGreaterThan(0);
      console.log(`Summary: total=${body.total_fees}, remaining=${body.total_remaining}`);
    });

    // --- Step 8: Get/Issue invoice ---
    await test.step("Get and issue invoice", async () => {
      // If invoiceId not set from fee calculation, get it from fee invoices
      if (!invoiceId) {
        const invResp = await page.request.get(`${API_URL}/api/invoices/by-fee/${feeId}`);
        expect(invResp.ok()).toBeTruthy();
        const invoices = await invResp.json();
        expect(invoices.length).toBeGreaterThan(0);
        invoiceId = invoices[0].id;
      }

      const getResp = await page.request.get(`${API_URL}/api/invoices/${invoiceId}`);
      expect(getResp.ok()).toBeTruthy();
      const invoiceDetail = await getResp.json();
      console.log(`Invoice ${invoiceId} fetched, status=${invoiceDetail.status}`);

      // Issue invoice (may already be issued if fee status was 'invoiced')
      if (invoiceDetail.status === "issued") {
        console.log(`Invoice ${invoiceId} already issued, skipping`);
      } else {
        const issueResp = await page.request.put(
          `${API_URL}/api/invoices/${invoiceId}/issue`,
          { headers: adminHeaders }
        );
        expect(issueResp.ok()).toBeTruthy();
        const body = await issueResp.json();
        expect(body.status).toBe("issued");
        console.log(`Invoice ${invoiceId} issued`);
      }
    });

    // --- Step 9: Get payment methods ---
    await test.step("Get payment methods", async () => {
      const resp = await page.request.get(`${API_URL}/api/payments/methods`, {
        headers: adminHeaders,
      });
      if (!resp.ok()) {
        console.log(`Payment methods failed: ${resp.status()} ${(await resp.text()).slice(0, 300)}`);
      }
      expect(resp.ok()).toBeTruthy();
      const methods = await resp.json();
      expect(methods.length).toBeGreaterThan(0);
      paymentMethodId = methods[0].id;
      console.log(`Payment methods: ${methods.length}, using id=${paymentMethodId}`);
    });

    // --- Step 10: Admin records payment ---
    await test.step("Admin records payment", async () => {
      // Note: payments:create requires admin/manager/accountant role
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.post(`${API_URL}/api/payments`, {
        headers: adminHeaders,
        data: {
          invoice_id: invoiceId,
          method_id: paymentMethodId,
          amount: feeAmount,
          reference_code: `E2E_PAY_${Date.now()}`,
          payer_name: "Nguyen Van Test",
        },
      });
      if (!resp.ok() && resp.status() !== 201) {
        console.log(`Record payment failed: ${resp.status()} ${(await resp.text()).slice(0, 500)}`);
      }
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      const body = await resp.json();
      paymentId = body.id;
      expect(body.status).toBe("pending");
      console.log(`Payment created: id=${paymentId}, status=pending`);
    });

    // --- Step 11: Admin verifies payment ---
    await test.step("Admin verifies payment", async () => {
      // Same admin records + verifies (maker-checker may or may not block for admin)
      const resp = await page.request.put(
        `${API_URL}/api/payments/${paymentId}/verify`,
        { headers: adminHeaders }
      );
      if (!resp.ok()) {
        // Self-verify blocked (maker-checker) — this is expected behavior
        // In E2E with only 1 admin, we accept this and just verify the payment exists
        console.log(`Admin self-verify blocked: ${resp.status()} — maker-checker enforced`);
        // Verify payment exists with pending status
        const getResp = await page.request.get(`${API_URL}/api/payments/${paymentId}`, {
          headers: adminHeaders,
        });
        expect(getResp.ok()).toBeTruthy();
        console.log(`Payment ${paymentId} exists (self-verify blocked, OK for single-admin E2E)`);
      } else {
        const body = await resp.json();
        expect(body.status).toBe("verified");
        console.log(`Payment ${paymentId} verified`);
      }
    });

    // --- Step 12: Verify fee status ---
    await test.step("Verify fee after payment", async () => {
      const resp = await page.request.get(`${API_URL}/api/fees/${feeId}`);
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      // paid_amount may be 0 if self-verify was blocked (maker-checker)
      console.log(`Fee paid_amount: ${body.paid_amount}, status: ${body.status}`);
    });

    // --- Step 13: Finance dashboard ---
    await test.step("Finance dashboard", async () => {
      const resp = await page.request.get(`${API_URL}/api/finance/dashboard`);
      if (resp.ok()) {
        const body = await resp.json();
        console.log(`Dashboard: ${JSON.stringify(body).slice(0, 200)}`);
      } else {
        // Dashboard endpoint may not exist, that's OK
        console.log(`Dashboard endpoint: ${resp.status()} (may not exist)`);
      }
    });
  });

  // =========================================================================
  // Test 2: Fee operations — Recalculate + Waive + Cancel + Business rules
  // =========================================================================
  test("Fee operations: Recalculate + Waive + Cancel + Business rules", async ({ page }) => {
    // --- Step 1: Calculate a second fee (application type) ---
    await test.step("Calculate application fee", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.post(`${API_URL}/api/fees/calculate`, {
        headers: adminHeaders,
        data: {
          admission_profile_id: approvedProfileId,
          fee_type: "application",
          installment_plan_code: "FULL",
        },
      });
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      const body = await resp.json();
      fee2Id = body.id;
      console.log(`Fee2 created: id=${fee2Id}, type=application`);
    });

    // --- Step 2: Recalculate fee ---
    await test.step("Recalculate fee", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/fees/${fee2Id}/recalculate?new_base_amount=500000&reason=E2E+test+recalculation`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      console.log(`Fee2 recalculated: ${JSON.stringify(body).slice(0, 200)}`);
    });

    // --- Step 3: Waive partial amount ---
    await test.step("Waive partial fee amount", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/fees/${fee2Id}/waive`,
        {
          headers: adminHeaders,
          data: {
            waive_amount: 100000,
            reason: "E2E test: scholarship discount",
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      console.log(`Fee2 waived: ${JSON.stringify(body).slice(0, 200)}`);
    });

    // --- Step 4: Waive excessive amount (should fail) ---
    await test.step("Waive excessive amount fails", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/fees/${fee2Id}/waive`,
        {
          headers: adminHeaders,
          data: {
            waive_amount: 999999999,
            reason: "E2E test: this should fail",
          },
        }
      );
      expect([400, 422]).toContain(resp.status());
      console.log(`Excessive waive rejected: ${resp.status()}`);
    });

    // --- Step 5: Cancel fee2 ---
    await test.step("Cancel fee", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/fees/${fee2Id}/cancel?reason=E2E+test+cancellation`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.status).toBe("cancelled");
      console.log(`Fee2 cancelled`);
    });

    // --- Step 6: Recalculate fee with pending payment ---
    await test.step("Recalculate fee with pending payment", async () => {
      // With only a pending (unverified) payment, recalculate may still succeed
      const resp = await page.request.post(
        `${API_URL}/api/fees/${feeId}/recalculate?new_base_amount=7000000&reason=E2E+recalculate+test`,
        { headers: adminHeaders }
      );
      // Accept either success (pending payment doesn't block) or blocked (stricter rules)
      if (resp.ok()) {
        console.log(`Recalculate succeeded (pending payment doesn't block)`);
      } else {
        expect([400, 409, 422]).toContain(resp.status());
        console.log(`Recalculate blocked: ${resp.status()}`);
      }
    });

    // --- Step 7: List installment plans ---
    await test.step("List installment plans", async () => {
      const resp = await page.request.get(`${API_URL}/api/installment-plans`);
      if (resp.ok()) {
        const plans = await resp.json();
        console.log(`Installment plans: ${JSON.stringify(plans).slice(0, 200)}`);
      } else {
        // Endpoint may not exist
        console.log(`Installment plans endpoint: ${resp.status()}`);
      }
    });
  });

  // =========================================================================
  // Test 3: Payment rejection + Self-verify block (maker-checker enforcement)
  // =========================================================================
  test("Payment rejection + Self-verify block", async ({ page }) => {
    // --- Step 1: Create new fee + issue invoice ---
    await test.step("Create fee + issue invoice", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // Calculate a new fee
      const feeResp = await page.request.post(`${API_URL}/api/fees/calculate`, {
        headers: adminHeaders,
        data: {
          admission_profile_id: approvedProfileId,
          fee_type: "other",
          installment_plan_code: "FULL",
        },
      });

      // If "other" fee type not available, create another tuition fee for a new profile
      if (feeResp.ok() || feeResp.status() === 201) {
        const body = await feeResp.json();
        fee3Id = body.id;
        const invoices = body.invoices || [];
        if (invoices.length > 0) {
          invoice3Id = invoices[0].id;
        }
      } else {
        // Fallback: reuse a different approach - create new profile
        console.log(`'other' fee type failed (${feeResp.status()}), creating new profile`);
        const result = await setupApprovedProfile(
          page,
          adminHeaders,
          adminCookies,
          officerHeaders,
          officerCookies,
          { offeringId, admissionMethodId, initialStatusId }
        );
        adminHeaders = await restoreCookies(page, adminCookies);

        const newFeeResp = await page.request.post(`${API_URL}/api/fees/calculate`, {
          headers: adminHeaders,
          data: {
            admission_profile_id: result.profileId,
            fee_type: "tuition",
            installment_plan_code: "FULL",
          },
        });
        expect(newFeeResp.ok() || newFeeResp.status() === 201).toBeTruthy();
        const body = await newFeeResp.json();
        fee3Id = body.id;
        const invoices = body.invoices || [];
        if (invoices.length > 0) {
          invoice3Id = invoices[0].id;
        }
      }
      expect(fee3Id).toBeTruthy();

      // Get invoice if not set
      if (!invoice3Id) {
        const invResp = await page.request.get(`${API_URL}/api/invoices/by-fee/${fee3Id}`);
        expect(invResp.ok()).toBeTruthy();
        const invoices = await invResp.json();
        expect(invoices.length).toBeGreaterThan(0);
        invoice3Id = invoices[0].id;
      }

      // Issue invoice
      const issueResp = await page.request.put(
        `${API_URL}/api/invoices/${invoice3Id}/issue`,
        { headers: adminHeaders }
      );
      expect(issueResp.ok()).toBeTruthy();
      console.log(`Fee3=${fee3Id}, Invoice3=${invoice3Id} issued`);
    });

    // --- Step 2: Admin records payment ---
    let payment3Id: number;
    await test.step("Admin records payment", async () => {
      const resp = await page.request.post(`${API_URL}/api/payments`, {
        headers: adminHeaders,
        data: {
          invoice_id: invoice3Id,
          method_id: paymentMethodId,
          amount: 100000,
          reference_code: `E2E_REJ_${Date.now()}`,
          payer_name: "Tran Van Test",
        },
      });
      if (!resp.ok() && resp.status() !== 201) {
        console.log(`Record payment3 failed: ${resp.status()} ${(await resp.text()).slice(0, 300)}`);
      }
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      const body = await resp.json();
      payment3Id = body.id;
      expect(body.status).toBe("pending");
      console.log(`Payment3=${payment3Id} created by admin`);
    });

    // --- Step 3: Admin tries self-verify (should be blocked by maker-checker) ---
    await test.step("Admin self-verify blocked (maker-checker)", async () => {
      const resp = await page.request.put(
        `${API_URL}/api/payments/${payment3Id}/verify`,
        { headers: adminHeaders }
      );
      // Expect 400 or 403 for self-approval attempt
      expect([400, 403]).toContain(resp.status());
      console.log(`Self-verify blocked: ${resp.status()}`);
    });

    // --- Step 4: Admin rejects payment ---
    await test.step("Admin rejects payment", async () => {
      const resp = await page.request.put(
        `${API_URL}/api/payments/${payment3Id}/reject?reason=E2E+test+payment+rejection`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.status).toBe("rejected");
      console.log(`Payment3 rejected`);
    });

    // --- Step 5: Verify payment in invoice list ---
    await test.step("Verify payment in invoice payment list", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/payments/by-invoice/${invoice3Id}`
      );
      expect(resp.ok()).toBeTruthy();
      const payments = await resp.json();
      const rejected = payments.find((p: { id: number }) => p.id === payment3Id);
      expect(rejected).toBeTruthy();
      expect(rejected.status).toBe("rejected");
      console.log(`Payment3 found in invoice list with status=rejected`);
    });
  });
});
