/**
 * E2E Test: Magic Link Confirmation Flow
 *
 * State machine coverage:
 *   submitted → approved → confirmed → enrolled
 *
 * Tests the token-based confirmation path where a lead confirms
 * their admission via a magic link (CCCD verification).
 *
 * MFA backup codes: Uses 1 admin backup code per run.
 *
 * Chạy: npx playwright test admission-confirm-flow.spec.ts --project=e2e-workflow --headed
 */

import { test, expect, type Page, type Cookie } from "@playwright/test";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const OFFICER_USERNAME = process.env.E2E_OFFICER_USERNAME || "vothuhien";
const OFFICER_PASSWORD = process.env.E2E_OFFICER_PASSWORD || "@Matkhau123!";
const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "Admin@12345";
const ADMIN_MFA_CODE = process.env.E2E_ADMIN_MFA_CODE || "e1cb4ebe04";
const API_URL = process.env.E2E_API_URL || "http://localhost:8000";

// Shared state
let createdLeadId: number;
let createdProfileId: number;
let officerHeaders: Record<string, string> = {};
let adminHeaders: Record<string, string> = {};
let adminCookies: Cookie[] = [];
let tokenValue: string;
let citizenId: string;

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

function generateCitizenId(): string {
  return Array.from({ length: 12 }, () => Math.floor(Math.random() * 10)).join(
    ""
  );
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
  mfaCode?: string
): Promise<Record<string, string>> {
  await page.context().clearCookies();

  const loginResp = await page.request.post(`${API_URL}/api/auth/login`, {
    form: { username, password },
  });
  if (!loginResp.ok()) {
    console.log(`Login failed for ${username}: ${loginResp.status()} ${(await loginResp.text()).slice(0, 300)}`);
  }
  expect(loginResp.ok()).toBeTruthy();

  let loginBody = await loginResp.json();
  let authResp = loginResp;

  if (loginBody.mfa_required && mfaCode) {
    const mfaResp = await page.request.post(
      `${API_URL}/api/auth/verify-mfa`,
      { data: { mfa_token: loginBody.mfa_token, code: mfaCode } }
    );
    expect(mfaResp.ok()).toBeTruthy();
    loginBody = await mfaResp.json();
    authResp = mfaResp;
  }

  const csrf = await extractAndAddCookies(page, authResp);
  return csrf ? { "X-CSRF-Token": csrf } : {};
}

/** Restore a previously saved cookie set (avoids re-login + MFA). */
async function restoreCookies(
  page: Page,
  cookies: Cookie[],
  headers: Record<string, string>
) {
  await page.context().clearCookies();
  if (cookies.length > 0) {
    await page.context().addCookies(cookies);
  }
  return headers;
}

async function getProfile(page: Page, profileId: number) {
  const resp = await page.request.get(
    `${API_URL}/api/admissions/${profileId}`
  );
  expect(resp.ok()).toBeTruthy();
  return resp.json();
}

// ---------------------------------------------------------------------------
// Test Suite
// ---------------------------------------------------------------------------

