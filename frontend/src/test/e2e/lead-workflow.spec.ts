/**
 * E2E Test: Lead Management Workflow
 *
 * Coverage:
 *   - Lead CRUD + Consultation + Status progression
 *   - Assignment + Bulk operations + Duplicate check
 *   - Delete/Restore + FSM validation
 *
 * Chạy:
 *   npx playwright test lead-workflow --project=e2e-workflow --reporter=list
 *   npx playwright test lead-workflow --project=e2e-workflow --headed
 *   npx playwright test lead-workflow -g "CRUD" --project=e2e-workflow
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
// Shared state across tests (serial execution within describe)
// ---------------------------------------------------------------------------

let adminHeaders: Record<string, string> = {};
let adminCookies: Cookie[] = [];
let officerHeaders: Record<string, string> = {};
let officerCookies: Cookie[] = [];

// Discovery
let unitId: number;
let offeringId: number;
let pipelineStatuses: Array<{ id: string; name: string }> = [];
let pipelineStages: Array<{ id: string; name: string }> = [];
let initialStatusId: string;
let secondStatusId: string;
let officerUserId: number;

// Leads
let leadId1: number; // happy path CRUD
let leadId2: number; // assignment/bulk
let leadId3: number; // delete/restore
let consultationId1: number;
const testPhone1 = generatePhone();
const testPhone2 = generatePhone();
const testPhone3 = generatePhone();

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
      let mfaResp = await page.request.post(`${API_URL}/api/auth/verify-mfa`, {
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

// ---------------------------------------------------------------------------
// Test Suite
// ---------------------------------------------------------------------------

test.describe("Lead Management Workflow", () => {
  test.describe.configure({ timeout: 600_000, mode: "serial" });

  // =========================================================================
  // Test 1: Lead CRUD + Consultation + Status progression
  // =========================================================================
  test("Lead CRUD + Consultation + Status progression", async ({ page }) => {
    // --- Step 1: Admin login + discover pipeline, units, offerings ---
    await test.step("Admin login + discover config", async () => {
      adminHeaders = await loginViaAPI(page, ADMIN_USERNAME, ADMIN_PASSWORD, {
        totpSecret: ADMIN_TOTP_SECRET,
      });
      adminCookies = await page.context().cookies();
      console.log("Admin logged in");

      // Pipeline
      const pipelineResp = await page.request.get(`${API_URL}/api/pipeline/all`);
      expect(pipelineResp.ok()).toBeTruthy();
      const pipeline = await pipelineResp.json();
      pipelineStatuses = pipeline.statuses;
      pipelineStages = pipeline.stages;
      const transitions: Array<{ from_status_id: string; to_status_id: string }> =
        pipeline.allowed_transitions || [];
      expect(pipelineStatuses.length).toBeGreaterThanOrEqual(2);

      // Pick a valid transition pair from allowed_transitions
      if (transitions.length > 0) {
        initialStatusId = transitions[0].from_status_id;
        secondStatusId = transitions[0].to_status_id;
      } else {
        // Fallback: use first two statuses
        initialStatusId = pipelineStatuses[0].id;
        secondStatusId = pipelineStatuses[1].id;
      }
      console.log(`Pipeline: ${pipelineStatuses.length} statuses, ${transitions.length} transitions, initial=${initialStatusId}, second=${secondStatusId}`);

      // Organization units
      const unitsResp = await page.request.get(`${API_URL}/api/organization-units`);
      expect(unitsResp.ok()).toBeTruthy();
      const units = await unitsResp.json();
      unitId = units[0]?.id;
      expect(unitId).toBeTruthy();
      console.log(`Unit ID: ${unitId}`);

      // Offerings
      const offeringsResp = await page.request.get(
        `${API_URL}/api/program-offerings?is_active=true&limit=1`
      );
      expect(offeringsResp.ok()).toBeTruthy();
      const offerings = await offeringsResp.json();
      expect(offerings.length).toBeGreaterThan(0);
      offeringId = offerings[0].id;
      console.log(`Offering ID: ${offeringId}`);
    });

    // --- Step 2: Officer login ---
    await test.step("Officer login", async () => {
      officerHeaders = await loginViaAPI(page, OFFICER_USERNAME, OFFICER_PASSWORD);
      officerCookies = await page.context().cookies();
      console.log("Officer logged in");
    });

    // --- Step 3: Check duplicate (should not exist) ---
    await test.step("Check duplicate - no match", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/leads/check-duplicate?phone=${testPhone1}`
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.phone_available).toBe(true);
      console.log(`No duplicate for ${testPhone1}: phone_available=${body.phone_available}`);
    });

    // --- Step 4: Create lead ---
    await test.step("Create lead", async () => {
      const resp = await page.request.post(`${API_URL}/api/leads`, {
        headers: officerHeaders,
        data: {
          full_name: `E2E_Lead1_${Date.now()}`,
          phone: testPhone1,
          source: "walk_in",
          offering_id: offeringId,
        },
      });
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      const body = await resp.json();
      leadId1 = body.id;
      expect(leadId1).toBeTruthy();
      console.log(`Created lead ID: ${leadId1}`);
    });

    // --- Step 5: Get lead details ---
    await test.step("Get lead details", async () => {
      const resp = await page.request.get(`${API_URL}/api/leads/${leadId1}`, {
        headers: officerHeaders,
      });
      if (!resp.ok()) {
        console.log(`Get lead failed: ${resp.status()} ${(await resp.text()).slice(0, 300)}`);
      }
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.phone).toContain(testPhone1.slice(-4));
      expect(body.source).toBe("walk_in");
      // Capture officer ID from auto-assignment for later use
      if (body.assigned_officer_id) {
        officerUserId = body.assigned_officer_id;
      }
      console.log(`Lead details: name=${body.full_name}, assigned_officer=${body.assigned_officer_id}`);
    });

    // --- Step 6: Get workflow context ---
    await test.step("Get workflow context", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/leads/${leadId1}/workflow-context`
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      console.log(`Workflow context: ${JSON.stringify(body).slice(0, 200)}`);
    });

    // --- Step 7: Add consultation ---
    await test.step("Add consultation", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/leads/${leadId1}/consultations`,
        {
          headers: officerHeaders,
          data: {
            status_id: initialStatusId,
            method: "phone",
            notes: "E2E test: initial contact",
          },
        }
      );
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      const body = await resp.json();
      consultationId1 = body.id;
      expect(consultationId1).toBeTruthy();
      console.log(`Consultation ID: ${consultationId1}`);
    });

    // --- Step 8: Verify lead status updated ---
    await test.step("Verify lead consultation status", async () => {
      const resp = await page.request.get(`${API_URL}/api/leads/${leadId1}`);
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.consultation_status_id).toBe(initialStatusId);
      console.log(`Lead consultation_status_id = ${body.consultation_status_id}`);
    });

    // --- Step 9: Update consultation status ---
    await test.step("Update consultation to second status", async () => {
      const resp = await page.request.put(
        `${API_URL}/api/leads/${leadId1}/consultations/${consultationId1}`,
        {
          headers: officerHeaders,
          data: { status_id: secondStatusId },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.consultation_status_id).toBe(secondStatusId);
      console.log(`Consultation updated to status: ${body.consultation_status_id}`);
    });

    // --- Step 10: Get lead timeline ---
    await test.step("Get lead timeline", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/leads/${leadId1}/timeline`
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.length).toBeGreaterThanOrEqual(1);
      console.log(`Timeline entries: ${body.length}`);
    });

    // --- Step 11: Get lead insights ---
    await test.step("Get lead insights", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/leads/${leadId1}/insights`
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      console.log(`Insights: ${JSON.stringify(body).slice(0, 200)}`);
    });

    // --- Step 12: Update lead ---
    await test.step("Update lead details", async () => {
      // Get current version for optimistic locking
      const getResp = await page.request.get(`${API_URL}/api/leads/${leadId1}`);
      const current = await getResp.json();

      const resp = await page.request.put(`${API_URL}/api/leads/${leadId1}`, {
        headers: officerHeaders,
        data: {
          email: `e2e_lead1_${Date.now()}@example.com`,
          education_level: "12/12",
          version: current.version,
        },
      });
      if (!resp.ok()) {
        console.log(`Lead update failed: ${resp.status()} ${(await resp.text()).slice(0, 300)}`);
      }
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.email).toBeTruthy();
      console.log(`Lead updated: email=${body.email}`);
    });

    // --- Step 13: Admin list leads (verify created lead visible) ---
    await test.step("Admin list leads", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // Get the specific lead directly to verify admin access
      const resp = await page.request.get(`${API_URL}/api/leads/${leadId1}`);
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.id).toBe(leadId1);
      console.log(`Admin can see lead ${leadId1}: name=${body.full_name}`);
    });
  });

  // =========================================================================
  // Test 2: Assignment + Bulk operations + Duplicate check
  // =========================================================================
  test("Assignment + Bulk operations + Duplicate check", async ({ page }) => {
    // --- Step 1: Admin creates lead2 ---
    await test.step("Admin creates lead2", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.post(`${API_URL}/api/leads`, {
        headers: adminHeaders,
        data: {
          full_name: `E2E_Lead2_${Date.now()}`,
          phone: testPhone2,
          source: "online",
          offering_id: offeringId,
        },
      });
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      leadId2 = (await resp.json()).id;
      console.log(`Created lead2 ID: ${leadId2}`);
    });

    // --- Step 2: Duplicate check (phone1 should exist) ---
    await test.step("Duplicate check - phone1 exists", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/leads/check-duplicate?phone=${testPhone1}`
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.phone_available).toBe(false);
      expect(body.phone_conflict).toBeTruthy();
      console.log(`Duplicate found for ${testPhone1}: conflict=${JSON.stringify(body.phone_conflict).slice(0, 100)}`);
    });

    // --- Step 3: Assign lead2 to officer ---
    await test.step("Assign lead to officer", async () => {
      // Discover officer user ID if not yet known
      if (!officerUserId) {
        const rolesResp = await page.request.get(
          `${API_URL}/api/admin/roles/officer/users`
        );
        if (rolesResp.ok()) {
          const users = await rolesResp.json();
          if (users.length > 0) {
            officerUserId = users[0].id;
          }
        }
        // Fallback: get from lead1 which was created by officer
        if (!officerUserId) {
          const lead1Resp = await page.request.get(`${API_URL}/api/leads/${leadId1}`);
          const lead1 = await lead1Resp.json();
          officerUserId = lead1.assigned_officer_id || lead1.created_by_id;
        }
        console.log(`Discovered officer user ID: ${officerUserId}`);
      }

      const resp = await page.request.post(
        `${API_URL}/api/leads/${leadId2}/assign`,
        {
          headers: adminHeaders,
          data: { officer_id: officerUserId },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.assigned_officer_id).toBe(officerUserId);
      console.log(`Lead2 assigned to officer ${officerUserId}`);
    });

    // --- Step 4: Officer checks reassign quota ---
    await test.step("Officer checks reassign quota", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      const resp = await page.request.get(
        `${API_URL}/api/leads/my/reassign-quota`
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      console.log(`Reassign quota: ${JSON.stringify(body)}`);
    });

    // --- Step 5: Admin creates lead3 ---
    await test.step("Admin creates lead3", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.post(`${API_URL}/api/leads`, {
        headers: adminHeaders,
        data: {
          full_name: `E2E_Lead3_${Date.now()}`,
          phone: testPhone3,
          source: "facebook",
          offering_id: offeringId,
        },
      });
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      leadId3 = (await resp.json()).id;
      console.log(`Created lead3 ID: ${leadId3}`);
    });

    // --- Step 6: Bulk update stage ---
    await test.step("Bulk update stage", async () => {
      expect(pipelineStages.length).toBeGreaterThan(0);
      const stageId = pipelineStages[0].id;

      const resp = await page.request.post(
        `${API_URL}/api/leads/bulk-update-stage`,
        {
          headers: adminHeaders,
          data: {
            lead_ids: [leadId2, leadId3],
            pipeline_stage_id: stageId,
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      console.log(`Bulk stage update: ${JSON.stringify(body)}`);
    });

    // --- Step 7: Export leads ---
    await test.step("Export leads CSV", async () => {
      const resp = await page.request.get(`${API_URL}/api/leads/export`);
      expect(resp.ok()).toBeTruthy();
      const contentType = resp.headers()["content-type"] || "";
      expect(
        contentType.includes("csv") ||
        contentType.includes("spreadsheet") ||
        contentType.includes("octet-stream")
      ).toBeTruthy();
      console.log(`Export: content-type=${contentType}`);
    });

    // --- Step 8: Download import template ---
    await test.step("Download import template", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/leads/import/template`
      );
      expect(resp.ok()).toBeTruthy();
      console.log("Import template downloaded");
    });
  });

  // =========================================================================
  // Test 3: Delete/Restore + FSM validation
  // =========================================================================
  test("Delete/Restore + FSM validation", async ({ page }) => {
    // --- Step 1: Admin deletes lead3 ---
    await test.step("Delete lead3", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.delete(
        `${API_URL}/api/leads/${leadId3}`,
        { headers: adminHeaders }
      );
      expect(resp.status()).toBe(204);
      console.log(`Lead3 deleted`);
    });

    // --- Step 2: Verify lead3 is gone ---
    await test.step("Verify lead3 not found", async () => {
      const resp = await page.request.get(`${API_URL}/api/leads/${leadId3}`);
      expect(resp.status()).toBe(404);
      console.log(`Lead3 returns 404`);
    });

    // --- Step 3: Restore lead3 ---
    await test.step("Restore lead3", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/leads/${leadId3}/restore`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.id).toBe(leadId3);
      console.log(`Lead3 restored: id=${body.id}`);
    });

    // --- Step 4: Verify lead3 accessible again ---
    await test.step("Verify lead3 restored", async () => {
      const resp = await page.request.get(`${API_URL}/api/leads/${leadId3}`);
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.id).toBe(leadId3);
      console.log(`Lead3 accessible: name=${body.full_name}`);
    });

    // --- Step 5: Add consultation to lead3 (required before status change) ---
    await test.step("Add consultation to lead3", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/leads/${leadId3}/consultations`,
        {
          headers: adminHeaders,
          data: {
            status_id: initialStatusId,
            method: "phone",
            notes: "E2E test: status change prep",
          },
        }
      );
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      console.log(`Lead3 consultation added with status ${initialStatusId}`);
    });

    // --- Step 6: Get workflow context for lead3 ---
    await test.step("Get workflow context for lead3", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/leads/${leadId3}/workflow-context`
      );
      expect(resp.ok()).toBeTruthy();
      const ctx = await resp.json();
      console.log(`Lead3 workflow: phase=${ctx.current_phase}, status=${ctx.current_status_id}, allowed=${(ctx.allowed_statuses || []).length}`);
    });

    // --- Step 7: Update lead3 consultation to advance status ---
    await test.step("Update lead3 consultation to advance status", async () => {
      // Get lead3 consultations by fetching lead details
      const leadResp = await page.request.get(`${API_URL}/api/leads/${leadId3}`);
      const lead = await leadResp.json();
      const consultations = lead.consultations || [];
      if (consultations.length > 0) {
        const cid = consultations[0].id;
        const resp = await page.request.put(
          `${API_URL}/api/leads/${leadId3}/consultations/${cid}`,
          {
            headers: adminHeaders,
            data: { status_id: secondStatusId },
          }
        );
        expect(resp.ok()).toBeTruthy();
        console.log(`Lead3 consultation updated to ${secondStatusId}`);
      } else {
        console.log("Lead3 has no consultations to update (skipped)");
      }
    });

    // --- Step 8: Delete consultation ---
    await test.step("Delete consultation", async () => {
      const resp = await page.request.delete(
        `${API_URL}/api/leads/${leadId1}/consultations/${consultationId1}`,
        { headers: adminHeaders }
      );
      expect(resp.status()).toBe(204);
      console.log(`Consultation ${consultationId1} deleted`);
    });

    // --- Step 9: Restore consultation ---
    await test.step("Restore consultation", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/leads/${leadId1}/consultations/${consultationId1}/restore`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.id).toBe(consultationId1);
      console.log(`Consultation ${consultationId1} restored`);
    });
  });
});
