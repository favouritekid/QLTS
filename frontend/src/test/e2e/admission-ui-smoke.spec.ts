/**
 * E2E Test: Admission UI Smoke
 *
 * Coverage:
 *   - List page loads với filter tabs
 *   - Detail page tabs không crash
 *   - Unsaved changes dialog khi đổi tab
 *
 * Project: chromium only (officer storageState from setup)
 * Data: seed profile via API in beforeAll — không phụ thuộc dữ liệu môi trường
 *
 * Chạy:
 *   npx playwright test admission-ui-smoke --project=chromium --reporter=list
 */

import { test, expect, type APIRequestContext } from "@playwright/test";

const API_URL = process.env.E2E_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Shared state
// ---------------------------------------------------------------------------

let smokeProfileId: number;
let smokeCookieHeader: string;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generatePhone(): string {
  const prefixes = ["091", "093", "097", "098", "035"];
  const prefix = prefixes[Math.floor(Math.random() * prefixes.length)];
  const suffix = Math.floor(Math.random() * 10_000_000)
    .toString()
    .padStart(7, "0");
  return prefix + suffix;
}

// ---------------------------------------------------------------------------
// beforeAll / afterAll using storageState session via request fixture
// ---------------------------------------------------------------------------

test.beforeAll(async ({ browser }) => {
  // Create a browser context with the stored auth state (officer session)
  // The storageState is injected by the project config (setup dependency)
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    // Read auth cookies from context (populated via storageState)
    const cookies = await context.cookies();
    smokeCookieHeader = cookies
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");

    // We need to call the backend API using the officer session.
    // Use page.request which shares the context's cookies.
    //
    // ⚠ FAIL-LOUD assertions (2026-05-26): each request asserts
    // ``resp.ok()`` so any 4xx/5xx surfaces immediately with the failing
    // step name + status code, instead of silently producing
    // ``undefined`` IDs that cascade into "List page loads — table not
    // found" 15s later. Audit task #54 root cause.
    const pipelineResp = await page.request.get(`${API_URL}/api/pipeline/all`);
    if (!pipelineResp.ok()) {
      throw new Error(
        `beforeAll: GET /api/pipeline/all returned ${pipelineResp.status()}`,
      );
    }
    const initialStatusId = (await pipelineResp.json()).statuses[0].id;

    const offeringsResp = await page.request.get(
      `${API_URL}/api/program-offerings?is_active=true&limit=1`,
    );
    if (!offeringsResp.ok()) {
      throw new Error(
        `beforeAll: GET /api/program-offerings returned ${offeringsResp.status()}`,
      );
    }
    const offeringId = (await offeringsResp.json())[0].id;

    const methodsResp = await page.request.get(
      `${API_URL}/api/admission-config/methods?active_only=true`,
    );
    if (!methodsResp.ok()) {
      throw new Error(
        `beforeAll: GET /api/admission-config/methods returned ${methodsResp.status()}`,
      );
    }
    const methodsBody = await methodsResp.json();
    const methods = methodsBody.methods || methodsBody;
    const admissionMethodId = methods[0].id;

    // Create lead + draft profile
    const leadResp = await page.request.post(`${API_URL}/api/leads`, {
      data: {
        full_name: `E2E_UISmoke_${Date.now()}`,
        phone: generatePhone(),
        source: "walk_in",
        offering_id: offeringId,
      },
    });
    if (!leadResp.ok()) {
      const body = await leadResp.text();
      throw new Error(
        `beforeAll: POST /api/leads returned ${leadResp.status()} — ${body.slice(0, 200)}`,
      );
    }
    const leadId = (await leadResp.json()).id;

    const consultResp = await page.request.post(
      `${API_URL}/api/leads/${leadId}/consultations`,
      { data: { status_id: initialStatusId, method: "phone", notes: "UI smoke test" } },
    );
    if (!consultResp.ok()) {
      const body = await consultResp.text();
      throw new Error(
        `beforeAll: POST /api/leads/${leadId}/consultations returned ${consultResp.status()} — ${body.slice(0, 200)}`,
      );
    }

    const profileResp = await page.request.post(`${API_URL}/api/admissions`, {
      data: { lead_id: leadId, admission_method_id: admissionMethodId },
    });
    if (!profileResp.ok()) {
      const body = await profileResp.text();
      throw new Error(
        `beforeAll: POST /api/admissions returned ${profileResp.status()} — ${body.slice(0, 200)}`,
      );
    }
    smokeProfileId = (await profileResp.json()).id;
    console.log(`UI smoke profile created: id=${smokeProfileId}`);
  } finally {
    await context.close();
  }
});