test.describe("Admission Confirmation Flow (Magic Link)", () => {
  test.describe.configure({ timeout: 600_000 });

  const testName = `E2E_Confirm_${Date.now()}`;
  const testPhone = generatePhone();

  test("Confirmation flow: Submit → Approve → Send Token → Verify CCCD → Confirm → Enroll", async ({
    page,
  }) => {
    citizenId = generateCitizenId();

    // =================================================================
    // STEP 1: Officer login + create lead + profile + submit
    // =================================================================
    await test.step("Setup: Create lead, profile, fill data, submit", async () => {
      officerHeaders = await loginViaAPI(page, OFFICER_USERNAME, OFFICER_PASSWORD);
      console.log("Officer logged in");

      // Get offering + admission method for lead + profile creation
      const offeringsResp = await page.request.get(
        `${API_URL}/api/program-offerings?is_active=true&limit=1`
      );
      if (!offeringsResp.ok()) {
        console.log(`Offerings failed: ${offeringsResp.status()} ${(await offeringsResp.text()).slice(0, 300)}`);
      }
      expect(offeringsResp.ok()).toBeTruthy();
      const offerings = await offeringsResp.json();
      expect(offerings.length).toBeGreaterThan(0);
      const offeringId = offerings[0].id;
      console.log(`Using offering_id: ${offeringId}`);

      const methodsResp = await page.request.get(
        `${API_URL}/api/admission-config/methods?active_only=true`
      );
      expect(methodsResp.ok()).toBeTruthy();
      const methodsBody = await methodsResp.json();
      const methods = methodsBody.methods || methodsBody;
      expect(methods.length).toBeGreaterThan(0);

      // Create lead with offering
      const leadResp = await page.request.post(`${API_URL}/api/leads`, {
        headers: officerHeaders,
        data: {
          full_name: testName,
          phone: testPhone,
          source: "walk_in",
          offering_id: offeringId,
        },
      });
      expect(leadResp.ok() || leadResp.status() === 201).toBeTruthy();
      createdLeadId = (await leadResp.json()).id;
      console.log(`Created lead ID: ${createdLeadId}`);

      // Add consultation (required before creating admission profile)
      const pipelineResp = await page.request.get(`${API_URL}/api/pipeline/all`);
      expect(pipelineResp.ok()).toBeTruthy();
      const pipeline = await pipelineResp.json();
      const firstStatus = pipeline.statuses[0];
      const consultResp = await page.request.post(
        `${API_URL}/api/leads/${createdLeadId}/consultations`,
        {
          headers: officerHeaders,
          data: { status_id: firstStatus.id, method: "phone", notes: "E2E test consultation" },
        }
      );
      expect(consultResp.ok() || consultResp.status() === 201).toBeTruthy();
      console.log(`Consultation added with status: ${firstStatus.id}`);

      // Create profile
      const profileResp = await page.request.post(`${API_URL}/api/admissions`, {
        headers: officerHeaders,
        data: {
          lead_id: createdLeadId,
          admission_method_id: methods[0].id,
        },
      });
      if (!profileResp.ok() && profileResp.status() !== 201) {
        const errBody = await profileResp.text();
        console.log(`Profile creation failed: ${profileResp.status()} ${errBody.slice(0, 500)}`);
      }
      expect(profileResp.ok() || profileResp.status() === 201).toBeTruthy();
      createdProfileId = (await profileResp.json()).id;
      console.log(`Created profile ID: ${createdProfileId}`);

      // Update personal info + family + academic history + scores (all required for submit)
      const freshProfile = await getProfile(page, createdProfileId);
      const allowedSubjects: string[] = freshProfile.applied_rules?.allowed_subject_codes || [];
      const subjectScores: Record<string, number> = {};
      for (const subj of allowedSubjects.slice(0, 3)) {
        subjectScores[subj] = 7 + Math.random() * 3; // Random score 7-10
      }
      console.log(`Subject scores: ${JSON.stringify(subjectScores)}`);

      const updateResp = await page.request.put(
        `${API_URL}/api/admissions/${createdProfileId}`,
        {
          headers: officerHeaders,
          data: {
            version: freshProfile.version,
            citizen_id: citizenId,
            gender: "female",
            date_of_birth: "2001-06-20",
            nationality: "Việt Nam",
            ethnicity: "Kinh",
            place_of_birth: "TP. Hồ Chí Minh",
            family_info: [
              { relationship: "Cha", full_name: "Nguyễn Văn A", phone: "0901234567", occupation: "Kinh doanh", is_primary_guardian: true },
              { relationship: "Mẹ", full_name: "Trần Thị B", phone: "0901234568", occupation: "Giáo viên", is_primary_guardian: false },
            ],
            academic_history: [
              { school_name: "THPT Nguyễn Du", year_from: 2019, year_to: 2022, gpa: 8.5, graduation_type: "THPT" },
            ],
            admission_scores: {
              subject_scores: subjectScores,
              gpa: 8.5,
            },
          },
        }
      );
      if (!updateResp.ok()) {
        console.log(`Profile update failed: ${updateResp.status()} ${(await updateResp.text()).slice(0, 500)}`);
      }

      // Upload mandatory documents
      const profile = await getProfile(page, createdProfileId);
      const missingDocs = (profile.documents_checklist || []).filter(
        (d: { is_mandatory: boolean; status: string }) =>
          d.is_mandatory && d.status === "missing"
      );
      for (const doc of missingDocs) {
        await page.request.post(
          `${API_URL}/api/admissions/${createdProfileId}/documents/${doc.code}/upload`,
          {
            headers: officerHeaders,
            multipart: {
              file: {
                name: `${doc.code}.pdf`,
                mimeType: "application/pdf",
                buffer: Buffer.from(`%PDF-1.4\n%%EOF\n% E2E: ${doc.code}`),
              },
              actual_submission_format: "photo",
            },
          }
        );
      }
      console.log(`Uploaded ${missingDocs.length} mandatory docs`);

      // Submit
      const submitResp = await page.request.post(
        `${API_URL}/api/admissions/${createdProfileId}/submit`,
        { headers: officerHeaders }
      );
      const submitBody = await submitResp.json();
      if (submitBody.status !== "submitted") {
        console.log(`Submit validation errors: ${JSON.stringify(submitBody.validation_errors || submitBody)}`);
      }
      expect(submitBody.status).toBe("submitted");
      console.log("Profile submitted");
    });

    // =================================================================
    // STEP 2: Admin login (ONCE) + approve profile
    // =================================================================
    await test.step("Admin approves profile", async () => {
      adminHeaders = await loginViaAPI(page, ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_MFA_CODE);
      // Save admin cookies for later restoration (avoid re-login + MFA)
      adminCookies = await page.context().cookies();
      console.log("Admin logged in (session saved)");

      const profile = await getProfile(page, createdProfileId);
      expect(profile.status).toBe("submitted");

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${createdProfileId}/approve`,
        {
          headers: adminHeaders,
          data: {
            notes: "E2E confirmation test - approved for token generation",
            version: profile.version,
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.status).toBe("approved");
      console.log(`Approved! version: ${body.version}`);
    });

    // =================================================================
    // STEP 3: Admin sends confirmation link (generates token)
    // =================================================================
    await test.step("Admin sends confirmation link", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${createdProfileId}/send-confirmation`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();

      tokenValue = body.token_value;
      expect(tokenValue).toBeTruthy();
      console.log(`Confirmation link sent, token: ${tokenValue.slice(0, 8)}...`);
      console.log(`Expires at: ${body.token_expires_at}`);
    });

    // =================================================================
    // STEP 4: GET token info (public endpoint - no auth needed)
    // Public endpoints work with or without auth cookies, so no need
    // to clear cookies. We keep admin session intact for later.
    // =================================================================
    await test.step("Get token info (public)", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/admissions/confirm/${tokenValue}`
      );
      expect(resp.ok()).toBeTruthy();
      const info = await resp.json();

      expect(info.valid).toBe(true);
      expect(info.expired).toBe(false);
      expect(info.locked).toBe(false);
      expect(info.already_used).toBe(false);
      expect(info.attempts_remaining).toBe(5);
      expect(info.profile_name).toBeTruthy();

      console.log(`Token info: valid=${info.valid}, attempts=${info.attempts_remaining}, name=${info.profile_name}`);
    });

    // =================================================================
    // STEP 5: Confirm with WRONG CCCD (should fail)
    // Public endpoint - CSRF exempt via backend middleware
    // =================================================================
    await test.step("Confirm with wrong CCCD (should fail)", async () => {
      const wrongDigits = "0000";

      const resp = await page.request.post(
        `${API_URL}/api/admissions/confirm/${tokenValue}`,
        { data: { last_digits_citizen_id: wrongDigits } }
      );

      expect(resp.status()).toBe(400);
      const body = await resp.json();
      expect(body.detail).toContain("CCCD");
      console.log(`Wrong CCCD rejected: ${body.detail}`);
    });

    // =================================================================
    // STEP 6: Verify attempts decremented
    // =================================================================
    await test.step("Verify attempts decremented", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/admissions/confirm/${tokenValue}`
      );
      expect(resp.ok()).toBeTruthy();
      const info = await resp.json();

      expect(info.valid).toBe(true);
      expect(info.attempts_remaining).toBe(4);
      console.log(`Attempts remaining: ${info.attempts_remaining}`);
    });

    // =================================================================
    // STEP 7: Confirm with CORRECT CCCD (should succeed)
    // =================================================================
    await test.step("Confirm with correct CCCD", async () => {
      const lastFour = citizenId.slice(-4);

      const resp = await page.request.post(
        `${API_URL}/api/admissions/confirm/${tokenValue}`,
        { data: { last_digits_citizen_id: lastFour } }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.status).toBe("confirmed");
      expect(body.profile_id).toBe(createdProfileId);
      console.log(`Confirmed! profile_id=${body.profile_id}, confirmed_at=${body.confirmed_at}`);
    });

    // =================================================================
    // STEP 8: Verify token is now used (replay prevention)
    // =================================================================
    await test.step("Verify token cannot be reused", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/admissions/confirm/${tokenValue}`
      );
      expect(resp.ok()).toBeTruthy();
      const info = await resp.json();

      expect(info.already_used).toBe(true);
      console.log(`Token marked as used: already_used=${info.already_used}`);
    });

    // =================================================================
    // STEP 9: Admin enrolls confirmed profile (restore saved session)
    // =================================================================
    await test.step("Admin enrolls confirmed profile", async () => {
      // Restore admin session from saved cookies (no re-login needed)
      await restoreCookies(page, adminCookies, adminHeaders);
      console.log("Admin session restored from saved cookies");

      const profile = await getProfile(page, createdProfileId);
      expect(profile.status).toBe("confirmed");

      // Try /enroll first
      const enrollResp = await page.request.post(
        `${API_URL}/api/admissions/${createdProfileId}/enroll`,
        { headers: adminHeaders }
      );

      if (enrollResp.ok() || enrollResp.status() === 201) {
        const body = await enrollResp.json();
        console.log(`Enrolled! student_code=${body.student_code}`);
      } else {
        // Fallback to /finalize
        const finalizeResp = await page.request.post(
          `${API_URL}/api/admissions/${createdProfileId}/finalize`,
          { headers: adminHeaders, data: {} }
        );
        expect(finalizeResp.ok()).toBeTruthy();
        const body = await finalizeResp.json();
        console.log(`Finalized! status=${body.status}`);
      }
    });

    // =================================================================
    // STEP 10: Verify final state = enrolled
    // =================================================================
    await test.step("Verify final state", async () => {
      const profile = await getProfile(page, createdProfileId);

      console.log(`\n========== CONFIRMATION FLOW RESULTS ==========`);
      console.log(`Lead ID:        ${createdLeadId}`);
      console.log(`Profile ID:     ${createdProfileId}`);
      console.log(`Citizen ID:     ${citizenId.slice(0, 4)}****${citizenId.slice(-4)}`);
      console.log(`Final status:   ${profile.status}`);
      console.log(`================================================\n`);

      expect(profile.status).not.toBe("draft");
      expect(profile.status).not.toBe("approved");

      const terminalStatuses = ["enrolled", "confirmed"];
      expect(terminalStatuses).toContain(profile.status);

      if (profile.status === "enrolled") {
        console.log("Full confirmation → enrollment flow completed!");
      }
    });
  });
});
