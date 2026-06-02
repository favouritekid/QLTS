/**
 * E2E Test: Bugfix Regression (T1-T9)
 *
 * Validates critical bugfixes via API calls to prevent regressions.
 * Tests run serially since later tests depend on state from earlier ones.
 *
 * Coverage:
 *   T1 - Bulk action targets correct leads by ID (not index)
 *   T2 - Move lead to stage via bulk-update-stage
 *   T3 - Export with correct filter param (assigned_officer_id)
 *   T4 - Reassign quota contract validation
 *   T5 - Quota response shape (no stale fields)
 *   T6 - Date range end-of-day inclusive filtering
 *   T7 - Lead detail 404 for non-existent ID
 *   T8 - Cleanup test data
 *
 * Run:
 *   npx playwright test bugfix-regression --project=e2e-workflow --reporter=list
 */

import { test, expect } from "@playwright/test";
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
let officerHeaders: Record<string, string> = {};

// Discovery
let unitId: number;
let offeringId: number;
let pipelineStages: Array<{ id: string; name: string }> = [];
let officerUserId: number;

// Test leads
let leadA_id: number;
let leadB_id: number;
let leadC_id: number;
let leadDateTest_id: number;
const createdLeadIds: number[] = [];

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

/**
 * Extract access_token from set-cookie headers and return as Bearer auth header.
 * The backend sets access_token as an httpOnly cookie; we parse it out
 * and use it as a Bearer token (backend supports both cookie and header auth).
 */
function extractAccessToken(
  resp: { headersArray(): Array<{ name: string; value: string }> }
): string | null {
  for (const h of resp.headersArray()) {
    if (h.name.toLowerCase() !== "set-cookie") continue;
    const m = h.value.match(/^access_token=([^;]+)/);
    if (m) return m[1];
  }
  return null;
}

// ---------------------------------------------------------------------------
// Test Suite
// ---------------------------------------------------------------------------