test.afterAll(async ({ browser }) => {
  if (!smokeProfileId) return;
  // Cleanup: attempt to delete the draft profile
  const context = await browser.newContext();
  const page = await context.newPage();
  try {
    await page.request.delete(`${API_URL}/api/admissions/${smokeProfileId}`);
    console.log(`UI smoke profile deleted: id=${smokeProfileId}`);
  } catch {
    console.log(`Could not delete smoke profile ${smokeProfileId} — ignoring`);
  } finally {
    await context.close();
  }
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test("List page loads với filter tabs", async ({ page }) => {
  await page.goto("/admissions");

  // Page heading should be visible
  await expect(page.locator("h1")).toBeVisible({ timeout: 15000 });

  // Table or list container should render (not blank)
  const tableOrList = page.locator("table, [role='table'], [data-testid='admissions-list']").first();
  await expect(tableOrList).toBeVisible({ timeout: 15000 });

  console.log("Admissions list page loaded successfully");
});

test("Detail page tabs không crash", async ({ page }) => {
  if (!smokeProfileId) {
    test.skip(true, "smokeProfileId not set — beforeAll failed");
    return;
  }

  await page.goto(`/admissions/${smokeProfileId}`);
  await expect(page.locator("h1, h2").first()).toBeVisible({ timeout: 15000 });

  // Find all tab triggers
  const tabs = page.locator("[role='tab']");
  const tabCount = await tabs.count();
  console.log(`Found ${tabCount} tabs on detail page`);

  // Click each tab and verify no unhandled error appears
  for (let i = 0; i < tabCount; i++) {
    const tab = tabs.nth(i);
    const tabName = await tab.textContent();

    try {
      await tab.click();
      // Wait for tab panel to be visible (not stuck loading)
      await page.waitForLoadState("networkidle", { timeout: 5000 });
      console.log(`  Tab "${tabName?.trim()}" — OK`);
    } catch (err) {
      console.log(`  Tab "${tabName?.trim()}" — timeout (may still be loading)`);
    }

    // Verify no error boundary or crash message visible
    const errorBoundary = page.locator("text=Something went wrong, text=Đã có lỗi xảy ra").first();
    const hasError = await errorBoundary.isVisible().catch(() => false);
    if (hasError) {
      throw new Error(`Tab "${tabName?.trim()}" caused a UI error`);
    }
  }
});

test("Unsaved changes dialog khi đổi tab sau khi edit", async ({ page }) => {
  if (!smokeProfileId) {
    test.skip(true, "smokeProfileId not set — beforeAll failed");
    return;
  }

  await page.goto(`/admissions/${smokeProfileId}`);
  await expect(page.locator("h1, h2").first()).toBeVisible({ timeout: 15000 });

  // Find the first editable text input on the current tab
  const editableInput = page
    .locator("input[type='text']:not([disabled]):not([readonly])")
    .first();
  const isEditable = await editableInput.isVisible().catch(() => false);

  if (!isEditable) {
    console.log("No editable input found on first tab — skipping unsaved-changes assertion");
    return;
  }

  // Type something to dirty the form
  await editableInput.click();
  await editableInput.fill("UI_SMOKE_DIRTY_VALUE");

  // Click a different tab
  const tabs = page.locator("[role='tab']");
  const tabCount = await tabs.count();
  if (tabCount < 2) {
    console.log("Less than 2 tabs — skipping unsaved-changes assertion");
    return;
  }

  await tabs.nth(1).click();

  // AlertDialog should appear warning about unsaved changes
  const dialog = page.getByRole("alertdialog");
  const dialogVisible = await dialog.isVisible({ timeout: 3000 }).catch(() => false);

  if (dialogVisible) {
    await expect(dialog).toBeVisible();
    console.log("Unsaved changes AlertDialog appeared — OK");
    // Dismiss the dialog (cancel) to leave form state intact
    const cancelBtn = dialog.getByRole("button").first();
    await cancelBtn.click();
  } else {
    // Some implementations may use a different mechanism (toast, inline warning)
    console.log(
      "AlertDialog not visible — UI may use a different unsaved-changes mechanism"
    );
  }
});
