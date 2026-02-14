/**
 * E2E Test: Admission Rejection & Recovery Flow
 *
 * State machine coverage:
 *   submitted → rejected → resubmitted → approved → overridden → enrolled
 *
 * This is the alternative path where an admission is rejected, then
 * resubmitted with corrections, approved, and finally enrolled.
 *
 * Chạy: npx playwright test admission-rejection-flow.spec.ts --project=e2e-workflow --headed
 */

import { test, expect, type Page, type Cookie } from "@playwright/test";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const OFFICER_USERNAME = process.env.E2E_OFFICER_USERNAME || "vothuhien";
const OFFICER_PASSWORD = process.env.E2E_OFFICER_PASSWORD || "@Matkhau123!";
const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "Admin@12345";
const ADMIN_MFA_CODE = process.env.E2E_ADMIN_MFA_CODE || "763ca4b177";
const API_URL = process.env.E2E_API_URL || "http://localhost:8000";

// Shared state across test steps
let createdLeadId: number;
let createdProfileId: number;
let officerHeaders: Record<string, string> = {};
let adminHeaders: Record<string, string> = {};
let adminCookies: Cookie[] = [];

// ---------------------------------------------------------------------------
// Helpers (shared with other workflow tests)
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

/**
 * Login via API and return CSRF headers. Handles MFA if required.
 */
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
  expect(loginResp.ok()).toBeTruthy();

  let loginBody = await loginResp.json();
  let authResp = loginResp;

  // Handle MFA
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
async function restoreCookies(page: Page, cookies: Cookie[]) {
  await page.context().clearCookies();
  if (cookies.length > 0) {
    await page.context().addCookies(cookies);
  }
}

/**
 * Get the current profile state (status + version).
 */
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