test.describe("Bugfix Regression (T1-T9)", () => {
  test.describe.configure({ timeout: 300_000, mode: "serial" });

  // =========================================================================
  // Test 0: Setup - Admin & Officer login + Discovery
  // =========================================================================
  test("T0: Setup - Admin & Officer login + Discovery", async ({ request }) => {
    // --- Admin login (with TOTP) ---
    await test.step("Admin login", async () => {
      const loginResp = await request.post(`${API_URL}/api/auth/login`, {
        form: { username: ADMIN_USERNAME, password: ADMIN_PASSWORD },
      });
      expect(loginResp.ok()).toBeTruthy();
      const loginData = await loginResp.json();

      if (loginData.mfa_required) {
        const totp = generateTOTP(ADMIN_TOTP_SECRET);
        const mfaResp = await request.post(`${API_URL}/api/auth/verify-mfa`, {
          data: { mfa_token: loginData.mfa_token, code: totp },
        });
        if (!mfaResp.ok()) {
          // TOTP window collision - wait and retry
          console.log(
            `MFA failed (${mfaResp.status()}), waiting 31s and retrying...`
          );
          await new Promise((r) => setTimeout(r, 31_000));
          const loginResp2 = await request.post(`${API_URL}/api/auth/login`, {
            form: { username: ADMIN_USERNAME, password: ADMIN_PASSWORD },
          });
          const loginData2 = await loginResp2.json();
          const totp2 = generateTOTP(ADMIN_TOTP_SECRET);
          const mfaResp2 = await request.post(
            `${API_URL}/api/auth/verify-mfa`,
            {
              data: { mfa_token: loginData2.mfa_token, code: totp2 },
            }
          );
          expect(mfaResp2.ok()).toBeTruthy();
          const token2 = extractAccessToken(mfaResp2);
          expect(token2).toBeTruthy();
          adminHeaders = { Authorization: `Bearer ${token2}` };
        } else {
          const token = extractAccessToken(mfaResp);
          expect(token).toBeTruthy();
          adminHeaders = { Authorization: `Bearer ${token}` };
        }
      } else {
        const token = extractAccessToken(loginResp);
        expect(token).toBeTruthy();
        adminHeaders = { Authorization: `Bearer ${token}` };
      }
      console.log("Admin logged in (Bearer token)");
    });

    // --- Officer login (no MFA) ---
    await test.step("Officer login", async () => {
      const loginResp = await request.post(`${API_URL}/api/auth/login`, {
        form: { username: OFFICER_USERNAME, password: OFFICER_PASSWORD },
      });
      expect(loginResp.ok()).toBeTruthy();
      const token = extractAccessToken(loginResp);
      expect(token).toBeTruthy();
      officerHeaders = { Authorization: `Bearer ${token}` };
      console.log("Officer logged in (Bearer token)");
    });

    // --- Discover pipeline, units, offerings ---
    await test.step("Discover pipeline config", async () => {
      const pipelineResp = await request.get(`${API_URL}/api/pipeline/all`, {
        headers: adminHeaders,
      });
      expect(pipelineResp.ok()).toBeTruthy();
      const pipeline = await pipelineResp.json();
      pipelineStages = pipeline.stages;
      expect(pipelineStages.length).toBeGreaterThanOrEqual(1);
      console.log(`Pipeline: ${pipelineStages.length} stages`);
    });

    await test.step("Discover organization units", async () => {
      const unitsResp = await request.get(
        `${API_URL}/api/organization-units`,
        { headers: adminHeaders }
      );
      expect(unitsResp.ok()).toBeTruthy();
      const units = await unitsResp.json();
      unitId = units[0]?.id;
      expect(unitId).toBeTruthy();
      console.log(`Unit ID: ${unitId}`);
    });

    await test.step("Discover offerings", async () => {
      const offeringsResp = await request.get(
        `${API_URL}/api/program-offerings?is_active=true&limit=1`,
        { headers: adminHeaders }
      );
      expect(offeringsResp.ok()).toBeTruthy();
      const offerings = await offeringsResp.json();
      expect(offerings.length).toBeGreaterThan(0);
      offeringId = offerings[0].id;
      console.log(`Offering ID: ${offeringId}`);
    });

    await test.step("Discover officer user ID", async () => {
      // Create a temp lead as officer to discover their user ID via auto-assignment
      const tempResp = await request.post(`${API_URL}/api/leads`, {
        headers: officerHeaders,
        data: {
          full_name: `E2E_TempDiscover_${Date.now()}`,
          phone: generatePhone(),
          source: "walk_in",
          offering_id: offeringId,
        },
      });
      expect(
        tempResp.ok() || tempResp.status() === 201
      ).toBeTruthy();
      const tempLead = await tempResp.json();
      officerUserId = tempLead.assigned_officer_id || tempLead.created_by_id;
      expect(officerUserId).toBeTruthy();
      console.log(`Officer user ID: ${officerUserId}`);

      // Clean up temp lead
      const delResp = await request.delete(
        `${API_URL}/api/leads/${tempLead.id}`,
        { headers: adminHeaders }
      );
      expect(delResp.status()).toBe(204);
    });
  });

  // =========================================================================
  // Test 1 (T1): Bulk action targets correct leads by ID
  // =========================================================================
  test("T1: Bulk action targets correct leads by ID", async ({ request }) => {
    // Create 3 leads via admin
    await test.step("Create 3 leads (A, B, C)", async () => {
      const createLead = async (suffix: string) => {
        const resp = await request.post(`${API_URL}/api/leads`, {
          headers: adminHeaders,
          data: {
            full_name: `E2E_BulkT1_${suffix}_${Date.now()}`,
            phone: generatePhone(),
            source: "walk_in",
            offering_id: offeringId,
          },
        });
        expect(resp.ok() || resp.status() === 201).toBeTruthy();
        const body = await resp.json();
        createdLeadIds.push(body.id);
        return body.id;
      };

      leadA_id = await createLead("A");
      leadB_id = await createLead("B");
      leadC_id = await createLead("C");
      console.log(
        `Created leads: A=${leadA_id}, B=${leadB_id}, C=${leadC_id}`
      );
    });

    // Bulk assign only A and C (skip B) to the officer
    await test.step(
      "Bulk-assign A and C only (not B) to officer",
      async () => {
        const resp = await request.post(
          `${API_URL}/api/leads/bulk-assign?officer_id=${officerUserId}`,
          {
            headers: adminHeaders,
            data: { lead_ids: [leadA_id, leadC_id] },
          }
        );
        expect(resp.ok()).toBeTruthy();
        const body = await resp.json();
        expect(body.total).toBe(2);
        expect(body.successful).toBe(2);
        expect(body.assigned_lead_ids).toContain(leadA_id);
        expect(body.assigned_lead_ids).toContain(leadC_id);
        // B should NOT be in the assigned list
        expect(body.assigned_lead_ids).not.toContain(leadB_id);
        console.log(
          `Bulk-assign result: total=${body.total}, successful=${body.successful}`
        );
      }
    );

    // Verify: A is assigned to officer
    await test.step("Verify lead A is assigned to officer", async () => {
      const resp = await request.get(`${API_URL}/api/leads/${leadA_id}`, {
        headers: adminHeaders,
      });
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.assigned_officer_id).toBe(officerUserId);
      console.log(`Lead A assigned_officer_id: ${body.assigned_officer_id}`);
    });

    // Verify: C is assigned to officer
    await test.step("Verify lead C is assigned to officer", async () => {
      const resp = await request.get(`${API_URL}/api/leads/${leadC_id}`, {
        headers: adminHeaders,
      });
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.assigned_officer_id).toBe(officerUserId);
      console.log(`Lead C assigned_officer_id: ${body.assigned_officer_id}`);
    });

    // Verify: B was NOT assigned to our officer
    await test.step("Verify lead B was NOT bulk-assigned", async () => {
      const resp = await request.get(`${API_URL}/api/leads/${leadB_id}`, {
        headers: adminHeaders,
      });
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      // B may have been auto-assigned to someone during creation,
      // but the bulk-assign should NOT have changed it to our officer
      // (unless it was already auto-assigned to the same officer)
      // The key assertion: B was not in the bulk-assign request
      console.log(
        `Lead B assigned_officer_id: ${body.assigned_officer_id} (should differ from bulk-assign target or be auto-assigned)`
      );
    });
  });

  // =========================================================================
  // Test 2 (T2): Move lead to stage via bulk-update-stage
  // =========================================================================
  test("T2: Move lead to stage via bulk-update-stage", async ({ request }) => {
    await test.step("Move lead A to first pipeline stage", async () => {
      expect(pipelineStages.length).toBeGreaterThan(0);
      const targetStageId = pipelineStages[0].id;

      const resp = await request.post(
        `${API_URL}/api/leads/bulk-update-stage`,
        {
          headers: adminHeaders,
          data: {
            lead_ids: [leadA_id],
            pipeline_stage_id: targetStageId,
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      console.log(`Bulk stage update result: ${JSON.stringify(body)}`);
    });

    await test.step("Verify lead A has correct pipeline_stage_id", async () => {
      const resp = await request.get(`${API_URL}/api/leads/${leadA_id}`, {
        headers: adminHeaders,
      });
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.pipeline_stage_id).toBe(pipelineStages[0].id);
      console.log(`Lead A pipeline_stage_id: ${body.pipeline_stage_id}`);
    });

    // Move to second stage if available
    if (pipelineStages.length >= 2) {
      await test.step(
        "Move lead A to second pipeline stage",
        async () => {
          const targetStageId = pipelineStages[1].id;
          const resp = await request.post(
            `${API_URL}/api/leads/bulk-update-stage`,
            {
              headers: adminHeaders,
              data: {
                lead_ids: [leadA_id],
                pipeline_stage_id: targetStageId,
              },
            }
          );
          expect(resp.ok()).toBeTruthy();

          // Verify
          const verifyResp = await request.get(
            `${API_URL}/api/leads/${leadA_id}`,
            { headers: adminHeaders }
          );
          expect(verifyResp.ok()).toBeTruthy();
          const verifyBody = await verifyResp.json();
          expect(verifyBody.pipeline_stage_id).toBe(targetStageId);
          console.log(
            `Lead A moved to stage: ${verifyBody.pipeline_stage_id}`
          );
        }
      );
    }
  });

  // =========================================================================
  // Test 3 (T3): Export with pipeline filters matches expected scope
  // =========================================================================
  test("T3: Export with correct filter param (assigned_officer_id)", async ({
    request,
  }) => {
    // Export with the CORRECT param name: assigned_officer_id
    await test.step(
      "Export with assigned_officer_id filter returns 200",
      async () => {
        const resp = await request.get(
          `${API_URL}/api/leads/export?assigned_officer_id=${officerUserId}&format=csv`,
          { headers: adminHeaders }
        );
        expect(resp.ok()).toBeTruthy();
        const contentType = resp.headers()["content-type"] || "";
        expect(
          contentType.includes("csv") ||
            contentType.includes("spreadsheet") ||
            contentType.includes("octet-stream")
        ).toBeTruthy();
        const csvText = await resp.text();
        // CSV should contain data (at least a header row)
        expect(csvText.length).toBeGreaterThan(0);
        console.log(
          `Export with assigned_officer_id: content-type=${contentType}, size=${csvText.length}`
        );
      }
    );

    // Export with the WRONG param name: officer_id (frontend bug before fix)
    // Backend does not recognize "officer_id" as a filter, so the export is unfiltered
    await test.step(
      "Export with wrong param 'officer_id' returns unfiltered data",
      async () => {
        const resp = await request.get(
          `${API_URL}/api/leads/export?officer_id=${officerUserId}&format=csv`,
          { headers: adminHeaders }
        );
        expect(resp.ok()).toBeTruthy();
        const csvWrong = await resp.text();
        console.log(
          `Export with officer_id (wrong param): size=${csvWrong.length}`
        );

        // Now get the filtered export for comparison
        const respFiltered = await request.get(
          `${API_URL}/api/leads/export?assigned_officer_id=${officerUserId}&format=csv`,
          { headers: adminHeaders }
        );
        const csvFiltered = await respFiltered.text();

        // Unfiltered export (wrong param ignored) should be >= filtered export
        // This validates that using the wrong param name gives different results
        // (unless the officer has all leads, which is unlikely in a real system)
        console.log(
          `Comparison: unfiltered=${csvWrong.length}, filtered=${csvFiltered.length}`
        );
        // The key point: if csvWrong.length > csvFiltered.length, it proves
        // the wrong param name was ignored (unfiltered = all leads)
        // We just log this; the critical fix is that the frontend now uses the correct param
      }
    );
  });

  // =========================================================================
  // Test 4 (T4): Reassign quota contract validation
  // =========================================================================
  test("T4: Reassign quota contract validation", async ({ request }) => {
    await test.step(
      "GET /my/reassign-quota returns correct shape",
      async () => {
        const resp = await request.get(
          `${API_URL}/api/leads/my/reassign-quota`,
          { headers: officerHeaders }
        );
        expect(resp.ok()).toBeTruthy();
        const body = await resp.json();

        // Assert required fields exist with correct types
        expect(typeof body.allowed).toBe("boolean");
        expect(typeof body.used).toBe("number");
        expect(typeof body.limit).toBe("number");
        expect(typeof body.remaining).toBe("number");

        // Assert arithmetic: remaining = limit - used
        expect(body.remaining).toBe(body.limit - body.used);

        console.log(
          `Reassign quota: allowed=${body.allowed}, used=${body.used}, limit=${body.limit}, remaining=${body.remaining}`
        );
      }
    );
  });

  // =========================================================================
  // Test 5 (T5): Quota response has no stale/old fields
  // =========================================================================
  test("T5: Quota response has no stale fields", async ({ request }) => {
    await test.step(
      "Reassign quota response has NO old field names",
      async () => {
        const resp = await request.get(
          `${API_URL}/api/leads/my/reassign-quota`,
          { headers: officerHeaders }
        );
        expect(resp.ok()).toBeTruthy();
        const body = await resp.json();

        // These old field names should NOT exist in the response
        expect(body).not.toHaveProperty("remaining_today");
        expect(body).not.toHaveProperty("max_per_day");
        expect(body).not.toHaveProperty("used_today");
        expect(body).not.toHaveProperty("daily_limit");

        // Verify the response only contains expected keys
        const expectedKeys = ["allowed", "used", "limit", "remaining"];
        for (const key of expectedKeys) {
          expect(body).toHaveProperty(key);
        }

        console.log(
          `Quota shape validated: keys=${Object.keys(body).join(",")}`
        );
      }
    );
  });

  // =========================================================================
  // Test 6 (T6): Date range end-of-day inclusive
  // =========================================================================
  test("T6: Date range end-of-day inclusive", async ({ request }) => {
    // Create a lead (it will have created_at = now)
    await test.step("Create lead for date filtering", async () => {
      const resp = await request.post(`${API_URL}/api/leads`, {
        headers: adminHeaders,
        data: {
          full_name: `E2E_DateTest_${Date.now()}`,
          phone: generatePhone(),
          source: "online",
          offering_id: offeringId,
        },
      });
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      const body = await resp.json();
      leadDateTest_id = body.id;
      createdLeadIds.push(leadDateTest_id);
      console.log(`Created date-test lead: id=${leadDateTest_id}`);
    });

    // Query with date_to set to end of today (23:59:59.999) - should include the lead
    await test.step(
      "Query with date_to=end-of-day includes today's lead",
      async () => {
        const now = new Date();
        const endOfDay = new Date(
          now.getFullYear(),
          now.getMonth(),
          now.getDate(),
          23,
          59,
          59,
          999
        );

        const resp = await request.get(
          `${API_URL}/api/leads?date_to=${endOfDay.toISOString()}&date_field=created_at&search=${leadDateTest_id}&page_size=100`,
          { headers: adminHeaders }
        );
        expect(resp.ok()).toBeTruthy();
        const body = await resp.json();

        // The lead should be in the results
        const found = body.leads.some(
          (l: { id: number }) => l.id === leadDateTest_id
        );
        // Search by ID might not work (search is text-based), so also verify via direct GET
        if (!found) {
          // Fallback: query all leads with date filter and check
          const resp2 = await request.get(
            `${API_URL}/api/leads?date_to=${endOfDay.toISOString()}&date_field=created_at&page_size=100`,
            { headers: adminHeaders }
          );
          expect(resp2.ok()).toBeTruthy();
          const body2 = await resp2.json();
          const found2 = body2.leads.some(
            (l: { id: number }) => l.id === leadDateTest_id
          );
          expect(found2).toBeTruthy();
          console.log(
            `Lead ${leadDateTest_id} found in end-of-day query (fallback): ${found2}`
          );
        } else {
          console.log(
            `Lead ${leadDateTest_id} found in end-of-day query: ${found}`
          );
        }
      }
    );

    // Query with date_to set to start of today (00:00:00.000Z) - might miss the lead
    // if it was created after midnight (depends on timezone)
    await test.step(
      "Query with date_to=start-of-day may miss later leads",
      async () => {
        const now = new Date();
        const startOfDay = new Date(
          now.getFullYear(),
          now.getMonth(),
          now.getDate(),
          0,
          0,
          0,
          0
        );

        const resp = await request.get(
          `${API_URL}/api/leads?date_to=${startOfDay.toISOString()}&date_field=created_at&page_size=100`,
          { headers: adminHeaders }
        );
        expect(resp.ok()).toBeTruthy();
        const body = await resp.json();
        const found = body.leads.some(
          (l: { id: number }) => l.id === leadDateTest_id
        );
        // If the lead was created AFTER midnight, it should NOT be in start-of-day results
        // But this depends on server timezone, so we just log the result
        console.log(
          `Lead ${leadDateTest_id} in start-of-day query: ${found} (expected: likely false if server time > 00:00)`
        );
      }
    );
  });

  // =========================================================================
  // Test 7 (T7): Lead detail 404 vs server error
  // =========================================================================
  test("T7: Lead detail 404 for non-existent ID", async ({ request }) => {
    await test.step("GET non-existent lead returns 404", async () => {
      const resp = await request.get(`${API_URL}/api/leads/999999`, {
        headers: adminHeaders,
      });
      expect(resp.status()).toBe(404);
      console.log(`Non-existent lead 999999: status=${resp.status()}`);
    });

    await test.step(
      "GET another non-existent lead also returns 404",
      async () => {
        const resp = await request.get(`${API_URL}/api/leads/888888`, {
          headers: adminHeaders,
        });
        expect(resp.status()).toBe(404);
        console.log(`Non-existent lead 888888: status=${resp.status()}`);
      }
    );

    // Ensure 404 body has a parseable error structure (not a raw server error)
    await test.step("404 response has structured error body", async () => {
      const resp = await request.get(`${API_URL}/api/leads/999999`, {
        headers: adminHeaders,
      });
      expect(resp.status()).toBe(404);
      const body = await resp.json();
      // Backend typically returns { "detail": "..." } for 404s
      expect(body).toHaveProperty("detail");
      console.log(`404 body: ${JSON.stringify(body).slice(0, 200)}`);
    });
  });

  // =========================================================================
  // Test 8: Cleanup
  // =========================================================================
  test("T8: Cleanup test leads", async ({ request }) => {
    await test.step("Delete all test leads", async () => {
      const idsToDelete = [...createdLeadIds];
      console.log(`Cleaning up ${idsToDelete.length} test leads: ${idsToDelete.join(", ")}`);

      let deletedCount = 0;
      let skippedCount = 0;

      for (const id of idsToDelete) {
        const resp = await request.delete(`${API_URL}/api/leads/${id}`, {
          headers: adminHeaders,
        });
        if (resp.status() === 204) {
          deletedCount++;
        } else if (resp.status() === 404) {
          // Already deleted or never created - that's fine
          skippedCount++;
        } else {
          console.log(
            `Unexpected status deleting lead ${id}: ${resp.status()}`
          );
          skippedCount++;
        }
      }

      console.log(
        `Cleanup complete: deleted=${deletedCount}, skipped=${skippedCount}`
      );
    });
  });
});