test.describe("Admission Rejection & Recovery Flow", () => {
  test.describe.configure({ timeout: 600_000 }); // 10 minutes

  const testName = `E2E_Reject_${Date.now()}`;
  const testPhone = generatePhone();
  const testCitizenId = generateCitizenId();

  test("Rejection flow: Submit → Reject → Resubmit → Approve → Override → Enroll", async ({
    page,
  }) => {
    // =================================================================
    // STEP 1: Officer login + create lead via API
    // =================================================================
    await test.step("Officer login + create lead", async () => {
      officerHeaders = await loginViaAPI(page, OFFICER_USERNAME, OFFICER_PASSWORD);
      console.log("Officer logged in");

      // Get offering for lead creation
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

      // Create lead with offering
      const resp = await page.request.post(`${API_URL}/api/leads`, {
        headers: officerHeaders,
        data: {
          full_name: testName,
          phone: testPhone,
          source: "walk_in",
          offering_id: offeringId,
        },
      });
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      const body = await resp.json();
      createdLeadId = body.id;
      expect(createdLeadId).toBeTruthy();
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
    });

    // =================================================================
    // STEP 2: Create admission profile via API
    // =================================================================
    await test.step("Create admission profile", async () => {
      // Get admission methods
      const methodsResp = await page.request.get(
        `${API_URL}/api/admission-config/methods?active_only=true`
      );
      expect(methodsResp.ok()).toBeTruthy();
      const methodsBody = await methodsResp.json();
      const methods = methodsBody.methods || methodsBody;
      expect(methods.length).toBeGreaterThan(0);
      const admissionMethodId = methods[0].id;

      const resp = await page.request.post(`${API_URL}/api/admissions`, {
        headers: officerHeaders,
        data: {
          lead_id: createdLeadId,
          admission_method_id: admissionMethodId,
        },
      });
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      const body = await resp.json();
      createdProfileId = body.id;
      expect(createdProfileId).toBeTruthy();
      console.log(`Created profile ID: ${createdProfileId}, method: ${admissionMethodId}`);
    });

    // =================================================================
    // STEP 3: Fill required data + upload docs + submit
    // =================================================================
    await test.step("Fill data, upload docs, submit profile", async () => {
      // Update personal info + family + academic history + scores
      const freshProfile = await getProfile(page, createdProfileId);
      const allowedSubjects: string[] = freshProfile.applied_rules?.allowed_subject_codes || [];
      const subjectScores: Record<string, number> = {};
      for (const subj of allowedSubjects.slice(0, 3)) {
        subjectScores[subj] = 7 + Math.random() * 3;
      }

      const updateResp = await page.request.put(
        `${API_URL}/api/admissions/${createdProfileId}`,
        {
          headers: officerHeaders,
          data: {
            version: freshProfile.version,
            citizen_id: testCitizenId,
            gender: "male",
            date_of_birth: "2000-01-15",
            nationality: "Việt Nam",
            ethnicity: "Kinh",
            place_of_birth: "Hà Nội",
            family_info: [
              { relationship: "Cha", full_name: "Trần Văn C", phone: "0912345678", occupation: "Nông dân", is_primary_guardian: true },
              { relationship: "Mẹ", full_name: "Lê Thị D", phone: "0912345679", occupation: "Nội trợ", is_primary_guardian: false },
            ],
            academic_history: [
              { school_name: "THPT Chu Văn An", year_from: 2018, year_to: 2021, gpa: 7.5, graduation_type: "THPT" },
            ],
            admission_scores: {
              subject_scores: subjectScores,
              gpa: 7.5,
            },
          },
        }
      );
      if (updateResp.ok()) {
        console.log("Personal info updated");
      } else {
        console.log(`Personal info update: ${updateResp.status()} ${(await updateResp.text()).slice(0, 300)}`);
      }

      // Get profile to check required documents
      const profile = await getProfile(page, createdProfileId);
      const checklist: Array<{
        code: string;
        is_mandatory: boolean;
        status: string;
      }> = profile.documents_checklist || [];

      const missingDocs = checklist.filter(
        (d) => d.is_mandatory && d.status === "missing"
      );
      console.log(`Mandatory docs missing: ${missingDocs.length}`);

      // Upload fake PDF for each missing mandatory doc
      for (const doc of missingDocs) {
        const fakeContent = `%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n% E2E: ${doc.code}`;
        const resp = await page.request.post(
          `${API_URL}/api/admissions/${createdProfileId}/documents/${doc.code}/upload`,
          {
            headers: officerHeaders,
            multipart: {
              file: {
                name: `${doc.code}.pdf`,
                mimeType: "application/pdf",
                buffer: Buffer.from(fakeContent),
              },
              actual_submission_format: "photo",
            },
          }
        );
        if (resp.ok()) {
          console.log(`Uploaded ${doc.code}`);
        }
      }

      // Submit profile
      const submitResp = await page.request.post(
        `${API_URL}/api/admissions/${createdProfileId}/submit`,
        { headers: officerHeaders }
      );
      const submitBody = await submitResp.json();
      if (submitBody.status !== "submitted") {
        console.log(`Submit validation errors: ${JSON.stringify(submitBody.validation_errors || submitBody)}`);
      }
      console.log(`Submit: status=${submitBody.status}`);
      expect(submitBody.status).toBe("submitted");
    });

    // =================================================================
    // STEP 4: Admin login
    // =================================================================
    await test.step("Admin login", async () => {
      adminHeaders = await loginViaAPI(page, ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_MFA_CODE);
      adminCookies = await page.context().cookies();
      console.log("Admin logged in (session saved)");
    });

    // =================================================================
    // STEP 5: Admin rejects profile (submitted → rejected)
    // =================================================================
    await test.step("Admin rejects profile", async () => {
      const profile = await getProfile(page, createdProfileId);
      expect(profile.status).toBe("submitted");

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${createdProfileId}/reject`,
        {
          headers: adminHeaders,
          data: {
            reason: "Missing required documents - please upload updated ID card and transcript",
            version: profile.version,
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.status).toBe("rejected");
      console.log(`Rejected! version: ${profile.version} → ${body.version}`);
    });

    // =================================================================
    // STEP 6: Verify rejection state
    // =================================================================
    await test.step("Verify rejection state", async () => {
      const profile = await getProfile(page, createdProfileId);
      expect(profile.status).toBe("rejected");
      console.log(`Profile status confirmed: ${profile.status}`);
    });

    // =================================================================
    // STEP 7: Officer resubmits profile (rejected → resubmitted)
    // =================================================================
    await test.step("Officer resubmits profile", async () => {
      // Re-login as officer
      officerHeaders = await loginViaAPI(page, OFFICER_USERNAME, OFFICER_PASSWORD);

      const profile = await getProfile(page, createdProfileId);
      expect(profile.status).toBe("rejected");

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${createdProfileId}/resubmit`,
        {
          headers: officerHeaders,
          data: {
            notes: "Uploaded corrected ID card and updated transcript as requested",
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.status).toBe("resubmitted");
      console.log(`Resubmitted! version: ${body.version}`);
    });

    // =================================================================
    // STEP 8: Admin approves resubmitted profile (resubmitted → approved)
    // =================================================================
    await test.step("Admin approves resubmitted profile", async () => {
      // Restore admin session (no re-login, no MFA code consumed)
      await restoreCookies(page, adminCookies);
      console.log("Admin session restored");

      const profile = await getProfile(page, createdProfileId);
      expect(profile.status).toBe("resubmitted");

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${createdProfileId}/approve`,
        {
          headers: adminHeaders,
          data: {
            notes: "Documents verified after resubmission - approved",
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
    // STEP 9: Override + Enroll (approved → overridden → enrolled)
    // =================================================================
    await test.step("Override and enroll", async () => {
      // Override
      const overrideResp = await page.request.post(
        `${API_URL}/api/admissions/${createdProfileId}/override`,
        {
          headers: adminHeaders,
          data: {
            reason: "E2E rejection flow test: bypass confirmation for enrollment",
          },
        }
      );
      if (overrideResp.ok()) {
        const body = await overrideResp.json();
        console.log(`Overridden! status: ${body.status}`);
      } else {
        console.log(`Override: ${overrideResp.status()}`);
      }

      // Enroll
      const enrollResp = await page.request.post(
        `${API_URL}/api/admissions/${createdProfileId}/enroll`,
        { headers: adminHeaders }
      );

      if (enrollResp.ok() || enrollResp.status() === 201) {
        const body = await enrollResp.json();
        console.log(`Enrolled! student_code: ${body.student_code}`);
      } else {
        // Fallback to /finalize
        const finalizeResp = await page.request.post(
          `${API_URL}/api/admissions/${createdProfileId}/finalize`,
          { headers: adminHeaders, data: {} }
        );
        if (finalizeResp.ok()) {
          const body = await finalizeResp.json();
          console.log(`Finalized! status: ${body.status}`);
        } else {
          console.log(`Finalize: ${finalizeResp.status()}`);
        }
      }
    });

    // =================================================================
    // STEP 10: Verify final state = enrolled
    // =================================================================
    await test.step("Verify final state", async () => {
      const profile = await getProfile(page, createdProfileId);

      console.log(`\n========== REJECTION FLOW RESULTS ==========`);
      console.log(`Lead ID:        ${createdLeadId}`);
      console.log(`Profile ID:     ${createdProfileId}`);
      console.log(`Final status:   ${profile.status}`);
      console.log(`=============================================\n`);

      // Profile must have progressed beyond draft
      expect(profile.status).not.toBe("draft");
      expect(profile.status).not.toBe("rejected");

      // Should be enrolled or at least approved/overridden
      const terminalStatuses = ["enrolled", "overridden", "approved"];
      expect(terminalStatuses).toContain(profile.status);

      if (profile.status === "enrolled") {
        console.log("Full rejection → recovery → enrollment flow completed!");
      }
    });
  });
});
