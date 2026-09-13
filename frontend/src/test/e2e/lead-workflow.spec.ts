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
import {
  assertPrincipal,
  expectOk,
  listActiveOfficers,
  loginPrincipal,
  pickAssignableOfficer,
  safeBody,
  summarizeApiError,
  type Principal,
} from "./helpers/e2e-fixtures";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "Admin@123";
const ADMIN_TOTP_SECRET =
  process.env.E2E_ADMIN_TOTP_SECRET || "";

const OFFICER_USERNAME = process.env.E2E_OFFICER_USERNAME || "vothithuthuhien";
const OFFICER_PASSWORD = process.env.E2E_OFFICER_PASSWORD || "Abc@123456789";

const API_URL = process.env.E2E_API_URL || "http://localhost:8000";

const MANAGER_USERNAME = process.env.E2E_MANAGER_USERNAME || "";
const MANAGER_PASSWORD = process.env.E2E_MANAGER_PASSWORD || "";
const MANAGER_TOTP_SECRET = process.env.E2E_MANAGER_TOTP_SECRET || "";

// ---------------------------------------------------------------------------
// Shared state across tests (serial execution within describe)
// ---------------------------------------------------------------------------

let adminHeaders: Record<string, string> = {};
let adminCookies: Cookie[] = [];
let officerHeaders: Record<string, string> = {};
let officerCookies: Cookie[] = [];

// Discovery
/**
 * Đơn vị dùng cho MỌI lead mà admin tạo rồi giao cho officer của suite này.
 *
 * KHÔNG còn là `units[0].id`. `_assert_officer_in_lead_unit`
 * (`app/services/lead_service.py:2411-2423`) bắt buộc officer CÙNG đơn vị
 * với lead; lấy `units[0]` và `users[0]` rời rạc rồi giả định chúng khớp là
 * đúng cách nightly 34678745325 đỏ ở :517 — đo thật:
 *   POST /api/leads/{id}/assign → 400
 *   {"detail":"Không thể phân công: officer thuộc đơn vị #4, khác đơn vị
 *     của lead #1. Chỉ phân công officer cùng đơn vị.",
 *    "error_code":"BUSINESS_RULE_VIOLATION"}
 * và đơn vị #1 (phần tử đầu của `/api/organization-units`) KHÔNG có officer
 * active nào cả, nên không có cách nào chữa bằng việc đổi officer.
 *
 * Giá trị này đọc RA TỪ chính officer đang đăng nhập, nên cặp (đơn vị,
 * officer) luôn tương thích theo định nghĩa.
 */
let unitId: number;
let offeringId: number;
// `code` là định danh HỢP ĐỒNG (ràng buộc `uq_consultation_status_code UNIQUE`),
// khác `id` ở chỗ nó được lược đồ bảo đảm duy nhất và không phụ thuộc thứ tự hàng.
let pipelineStatuses: Array<{
  id: string;
  name: string;
  code?: string | null;
  is_final?: boolean;
}> = [];
let pipelineStages: Array<{ id: string; name: string }> = [];
let initialStatusId: string;
let secondStatusId: string;
let officerUserId: number;

// Leads
let leadId1: number; // happy path CRUD
let leadId2: number; // assignment/bulk
let leadId3: number; // delete/restore
let consultationId1: number;
let leadIdInaccessible: number; // IDOR bait (admin creates, unassigned)
let leadId4: number; // FSM status patch + officer action
const testPhone1 = generatePhone();
const testPhone2 = generatePhone();
const testPhone3 = generatePhone();

// Test 8: Business rule validations
let leadIdForLocking: number;
let finalNegativeStatusId: string | null = null;

// Test 9: Quota exhaustion
let quotaOfficerUsername: string;
let quotaOfficerHeaders: Record<string, string> = {};
let quotaOfficerCookies: Cookie[] = [];
let quotaOfficerUserId: number;
const quotaLeadIds: number[] = [];

// Test 10: Manager IDOR
let managerHeaders: Record<string, string> = {};
let managerCookies: Cookie[] = [];
let unitBId: number;
/** Đơn vị của CHÍNH manager — phạm vi thật của họ (lead_service.py:3736). */
let managerUnitId: number;

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
      const body = summarizeApiError(loginResp.status(), await loginResp.text());
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

/** Build a multipart/form-data body for file upload, returning raw Buffer + Content-Type header.
 *  Playwright's built-in `multipart` option sometimes drops custom headers (e.g. X-CSRF-Token).
 *  Using raw Buffer with `data` ensures all headers (including CSRF) are sent correctly.
 */
function buildMultipartFile(
  fieldName: string,
  filename: string,
  mimeType: string,
  content: string
): { body: Buffer; contentType: string } {
  const boundary = `----E2EBoundary${Date.now()}`;
  const body = Buffer.concat([
    Buffer.from(
      `--${boundary}\r\nContent-Disposition: form-data; name="${fieldName}"; filename="${filename}"\r\nContent-Type: ${mimeType}\r\n\r\n`
    ),
    Buffer.from(content, "utf-8"),
    Buffer.from(`\r\n--${boundary}--\r\n`),
  ]);
  return { body, contentType: `multipart/form-data; boundary=${boundary}` };
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
      expect(pipelineStatuses.length).toBeGreaterThanOrEqual(2);

      // ---------------------------------------------------------------------
      // TRẠNG THÁI KHỞI TẠO — chọn theo ĐỊNH DANH HỢP ĐỒNG, không theo thứ tự
      // ---------------------------------------------------------------------
      // Bản cũ đọc `pipeline.allowed_transitions` rồi rơi về `statuses[0]/[1]`.
      // Hai sai lầm chồng lên nhau, cả hai đều ĐO ĐƯỢC:
      //
      //  1. `allowed_transitions` LUÔN rỗng. `/api/pipeline/all`
      //     (`app/routers/pipeline.py:39-48`) chỉ trả `{stages, statuses}`;
      //     trường kia có trong schema nhưng không ai điền. Nên nhánh fallback
      //     LUÔN được chọn — "nhánh dự phòng" thực chất là nhánh duy nhất.
      //
      //  2. `statuses[0]` KHÔNG xác định. `PipelineRepository.get_all_statuses`
      //     (`app/repositories/pipeline_repository.py:104-108`) là `select(...)`
      //     KHÔNG `ORDER BY`, nên thứ tự là thứ tự heap của Postgres. Một
      //     `UPDATE` bất kỳ lên hàng `sts00` viết lại tuple và đẩy nó xuống
      //     CUỐI heap. Đo thật trên cùng một CSDL: trước UPDATE
      //     `statuses[0]='sts00'`, sau UPDATE `statuses[0]='sts02'` — cả suite
      //     lặng lẽ thao tác trên một cặp trạng thái KHÁC.
      //
      // Nguồn chuẩn đúng là `code`: nó có ràng buộc tầng CSDL
      // `uq_consultation_status_code UNIQUE (code)`, và `fsm_engine.py:112-130`
      // (SPEC Rule #11 — "lead mới, status NULL ⇒ CHỈ trả NOT_CONTACTED") đã
      // dùng đúng định danh này.
      const khoiTao = pipelineStatuses.find((s) => s.code === "NOT_CONTACTED");
      expect(
        khoiTao,
        `Seed phải có đúng một trạng thái code='NOT_CONTACTED'. ` +
          `Nhận được ${pipelineStatuses.length} trạng thái, các code: ` +
          `${pipelineStatuses.map((s) => s.code ?? "<null>").join(",")}`
      ).toBeTruthy();
      initialStatusId = khoiTao!.id;

      // TRẠNG THÁI KẾ TIẾP — hỏi chính FSM, không lấy phần tử kế trong mảng.
      // `GET /api/pipeline/allowed-next-statuses` (`routers/pipeline.py:93`)
      // chạy qua `get_next_statuses_for_lead`, tức đúng bộ luật mà PATCH status
      // sẽ cưỡng chế. Lấy `statuses[1]` là rút thăm, và rút trúng một trạng thái
      // không có cạnh tới thì ca test đỏ vì lý do chẳng liên quan.
      const nextResp = await page.request.get(
        `${API_URL}/api/pipeline/allowed-next-statuses?current_status_id=${initialStatusId}`
      );
      await expectOk(
        nextResp,
        `GET /api/pipeline/allowed-next-statuses?current_status_id=${initialStatusId}`,
        [200]
      );
      const ungVien = (await nextResp.json()) as Array<{
        id: string;
        code?: string | null;
        is_final?: boolean;
      }>;
      const keTiep = ungVien.find((s) => s.id !== initialStatusId && !s.is_final);
      expect(
        keTiep,
        `FSM phải cho ít nhất một trạng thái KHÔNG-final đi tới được từ ` +
          `${initialStatusId}; nhận được ${ungVien.length} ứng viên: ` +
          `${ungVien.map((s) => `${s.id}${s.is_final ? "(final)" : ""}`).join(",")}`
      ).toBeTruthy();
      secondStatusId = keTiep!.id;

      console.log(
        `Pipeline: ${pipelineStatuses.length} statuses · initial=${initialStatusId}` +
          ` (code=NOT_CONTACTED) · second=${secondStatusId} (FSM, ${ungVien.length} ứng viên)`
      );

      // Organization units — chỉ để khẳng định seed có đơn vị; `unitId`
      // KHÔNG lấy ở đây nữa (xem ghi chú ở khai báo biến).
      const unitsResp = await page.request.get(`${API_URL}/api/organization-units`);
      await expectOk(unitsResp, "GET /api/organization-units", [200]);
      const units = await unitsResp.json();
      expect(units.length).toBeGreaterThan(0);

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

      // Danh tính + đơn vị ĐỌC RA TỪ phiên, không suy từ tên đăng nhập và
      // không lấy `units[0]`. Cặp (officerUserId, unitId) từ đây trở đi
      // luôn tương thích với `_assert_officer_in_lead_unit`.
      const meResp = await page.request.get(`${API_URL}/api/users/me`);
      await expectOk(meResp, "officer GET /api/users/me", [200]);
      const me = await meResp.json();
      expect(me.role, `Tài khoản "${OFFICER_USERNAME}" phải có role officer`).toBe(
        "officer"
      );
      expect(
        me.unit_id,
        `Officer #${me.id} không có unit_id — không thể tạo lead cùng đơn vị để phân công.`
      ).toBeTruthy();
      officerUserId = me.id;
      unitId = me.unit_id;
      console.log(
        `Officer logged in: user #${officerUserId} role=${me.role} unit=${unitId}`
      );
    });

    // --- Step 3: Check duplicate (should not exist) ---
    await test.step("Check duplicate - no match", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/leads/check-duplicate?phone=${testPhone1}`
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.phone_available).toBe(true);
      // Không in nguyên số điện thoại (dù là số sinh ra cho test) — log
      // nightly được lưu 7 ngày và đi qua nhiều tay.
      console.log(`No duplicate for …${testPhone1.slice(-3)}: phone_available=${body.phone_available}`);
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
        console.log(`Get lead failed: ${resp.status()} ${summarizeApiError(resp.status(), await resp.text())}`);
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
      console.log(`Workflow context: ${safeBody(body)}`);
    });

    // --- Step 7: Add consultation ---
    await test.step("Add consultation", async () => {
      // Refresh CSRF token before mutation
      officerHeaders = await restoreCookies(page, officerCookies);

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
      if (!resp.ok() && resp.status() !== 201) {
        console.log(`Add consultation failed: ${resp.status()} ${summarizeApiError(resp.status(), await resp.text())}`);
      }
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      const body = await resp.json();
      consultationId1 = body.consultation?.id ?? body.id;
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
      console.log(`Insights: ${safeBody(body)}`);
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
        console.log(`Lead update failed: ${resp.status()} ${summarizeApiError(resp.status(), await resp.text())}`);
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

      // `unit_id` TƯỜNG MINH. Bỏ trống thì nhánh ADMIN của `create_lead`
      // (lead_service.py:941-960) hỏi cấu hình phân phối của offering và
      // đặt lead vào đơn vị mà cấu hình ấy trả về — đo thật: đơn vị #1,
      // nơi không có officer active nào ⇒ bước Assign bên dưới 400.
      const resp = await page.request.post(`${API_URL}/api/leads`, {
        headers: adminHeaders,
        data: {
          full_name: `E2E_Lead2_${Date.now()}`,
          phone: testPhone2,
          source: "online",
          offering_id: offeringId,
          unit_id: unitId,
        },
      });
      await expectOk(resp, "admin tạo lead2", [200, 201]);
      const lead2Body = await resp.json();
      leadId2 = lead2Body.id;
      expect(
        lead2Body.unit_id,
        `lead2 phải nằm ở đơn vị #${unitId} của officer #${officerUserId}`
      ).toBe(unitId);
      console.log(`Created lead2 ID: ${leadId2} (unit #${lead2Body.unit_id})`);
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
      // `phone_conflict` mang tên + SĐT + đơn vị của lead trùng ⇒ CHỈ in
      // các KHOÁ, không in giá trị.
      console.log(
        `Duplicate found for …${testPhone1.slice(-3)}: conflict keys=` +
          `${Object.keys(body.phone_conflict || {}).join(",")}`
      );
    });

    // --- Step 3: Assign lead2 to officer ---
    await test.step("Assign lead to officer", async () => {
      // `officerUserId` đã ĐỌC RA từ `/api/users/me` của chính phiên
      // officer ở Test 1. Khối "khám phá" cũ ở đây là mã CHẾT có hại:
      //   * `/api/admin/roles/officer/users` trả OBJECT
      //     `{role, user_count, users}` (admin/roles.py:451-503), nên
      //     `users.length` là `undefined` ⇒ nhánh đó không bao giờ chạy;
      //   * nó lọc grouping policy theo `group[1] == "officer"` trong khi
      //     seed ghi `v1 = "role:officer"` — đo thật: `user_count = 0`;
      //   * fallback `lead1.created_by_id` có thể trả về ID của ADMIN, và
      //     backend khi ấy trả 403 "is not an officer".
      // Thay bằng một cổng chứng minh cặp (officer, đơn vị lead) hợp lệ
      // TRƯỚC khi gọi — bất biến ở lead_service.py:2454-2472.
      const officers = await listActiveOfficers(page.request);
      const target = officers.find((o) => o.id === officerUserId);
      expect(
        target,
        `Officer #${officerUserId} không nằm trong danh sách officer active ` +
          `(${officers.map((o) => `#${o.id}@${o.unit_id}`).join(" ")}).`
      ).toBeTruthy();
      expect(
        target!.unit_id,
        `Officer #${officerUserId} thuộc đơn vị #${target!.unit_id} còn lead2 ` +
          `thuộc đơn vị #${unitId} — backend chặn 400 BUSINESS_RULE_VIOLATION.`
      ).toBe(unitId);

      const resp = await page.request.post(
        `${API_URL}/api/leads/${leadId2}/assign`,
        {
          headers: adminHeaders,
          data: { officer_id: officerUserId },
        }
      );
      await expectOk(
        resp,
        `assign lead2 #${leadId2} (đơn vị #${unitId}) → officer #${officerUserId}`,
        [200]
      );
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
      console.log(`Reassign quota: ${safeBody(body)}`);
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
          unit_id: unitId,
        },
      });
      await expectOk(resp, "admin tạo lead3", [200, 201]);
      leadId3 = (await resp.json()).id;
      console.log(`Created lead3 ID: ${leadId3}`);
    });

    // --- Step 6: Bulk-assign lead2 + lead3 to officer ---
    await test.step("Bulk-assign lead2 + lead3 to officer", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/leads/bulk-assign?officer_id=${officerUserId}`,
        {
          headers: adminHeaders,
          data: { lead_ids: [leadId2, leadId3] },
        }
      );
      await expectOk(
        resp,
        `bulk-assign [${leadId2},${leadId3}] → officer #${officerUserId}`,
        [200]
      );
      const body = await resp.json();
      expect(body.total).toBe(2);
      expect(
        body.successful,
        `bulk-assign errors=${safeBody(body.errors)}`
      ).toBe(2);
      expect(body.failed).toBe(0);
      expect(body.assigned_lead_ids).toContain(leadId2);
      expect(body.assigned_lead_ids).toContain(leadId3);
      console.log(`Bulk-assign: total=${body.total}, successful=${body.successful}, errors=${safeBody(body.errors)}`);
    });

    // --- Step 7: Bulk update stage ---
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
      console.log(`Bulk stage update: ${safeBody(body)}`);
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
      expect(body.consultation?.id ?? body.id).toBe(consultationId1);
      console.log(`Consultation ${consultationId1} restored`);
    });
  });

  // =========================================================================
  // Test 4: IDOR + FSM status patch + Officer action + Audit logs
  // =========================================================================
  test("IDOR: officer cannot access unassigned lead + FSM status patch + officer action + audit logs", async ({ page }) => {
    // --- Step 1: Admin creates unassigned lead (IDOR bait) ---
    await test.step("Admin creates unassigned lead (IDOR bait)", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.post(`${API_URL}/api/leads`, {
        headers: adminHeaders,
        data: {
          full_name: `E2E_IDOR_${Date.now()}`,
          phone: generatePhone(),
          source: "walk_in",
          offering_id: offeringId,
          // No officer_id → lead stays unassigned or assigned to admin
        },
      });
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      leadIdInaccessible = (await resp.json()).id;
      console.log(`Created unassigned lead: id=${leadIdInaccessible}`);
    });

    // --- Step 2: Officer tries to access unassigned lead → 404 (IDOR) ---
    await test.step("Officer cannot access unassigned lead → 404 (IDOR)", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      const resp = await page.request.get(
        `${API_URL}/api/leads/${leadIdInaccessible}`,
        { headers: officerHeaders }
      );
      expect(resp.status()).toBe(404);
      console.log(`IDOR blocked: officer got 404 for unassigned lead ${leadIdInaccessible}`);
    });

    // --- Step 3: Officer creates lead4 (auto-assigned to self) ---
    await test.step("Officer creates lead4 for FSM + action tests", async () => {
      const resp = await page.request.post(`${API_URL}/api/leads`, {
        headers: officerHeaders,
        data: {
          full_name: `E2E_Lead4_${Date.now()}`,
          phone: generatePhone(),
          source: "walk_in",
          offering_id: offeringId,
        },
      });
      expect(resp.ok() || resp.status() === 201).toBeTruthy();
      leadId4 = (await resp.json()).id;
      console.log(`Created lead4: id=${leadId4}`);
    });

    // --- Step 4: Add consultation to lead4 (prerequisite for FSM PATCH) ---
    await test.step("Add consultation to lead4 (set initial status)", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      const resp = await page.request.post(
        `${API_URL}/api/leads/${leadId4}/consultations`,
        {
          headers: officerHeaders,
          data: {
            status_id: initialStatusId,
            method: "phone",
            notes: "E2E: prepare for FSM patch test",
          },
        }
      );
      await expectOk(resp, `officer thêm consultation cho lead4 #${leadId4}`, [
        200,
        201,
      ]);
      const body = await resp.json();
      // `POST /consultations` trả `ConsultationCreateResult`
      // (`app/schemas/lead.py:133-142`) = `{consultation, status_updated,
      // terminal_guard_reason}`. KHÔNG có `consultation_status_id` ở cấp
      // gốc và KHÔNG có khoá `lead` — phép đọc cũ
      // `body.consultation_status_id ?? body.lead?.consultation_status_id`
      // luôn cho `undefined`. Ca này chưa từng chạy (serial mode dừng ở
      // :517 nên test 4 bị bỏ qua).
      expect(
        body.consultation?.consultation_status_id,
        `Consultation vừa tạo phải mang status ${initialStatusId}`
      ).toBe(initialStatusId);
      expect(
        body.status_updated,
        `Lead phải được cập nhật trạng thái; terminal_guard_reason=${body.terminal_guard_reason}`
      ).toBe(true);

      // Đo ở NGUỒN CHUẨN: trạng thái thật trên lead, không chỉ trên thân
      // phản hồi của chính lệnh vừa ghi.
      const leadResp = await page.request.get(`${API_URL}/api/leads/${leadId4}`, {
        headers: officerHeaders,
      });
      await expectOk(leadResp, `GET lead4 #${leadId4} sau consultation`, [200]);
      const leadBody = await leadResp.json();
      expect(leadBody.consultation_status_id).toBe(initialStatusId);
      console.log(`Lead4 consultation set to ${initialStatusId}`);
    });

    // `PATCH /leads/{id}/status` nhận `LeadStatusUpdate`
    // (`app/schemas/lead.py:480-501`): `consultation_status_id` VÀ
    // `version` (khoá lạc quan) đều là `Field(...)` BẮT BUỘC. Thiếu
    // `version` thì mọi lời gọi ở đây trả 422 — đo thật:
    //   422 VALIDATION_ERROR · invalid_fields=body.version[missing]
    // Ba bước dưới đây chưa từng chạy trong nightly (serial mode dừng ở
    // :517), nên lỗi hợp đồng này chưa ai thấy.
    const layVersion = async (
      headers: Record<string, string>
    ): Promise<number> => {
      const r = await page.request.get(`${API_URL}/api/leads/${leadId4}`, {
        headers,
      });
      await expectOk(r, `GET lead4 #${leadId4} để lấy version`, [200]);
      const b = await r.json();
      expect(typeof b.version, "Lead phải có version cho khoá lạc quan").toBe(
        "number"
      );
      return b.version as number;
    };

    // --- Step 5: Officer cannot PATCH /status → 403 (admin/manager only) ---
    await test.step("Officer cannot PATCH /leads/{id}/status → 403", async () => {
      // Thân request ĐẦY ĐỦ: nếu thiếu `version`, 403 có thể đến từ bất kỳ
      // đâu và ca kiểm không còn chứng minh được điều nó nhận là chứng minh.
      const version = await layVersion(officerHeaders);
      const resp = await page.request.patch(
        `${API_URL}/api/leads/${leadId4}/status`,
        {
          headers: officerHeaders,
          data: { consultation_status_id: secondStatusId, version },
        }
      );
      expect(
        resp.status(),
        `Officer PATCH /status phải 403 (Casbin: admin/manager). ` +
          `${summarizeApiError(resp.status(), await resp.text())}`
      ).toBe(403);
      console.log(`Officer PATCH /status blocked: 403`);
    });

    // --- Step 6: Admin PATCH /leads/{lead4}/status → secondStatusId (valid FSM transition) ---
    await test.step("Admin PATCH /leads/{lead4}/status → secondStatusId (valid)", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const version = await layVersion(adminHeaders);
      const resp = await page.request.patch(
        `${API_URL}/api/leads/${leadId4}/status`,
        {
          headers: adminHeaders,
          data: { consultation_status_id: secondStatusId, version },
        }
      );
      await expectOk(
        resp,
        `admin PATCH lead4 #${leadId4} status ${initialStatusId} → ${secondStatusId} (version ${version})`,
        [200]
      );
      const body = await resp.json();
      expect(body.consultation_status_id).toBe(secondStatusId);
      console.log(`Admin FSM PATCH: ${initialStatusId} → ${secondStatusId}`);
    });

    // --- Step 7: PATCH with non-existent status ID → 404 or 400 ---
    await test.step("PATCH with invalid status ID → rejected (404/400)", async () => {
      const version = await layVersion(adminHeaders);
      const resp = await page.request.patch(
        `${API_URL}/api/leads/${leadId4}/status`,
        {
          headers: adminHeaders,
          data: { consultation_status_id: "sts_nonexistent_xyz", version },
        }
      );
      // Phải bị từ chối vì TRẠNG THÁI không tồn tại, không phải vì thiếu
      // trường — nên loại tường minh 422 ra khỏi tập chấp nhận.
      expect(
        [400, 404],
        `PATCH với status không tồn tại phải bị từ chối bằng 400/404. ` +
          `${summarizeApiError(resp.status(), await resp.text())}`
      ).toContain(resp.status());
      console.log(`FSM PATCH with invalid status rejected: ${resp.status()}`);
    });

    // --- Step 8: Officer action "reject" on lead4 ---
    await test.step("Officer action: reject lead4", async () => {
      // Restore officer cookies (admin cookies were set in step 6)
      officerHeaders = await restoreCookies(page, officerCookies);

      const resp = await page.request.post(
        `${API_URL}/api/leads/${leadId4}/action`,
        {
          headers: officerHeaders,
          data: { action: "reject", reason: "E2E test: officer cannot contact this lead" },
        }
      );
      if (!resp.ok()) {
        console.log(`Officer action failed: ${resp.status()} ${summarizeApiError(resp.status(), await resp.text())}`);
      }
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      console.log(`Lead4 after officer reject: status=${body.status}`);
    });

    // --- Step 9: Officer action "reject" without reason → 422 (schema validation) ---
    await test.step("Officer action without reason → 422", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/leads/${leadId4}/action`,
        {
          headers: officerHeaders,
          data: { action: "reject" }, // missing required field
        }
      );
      expect(resp.status()).toBe(422);
      console.log(`Officer action without reason rejected: 422`);
    });

    // --- Step 10: Officer "reassign" action → clears assignment, reassign_pending ---
    await test.step("Officer reassign action → assigned_officer_id cleared + assignment_status=reassign_pending", async () => {
      // Admin creates a fresh lead and assigns it to the officer for this test
      adminHeaders = await restoreCookies(page, adminCookies);
      const freshLeadResp = await page.request.post(`${API_URL}/api/leads`, {
        headers: adminHeaders,
        data: {
          full_name: `E2E_Reassign_${Date.now()}`,
          phone: generatePhone(),
          source: "walk_in",
          offering_id: offeringId,
          // Cùng đơn vị officer — nếu không, assign dưới đây trả 400 và
          // bước "officer reassign" kế tiếp đo nhầm một lead chưa được gán.
          unit_id: unitId,
        },
      });
      await expectOk(freshLeadResp, "admin tạo lead cho ca reassign", [200, 201]);
      const freshLeadId = (await freshLeadResp.json()).id;

      const freshAssignResp = await page.request.post(
        `${API_URL}/api/leads/${freshLeadId}/assign`,
        {
          headers: adminHeaders,
          data: { officer_id: officerUserId },
        }
      );
      await expectOk(
        freshAssignResp,
        `assign lead #${freshLeadId} → officer #${officerUserId} trước ca reassign`,
        [200]
      );

      // Officer reassigns the lead (self-reassign: gives up ownership)
      officerHeaders = await restoreCookies(page, officerCookies);

      // Hạn mức reassign là 5 LƯỢT/TUẦN cho mỗi officer
      // (`lead_service.check_reassign_quota`). Đọc nó TRƯỚC và đưa vào
      // thông điệp lỗi: trên CSDL bị dùng lại nhiều lượt, bước này hết
      // hạn mức và `expect(resp.ok()).toBeTruthy()` chỉ in "Received:
      // false" — không ai đoán được vì sao.
      const quotaResp = await page.request.get(
        `${API_URL}/api/leads/my/reassign-quota`,
        { headers: officerHeaders }
      );
      await expectOk(quotaResp, "officer GET /api/leads/my/reassign-quota", [200]);
      const quota = await quotaResp.json();

      const resp = await page.request.post(
        `${API_URL}/api/leads/${freshLeadId}/action`,
        {
          headers: officerHeaders,
          data: { action: "reassign", reason: "Lead không phù hợp, cần chuyển cho nhóm khác" },
        }
      );
      await expectOk(
        resp,
        `officer #${officerUserId} reassign lead #${freshLeadId} ` +
          `(hạn mức tuần: used=${quota.used}/${quota.limit}, remaining=${quota.remaining}, allowed=${quota.allowed})`,
        [200]
      );
      const body = await resp.json();
      expect(body.assigned_officer_id).toBeNull();
      expect(body.assignment_status).toBe("reassign_pending");
      console.log(
        `Officer reassign: assigned_officer_id=${body.assigned_officer_id}, assignment_status=${body.assignment_status}`
      );
    });

    // --- Step 11: GET /leads/{lead1}/audit-logs (admin) ---
    await test.step("Admin gets audit logs for lead1", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.get(
        `${API_URL}/api/leads/${leadId1}/audit-logs`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      // Audit log may be empty if no field-level changes were tracked
      expect(typeof body.total).toBe("number");
      expect(Array.isArray(body.items)).toBeTruthy();
      console.log(`Audit logs for lead1: total=${body.total}, items=${body.items.length}`);
    });

    // --- Step 11: Officer cannot get audit logs for inaccessible lead → 404 ---
    await test.step("Officer cannot get audit logs for unassigned lead → 404", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      const resp = await page.request.get(
        `${API_URL}/api/leads/${leadIdInaccessible}/audit-logs`,
        { headers: officerHeaders }
      );
      expect(resp.status()).toBe(404);
      console.log(`Audit log IDOR blocked: officer got 404`);
    });
  });

  // =========================================================================
  // Test 5: Validity status + Bulk delete + Distribution preview
  // =========================================================================
  test("Validity status + Bulk delete + Distribution preview", async ({ page }) => {
    // --- Step 1: Admin sets lead3 validity to "invalid" ---
    await test.step("Admin sets lead3 validity to 'invalid'", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.post(
        `${API_URL}/api/leads/${leadId3}/validity`,
        {
          headers: adminHeaders,
          data: { validity_status: "invalid" },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.validity_status).toBe("invalid");
      console.log(`Lead3 validity set to invalid`);
    });

    // --- Step 2: Admin sets validity back to "valid" ---
    await test.step("Admin sets lead3 validity back to 'valid'", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/leads/${leadId3}/validity`,
        {
          headers: adminHeaders,
          data: { validity_status: "valid" },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.validity_status).toBe("valid");
      console.log(`Lead3 validity set to valid`);
    });

    // --- Step 3: Officer cannot set validity → 403 (admin/manager only) ---
    await test.step("Officer cannot set validity → 403", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      const resp = await page.request.post(
        `${API_URL}/api/leads/${leadId1}/validity`,
        {
          headers: officerHeaders,
          data: { validity_status: "valid" },
        }
      );
      expect(resp.status()).toBe(403);
      console.log(`Officer validity blocked: 403`);
    });

    // --- Step 4: Admin bulk-deletes 2 fresh leads ---
    await test.step("Admin bulk-delete 2 fresh leads", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // Create 2 leads to be bulk-deleted
      const r1 = await page.request.post(`${API_URL}/api/leads`, {
        headers: adminHeaders,
        data: {
          full_name: `E2E_BulkDel_A_${Date.now()}`,
          phone: generatePhone(),
          source: "walk_in",
          offering_id: offeringId,
        },
      });
      const r2 = await page.request.post(`${API_URL}/api/leads`, {
        headers: adminHeaders,
        data: {
          full_name: `E2E_BulkDel_B_${Date.now()}`,
          phone: generatePhone(),
          source: "walk_in",
          offering_id: offeringId,
        },
      });
      const bulkDelId1 = (await r1.json()).id;
      const bulkDelId2 = (await r2.json()).id;
      console.log(`Created leads for bulk-delete: ${bulkDelId1}, ${bulkDelId2}`);

      // Bulk delete
      const resp = await page.request.post(`${API_URL}/api/leads/bulk-delete`, {
        headers: adminHeaders,
        data: { lead_ids: [bulkDelId1, bulkDelId2] },
      });
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.deleted_count).toBe(2);
      console.log(`Bulk deleted: ${body.deleted_count} leads, skipped=${body.skipped?.length ?? 0}`);

      // Verify both are soft-deleted (404 from officer's perspective)
      const g1 = await page.request.get(`${API_URL}/api/leads/${bulkDelId1}`);
      const g2 = await page.request.get(`${API_URL}/api/leads/${bulkDelId2}`);
      expect(g1.status()).toBe(404);
      expect(g2.status()).toBe(404);
      console.log(`Bulk-deleted leads confirmed 404`);
    });

    // --- Step 5: Distribution preview ---
    await test.step("Distribution preview for offering", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/leads/distribution-preview?offering_id=${offeringId}`,
        { headers: adminHeaders }
      );
      // 200 if config exists, 404 if no distribution config for offering
      expect(resp.status() === 200 || resp.status() === 404).toBeTruthy();
      if (resp.ok()) {
        const body = await resp.json();
        console.log(`Distribution preview: has_config=${body.has_config}, offering=${body.offering_id}`);
      } else {
        console.log(`Distribution preview: no config for offering ${offeringId}`);
      }
    });
  });

  // =========================================================================
  // Test 6: CSV Import
  // =========================================================================
  test("Import leads from CSV file", async ({ page }) => {
    const phoneImport1 = generatePhone();
    const phoneImport2 = generatePhone();
    let firstImportCount = 0;

    // --- Step 1: Officer imports CSV with 2 new leads ---
    await test.step("Officer imports CSV — 2 new leads", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      const ts = Date.now();
      // Use +84 prefix so pandas read_csv doesn't convert to integer (leading-zero stripping).
      // Backend phone_helpers normalizes +84xxxxxxxxx → 0xxxxxxxxx before validation.
      const phone1E164 = `+84${phoneImport1.substring(1)}`;
      const phone2E164 = `+84${phoneImport2.substring(1)}`;
      const csvContent = [
        "full_name,email,phone,source,unit_id",
        `E2E_Import1_${ts},import1_${ts}@test.com,${phone1E164},online,${unitId}`,
        `E2E_Import2_${ts},import2_${ts}@test.com,${phone2E164},facebook,${unitId}`,
      ].join("\n");

      const { body: mpBody, contentType: mpCT } = buildMultipartFile("file", "leads.csv", "text/csv", csvContent);
      const resp = await page.request.post(`${API_URL}/api/leads/import`, {
        headers: { ...officerHeaders, "Content-Type": mpCT },
        data: mpBody,
      });
      // ⛔ ĐANG ĐỎ VÌ DỮ LIỆU NỀN, KHÔNG PHẢI VÌ TEST.
      //
      // Đo thật trên stack nightly dựng lại cục bộ (`nfrb`), CSDL vừa
      // `alembic upgrade head` + `seed_from_xlsx`:
      //     POST /api/leads/import → 400
      //     {"detail":"System configuration error: Initial lead status not
      //       found.","error_code":"HTTP_400"}
      // Nguyên nhân: `StatusHelper.get_initial_status`
      // (`app/services/status_helper.py:46-67`) tìm hàng
      // `legacy_status == 'new' AND is_final == false`, mà trên CSDL mới
      // KHÔNG hàng nào có `legacy_status='new'`:
      //   * `zq6w7x8y9z0a1_seed_operational_baseline.py:146` chèn sts00 với
      //     `legacy_status = NULL`;
      //   * `zb1h2i3j4k5l6_fix_consultation_status_legacy_and_funnel.py:59`
      //     đổi sts02 từ 'new' → 'contacted';
      //   * `seed_from_xlsx.seed_10b_trang_thai` BỎ QUA vì bảng đã có 21 hàng.
      // Đo bằng SQL: `count(*) FILTER (WHERE legacy_status='new') = 0 / 21`.
      // KHÔNG nới assertion ở đây — sửa phải nằm ở seed/migration, đi qua
      // PR riêng có cổng deploy.
      await expectOk(
        resp,
        "officer nhập CSV 2 lead (POST /api/leads/import)",
        [200]
      );
      const body = await resp.json();
      firstImportCount = body.successful_imports;
      console.log(
        `CSV import: rows=${body.total_rows_processed}, success=${body.successful_imports}, failed=${body.failed_imports}`
      );
      if (body.failed_imports > 0) {
        console.log(`Import body: ${safeBody(body)}`);
      }
      expect(body.total_rows_processed).toBe(2);
      expect(body.successful_imports).toBeGreaterThanOrEqual(1);
    });

    // --- Step 2: Re-import same phones → duplicate detection ---
    await test.step("Re-import same phones → duplicate detection", async () => {
      const ts = Date.now();
      const csvContent = [
        "full_name,email,phone,source,unit_id",
        `E2E_Dup1_${ts},dup1_${ts}@test.com,${phoneImport1},online,${unitId}`,
        `E2E_Dup2_${ts},dup2_${ts}@test.com,${phoneImport2},facebook,${unitId}`,
      ].join("\n");

      const { body: mpBody2, contentType: mpCT2 } = buildMultipartFile("file", "leads_dup.csv", "text/csv", csvContent);
      const resp = await page.request.post(`${API_URL}/api/leads/import`, {
        headers: { ...officerHeaders, "Content-Type": mpCT2 },
        data: mpBody2,
      });
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      console.log(
        `Re-import: rows=${body.total_rows_processed}, success=${body.successful_imports}, failed=${body.failed_imports}`
      );
      // At least the successful rows from first import should now be duplicates
      expect(body.failed_imports).toBeGreaterThanOrEqual(firstImportCount);
    });

    // --- Step 3: Import CSV with missing required field (phone) ---
    await test.step("Import CSV with missing phone → row-level error", async () => {
      const ts = Date.now();
      const csvContent = [
        "full_name,email,phone,source,unit_id",
        `E2E_NoPhone_${ts},noPhone_${ts}@test.com,,online,${unitId}`, // empty phone
      ].join("\n");

      const { body: mpBody3, contentType: mpCT3 } = buildMultipartFile("file", "invalid.csv", "text/csv", csvContent);
      const resp = await page.request.post(`${API_URL}/api/leads/import`, {
        headers: { ...officerHeaders, "Content-Type": mpCT3 },
        data: mpBody3,
      });
      // 200 with row-level error in body, or 400 at API level
      expect(resp.status() === 200 || resp.status() === 400).toBeTruthy();
      if (resp.ok()) {
        const body = await resp.json();
        console.log(
          `Missing-phone row: total=${body.total_rows_processed}, failed=${body.failed_imports}`
        );
        // Either the row was skipped/failed (if phone is required) or imported (if optional)
      } else {
        console.log(`Missing-phone CSV rejected at API level: ${resp.status()}`);
      }
    });
  });

  // =========================================================================
  // Test 7: GET /api/leads — List, Filters, Pagination, Role-based visibility
  // =========================================================================
  test("List leads — filters, pagination, role-based visibility", async ({ page }) => {
    // --- Step 1: Admin list (no filter) — verify shape + positive control ---
    await test.step("Admin list — shape + positive control", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // Shape check: default page
      const resp = await page.request.get(`${API_URL}/api/leads`, { headers: adminHeaders });
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(typeof body.total_count).toBe("number");
      expect(Array.isArray(body.leads)).toBeTruthy();
      expect(body.total_count).toBeGreaterThanOrEqual(1);

      // Positive control: search for the specific lead (seed data may push it off page 1)
      const resp2 = await page.request.get(`${API_URL}/api/leads?search=${testPhone1}`, { headers: adminHeaders });
      expect(resp2.ok()).toBeTruthy();
      const body2 = await resp2.json();
      expect(body2.leads.some((l: { id: number }) => l.id === leadId1)).toBeTruthy();
      console.log(`Admin list: total_count=${body.total_count}, lead1 found via search`);
    });

    // --- Step 2: Filter by source=walk_in ---
    await test.step("Filter by source=walk_in", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.get(`${API_URL}/api/leads?source=walk_in`, { headers: adminHeaders });
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      if (body.leads.length > 0) {
        expect(body.leads.every((l: { source: string }) => l.source === "walk_in")).toBeTruthy();
      }
      console.log(`Filter source=walk_in: returned ${body.leads.length} leads`);
    });

    // --- Step 3: Search by testPhone1 ---
    await test.step("Search by testPhone1 — lead1 found", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.get(`${API_URL}/api/leads?search=${testPhone1}`, { headers: adminHeaders });
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.leads.some((l: { id: number }) => l.id === leadId1)).toBeTruthy();
      console.log(`Search by phone: found=${body.leads.length} leads`);
    });

    // --- Step 4: Filter by pipeline_stage_id ---
    await test.step("Filter by pipeline_stage_id", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const stageIdForFilter = pipelineStages[0].id;
      const resp = await page.request.get(
        `${API_URL}/api/leads?pipeline_stage_id=${stageIdForFilter}`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      if (body.leads.length > 0) {
        expect(
          body.leads.every(
            (l: { pipeline_stage_id: string }) => l.pipeline_stage_id === stageIdForFilter
          )
        ).toBeTruthy();
      }
      console.log(`Filter stage_id=${stageIdForFilter}: returned ${body.leads.length} leads`);
    });

    // --- Step 5: Pagination — page_size=1 ---
    await test.step("Pagination page_size=1", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.get(`${API_URL}/api/leads?page=1&page_size=1`, { headers: adminHeaders });
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.leads.length).toBeLessThanOrEqual(1);
      expect(body.total_count).toBeGreaterThanOrEqual(1);
      console.log(`Pagination page_size=1: leads.length=${body.leads.length}, total_count=${body.total_count}`);
    });

    // --- Step 6: Filter by assigned_officer_id ---
    await test.step("Filter by assigned_officer_id", async () => {
      if (!officerUserId) {
        console.log("officerUserId not set, skip step 6");
        return;
      }
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.get(
        `${API_URL}/api/leads?assigned_officer_id=${officerUserId}&page_size=100`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.leads.some((l: { id: number }) => l.id === leadId1)).toBeTruthy();
      if (body.leads.length > 0) {
        expect(
          body.leads.every(
            (l: { assigned_officer_id: number }) => l.assigned_officer_id === officerUserId
          )
        ).toBeTruthy();
      }
      console.log(`Filter officer_id=${officerUserId}: returned ${body.leads.length} leads`);
    });

    // --- Step 7: Date range — broad range covering all test data ---
    await test.step("Date range filter — broad range", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.get(
        `${API_URL}/api/leads?date_from=2020-01-01T00%3A00%3A00&date_to=2099-12-31T23%3A59%3A59`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.total_count).toBeGreaterThanOrEqual(1);
      console.log(`Date range filter: total_count=${body.total_count}`);
    });

    // --- Step 8: Score range filter ---
    await test.step("Score range filter score_min=0&score_max=100", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.get(
        `${API_URL}/api/leads?score_min=0&score_max=100`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.total_count).toBeGreaterThanOrEqual(1);
      console.log(`Score range filter: total_count=${body.total_count}`);
    });

    // --- Step 9: Officer role-based filter — chỉ thấy leads của mình ---
    await test.step("Officer list — role-scoped visibility", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      const resp = await page.request.get(`${API_URL}/api/leads?page_size=100`, { headers: officerHeaders });
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      // Positive: officer phải thấy lead1 (assigned trong Test 1)
      expect(body.leads.some((l: { id: number }) => l.id === leadId1)).toBeTruthy();
      // Negative: không thấy leadIdInaccessible (unassigned, tạo trong Test 4)
      expect(body.leads.find((l: { id: number }) => l.id === leadIdInaccessible)).toBeFalsy();
      // Role enforcement: mọi lead trả về phải của officer này
      if (body.leads.length > 0 && officerUserId) {
        expect(
          body.leads.every(
            (l: { assigned_officer_id: number }) => l.assigned_officer_id === officerUserId
          )
        ).toBeTruthy();
      }
      console.log(`Officer list: total_count=${body.total_count}, visible leads=${body.leads.length}`);
    });
  });

  // =========================================================================
  // Test 8: Business Rule Validations — optimistic locking, loss reason
  //
  // Ca "terminal block" ĐÃ RỜI khỏi đây sang describe ĐỘC LẬP ở cuối tệp
  // (`Lead terminal hard block — độc lập`). Lý do là một sự thật ĐO ĐƯỢC, không
  // phải gu thẩm mỹ: describe này chạy `mode: "serial"`, nên test 6 (import
  // CSV) đỏ là Playwright **skip** mọi test sau nó — test 7..10 in ra
  // "did not run". Ca terminal vì thế chưa từng thực thi một lần nào, kể cả
  // trong những đêm nightly mà nó nằm sẵn trong tệp.
  // Chạy riêng bằng `-g` cũng không cứu: test 8 đọc `adminCookies`,
  // `offeringId`, `unitId`, `initialStatusId` — toàn biến module do test 1 gán.
  // =========================================================================
  test("Business rule validations — optimistic locking, loss reason", async ({ page }) => {
    // --- Preamble: Re-fetch pipeline với full metadata + tạo lead mới ---
    await test.step("Re-fetch pipeline metadata + create fresh lead", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // Re-fetch để lấy is_final, phase, outcome_type
      const pr = await page.request.get(`${API_URL}/api/pipeline/all`, { headers: adminHeaders });
      expect(pr.ok()).toBeTruthy();
      const fullPipeline = await pr.json();
      type FullStatus = { id: string; name: string; phase: string; is_final: boolean; outcome_type: string };
      const allFullStatuses: FullStatus[] = fullPipeline.statuses;

      finalNegativeStatusId = allFullStatuses.find(
        (s) => s.is_final && s.outcome_type === "negative" && s.phase === "consultation"
      )?.id ?? null;
      console.log(`finalNegativeStatusId=${finalNegativeStatusId}`);

      // Create 1 fresh lead
      const r1 = await page.request.post(`${API_URL}/api/leads`, {
        headers: adminHeaders,
        // `unit_id` tường minh: sub-test B gán lead này cho officer.
        data: { full_name: `E2E_Lock_${Date.now()}`, phone: generatePhone(), source: "walk_in", offering_id: offeringId, unit_id: unitId },
      });
      await expectOk(r1, "admin tạo lead cho ca optimistic locking", [200, 201]);
      leadIdForLocking = (await r1.json()).id;
      console.log(`Created lead for Test 8: locking=${leadIdForLocking}`);
    });

    // --- Sub-test A: Optimistic Locking (version mismatch → 409) ---
    await test.step("A1: GET lead — capture version", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const detail = await (
        await page.request.get(`${API_URL}/api/leads/${leadIdForLocking}`, { headers: adminHeaders })
      ).json();
      const currentVersion: number = detail.version;
      console.log(`Lead version: ${currentVersion}`);

      // A2: PUT với version sai → 409
      const staleResp = await page.request.put(`${API_URL}/api/leads/${leadIdForLocking}`, {
        headers: adminHeaders,
        data: { full_name: "E2E_Stale", version: currentVersion + 999 },
      });
      expect(staleResp.status()).toBe(409);
      const staleErr = await staleResp.json();
      expect(staleErr.detail).toMatch(/cập nhật|conflict/i);
      console.log(`Stale version rejected: 409 — ${safeBody({ detail: staleErr.detail })}`);

      // A3: PUT với version đúng → 200, version tăng
      adminHeaders = await restoreCookies(page, adminCookies);
      const okResp = await page.request.put(`${API_URL}/api/leads/${leadIdForLocking}`, {
        headers: adminHeaders,
        data: { full_name: "E2E_Lock_Updated", version: currentVersion },
      });
      expect(okResp.ok()).toBeTruthy();
      const updated = await okResp.json();
      expect(updated.version).toBe(currentVersion + 1);
      expect(updated.full_name).toBe("E2E_Lock_Updated");
      console.log(`Correct version accepted: version now=${updated.version}`);
    });

    // --- Sub-test B: Loss Reason Validation ---
    await test.step("B: Loss reason required for negative final status", async () => {
      if (!finalNegativeStatusId) {
        console.log("Skip sub-test B: no status with is_final=true AND outcome_type=negative");
        return;
      }

      // B1: Assign leadIdForLocking to officer
      adminHeaders = await restoreCookies(page, adminCookies);
      if (officerUserId) {
        const assignResp = await page.request.post(`${API_URL}/api/leads/${leadIdForLocking}/assign`, {
          headers: adminHeaders,
          data: { officer_id: officerUserId },
        });
        await expectOk(
          assignResp,
          `assign lead #${leadIdForLocking} → officer #${officerUserId}`,
          [200]
        );
        console.log(`Lead assigned to officer ${officerUserId}`);
      }

      // B2: POST consultation to final+negative WITHOUT loss_reason_code → 400
      adminHeaders = await restoreCookies(page, adminCookies);
      const noReasonResp = await page.request.post(
        `${API_URL}/api/leads/${leadIdForLocking}/consultations`,
        {
          headers: adminHeaders,
          data: { status_id: finalNegativeStatusId, method: "phone", notes: "E2E: missing loss_reason" },
        }
      );
      expect(noReasonResp.status()).toBe(400);
      const noReasonErr = await noReasonResp.json();
      expect(noReasonErr.detail).toMatch(/loss_reason|lý do/i);
      console.log(`Missing loss_reason rejected: 400 — ${safeBody({ detail: noReasonErr.detail })}`);

      // B3: POST WITH loss_reason_code → 201
      adminHeaders = await restoreCookies(page, adminCookies);
      const withReasonResp = await page.request.post(
        `${API_URL}/api/leads/${leadIdForLocking}/consultations`,
        {
          headers: adminHeaders,
          data: {
            status_id: finalNegativeStatusId,
            method: "phone",
            notes: "E2E: with loss reason",
            loss_reason_code: "NO_CONTACT",
            loss_reason_note: "Lead không nghe máy sau 5 lần gọi",
          },
        }
      );
      await expectOk(
        withReasonResp,
        `POST consultation ${finalNegativeStatusId} kèm loss_reason_code`,
        [200, 201]
      );
      const created = await withReasonResp.json();
      // Cùng lớp lỗi với :862 — `ConsultationCreateResult` bọc bản ghi trong
      // khoá `consultation` (`app/schemas/lead.py:133-142`), nên phép đọc cũ
      // `created.consultation_status_id ?? created.status_id` luôn
      // `undefined`. Ca này chưa từng chạy trong nightly.
      const statusField = created.consultation?.consultation_status_id;
      expect(
        statusField,
        `Consultation tạo kèm loss_reason phải mang status ${finalNegativeStatusId}; ` +
          `khoá nhận được: ${Object.keys(created).join(",")}`
      ).toBe(finalNegativeStatusId);
      console.log(`Loss reason accepted: consultation status=${statusField}`);
    });
  });

  // =========================================================================
  // Test 9: Reassign Quota Exhaustion — officer capped at 5/week, admin uncapped
  // =========================================================================
  test("Reassign quota exhaustion — officer capped at 5/week, admin uncapped", async ({ page }) => {
    const ts = Date.now();

    // --- Step 1: Admin creates fresh officer (quota=0) ---
    await test.step("Create fresh quota officer", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      quotaOfficerUsername = `e2e_quota_${ts}`;
      const createResp = await page.request.post(`${API_URL}/api/admin/users`, {
        headers: adminHeaders,
        form: {
          username: quotaOfficerUsername,
          email: `e2e_quota_${ts}@test.example`,
          password: "E2eQuota@12345",
          full_name: "E2E Quota Officer",
          role: "officer",
          status: "active",
        },
      });
      expect(createResp.status()).toBe(201);
      quotaOfficerUserId = (await createResp.json()).id;
      console.log(`Created quota officer: id=${quotaOfficerUserId}, username=${quotaOfficerUsername}`);
    });

    // --- Step 2: Assign quota officer to unitId ---
    await test.step("Assign quota officer to unit", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const assignUnitResp = await page.request.put(
        `${API_URL}/api/admin/users/${quotaOfficerUserId}`,
        { headers: adminHeaders, form: { unit_id: String(unitId) } }
      );
      expect(assignUnitResp.ok()).toBeTruthy();
      console.log(`Quota officer assigned to unit ${unitId}`);
    });

    // --- Step 3: Quota officer login ---
    await test.step("Quota officer login", async () => {
      quotaOfficerHeaders = await loginViaAPI(page, quotaOfficerUsername, "E2eQuota@12345");
      quotaOfficerCookies = await page.context().cookies();
      console.log("Quota officer logged in");
    });

    // --- Step 4: Initial quota = 5 ---
    await test.step("Verify initial quota = 5", async () => {
      quotaOfficerHeaders = await restoreCookies(page, quotaOfficerCookies);

      const q0 = await (
        await page.request.get(`${API_URL}/api/leads/my/reassign-quota`, { headers: quotaOfficerHeaders })
      ).json();
      expect(q0.remaining).toBe(5);
      expect(q0.limit).toBe(5);
      expect(q0.allowed).toBe(true);
      console.log(`Initial quota: remaining=${q0.remaining}, limit=${q0.limit}`);
    });

    // --- Step 5: Admin creates 6 leads and assigns all to quota officer ---
    await test.step("Create and assign 6 leads to quota officer", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      for (let i = 0; i < 6; i++) {
        const lr = await page.request.post(`${API_URL}/api/leads`, {
          headers: adminHeaders,
          data: {
            full_name: `E2E_Quota_Lead_${i}_${ts}`,
            phone: generatePhone(),
            source: "walk_in",
            offering_id: offeringId,
            // quota officer vừa được đặt vào chính `unitId` ở Step 2.
            unit_id: unitId,
          },
        });
        await expectOk(lr, `admin tạo quota lead #${i}`, [200, 201]);
        const lid = (await lr.json()).id;
        const qAssign = await page.request.post(`${API_URL}/api/leads/${lid}/assign`, {
          headers: adminHeaders,
          data: { officer_id: quotaOfficerUserId },
        });
        await expectOk(
          qAssign,
          `assign quota lead #${lid} → quota officer #${quotaOfficerUserId} (đơn vị #${unitId})`,
          [200]
        );
        quotaLeadIds.push(lid);
      }
      expect(quotaLeadIds).toHaveLength(6);
      console.log(`Created and assigned 6 leads: ${quotaLeadIds}`);
    });

    // --- Step 6: Quota officer reassigns 5 leads — each succeeds, quota decrements ---
    await test.step("Quota officer reassigns 5 leads — all succeed", async () => {
      for (let i = 0; i < 5; i++) {
        quotaOfficerHeaders = await restoreCookies(page, quotaOfficerCookies);
        const actionResp = await page.request.post(
          `${API_URL}/api/leads/${quotaLeadIds[i]}/action`,
          {
            headers: quotaOfficerHeaders,
            data: { action: "reassign", reason: `E2E quota test attempt ${i + 1}` },
          }
        );
        expect(actionResp.ok()).toBeTruthy();

        // Verify quota after each reassign
        quotaOfficerHeaders = await restoreCookies(page, quotaOfficerCookies);
        const qi = await (
          await page.request.get(`${API_URL}/api/leads/my/reassign-quota`, { headers: quotaOfficerHeaders })
        ).json();
        expect(qi.used).toBe(i + 1);
        expect(qi.remaining).toBe(4 - i);
        console.log(`Reassign ${i + 1}/5: used=${qi.used}, remaining=${qi.remaining}`);
      }
    });

    // --- Step 7: 6th reassign → 400 quota exceeded ---
    await test.step("6th reassign → 400 quota exceeded", async () => {
      quotaOfficerHeaders = await restoreCookies(page, quotaOfficerCookies);

      const failResp = await page.request.post(
        `${API_URL}/api/leads/${quotaLeadIds[5]}/action`,
        {
          headers: quotaOfficerHeaders,
          data: { action: "reassign", reason: "E2E quota test: should fail" },
        }
      );
      expect(failResp.status()).toBe(400);
      const failErr = await failResp.json();
      expect(failErr.detail).toMatch(/quota|lượt|hết/i);
      console.log(`Quota exceeded: 400 — ${safeBody({ detail: failErr.detail })}`);
    });

    // --- Step 8: Final quota state — remaining=0, allowed=false ---
    await test.step("Final quota: remaining=0, allowed=false", async () => {
      quotaOfficerHeaders = await restoreCookies(page, quotaOfficerCookies);

      const qFinal = await (
        await page.request.get(`${API_URL}/api/leads/my/reassign-quota`, { headers: quotaOfficerHeaders })
      ).json();
      expect(qFinal.remaining).toBe(0);
      expect(qFinal.allowed).toBe(false);
      expect(qFinal.used).toBe(5);
      console.log(`Final quota: remaining=${qFinal.remaining}, allowed=${qFinal.allowed}`);
    });

    // --- Step 9: Admin reassigns 6th lead → succeeds (no quota for admin) ---
    await test.step("Admin reassign — not subject to quota", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const adminReassign = await page.request.post(
        `${API_URL}/api/leads/${quotaLeadIds[5]}/action`,
        {
          headers: adminHeaders,
          data: { action: "reassign", reason: "Admin has no quota limit" },
        }
      );
      expect(adminReassign.ok()).toBeTruthy();
      console.log("Admin reassign succeeded (uncapped)");
    });
  });

  // =========================================================================
  // Test 10: Manager IDOR List Scope — unit-scoped visibility
  // =========================================================================
  test("Manager IDOR list scope — unit-scoped visibility", async ({ page }) => {
    // --- Step 1: Skip if no manager credentials ---
    await test.step("Guard: manager credentials + units check", async () => {
      if (!MANAGER_USERNAME || !MANAGER_PASSWORD) {
        test.skip(true, "E2E_MANAGER_USERNAME/PASSWORD not set — skip manager IDOR test");
        return;
      }

      // Check ≥2 units
      adminHeaders = await restoreCookies(page, adminCookies);
      const unitsResp = await page.request.get(`${API_URL}/api/organization-units`, { headers: adminHeaders });
      const allUnits = await unitsResp.json();
      if (allUnits.length < 2) {
        test.skip(true, "Need ≥2 organization units for manager IDOR cross-unit test");
        return;
      }
      console.log(`Đơn vị gốc đọc được: ${allUnits.map((u: { id: number }) => u.id).join(",")}`);
    });

    // Early return if skipped
    if (!MANAGER_USERNAME || !MANAGER_PASSWORD) return;

    // --- Step 2: Manager login (with optional TOTP) ---
    //
    // Đăng nhập manager phải đi TRƯỚC việc dựng dữ liệu, vì phạm vi của
    // manager là `user.unit_id` của CHÍNH manager
    // (`lead_service.py:3736` — `MANAGER và unit_id != None → (None,
    // user.unit_id)`, KHÔNG mở rộng xuống đơn vị con).
    //
    // Bản cũ so phạm vi manager với `unitId` — mà `unitId` là đơn vị của
    // OFFICER. Seed đặt officer `vothithuthuhien` ở đơn vị #4 còn manager
    // `phanthithuyvan` ở đơn vị #11, nên "manager phải nhìn thấy lead1"
    // là một giả định SAI về quan hệ dữ liệu seed, không phải một bất biến
    // của sản phẩm. Ca này chưa từng chạy thật (serial mode dừng ở :517).
    await test.step("Manager login + đọc đơn vị của chính manager", async () => {
      managerHeaders = await loginViaAPI(
        page,
        MANAGER_USERNAME,
        MANAGER_PASSWORD,
        MANAGER_TOTP_SECRET ? { totpSecret: MANAGER_TOTP_SECRET } : undefined
      );
      managerCookies = await page.context().cookies();

      const meResp = await page.request.get(`${API_URL}/api/users/me`);
      await expectOk(meResp, "manager GET /api/users/me", [200]);
      const me = await meResp.json();
      expect(me.role, `Tài khoản "${MANAGER_USERNAME}" phải có role manager`).toBe(
        "manager"
      );
      expect(
        me.unit_id,
        `Manager #${me.id} không có unit_id ⇒ phạm vi rơi về "chỉ của mình" ` +
          `(lead_service.py:3739), ca kiểm phạm vi theo ĐƠN VỊ không còn nghĩa.`
      ).toBeTruthy();
      managerUnitId = me.unit_id;
      console.log(`Manager logged in: user #${me.id} unit=${managerUnitId}`);
    });

    // --- Step 3: Admin dựng hai chứng cứ: 1 lead TRONG đơn vị manager, 1 lead NGOÀI ---
    let unitBLeadId: number;
    let managerUnitLeadId: number;
    await test.step("Admin creates lead in unitB + lead in manager's unit", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // unitB = một đơn vị KHÁC đơn vị của manager.
      const unitsResp2 = await page.request.get(`${API_URL}/api/organization-units`, {
        headers: adminHeaders,
      });
      await expectOk(unitsResp2, "GET /api/organization-units", [200]);
      const roots = await unitsResp2.json();
      const other = roots.find((u: { id: number }) => u.id !== managerUnitId);
      expect(
        other,
        `Không tìm được đơn vị nào khác đơn vị #${managerUnitId} của manager ` +
          `trong ${roots.length} đơn vị gốc.`
      ).toBeTruthy();
      unitBId = other.id;
      console.log(`managerUnitId=${managerUnitId}, unitBId=${unitBId}`);

      const unitBLeadResp = await page.request.post(`${API_URL}/api/leads`, {
        headers: adminHeaders,
        data: {
          full_name: `E2E_UnitB_Lead_${Date.now()}`,
          phone: generatePhone(),
          source: "walk_in",
          unit_id: unitBId,
        },
      });
      await expectOk(unitBLeadResp, `admin tạo lead ở đơn vị #${unitBId}`, [200, 201]);
      unitBLeadId = (await unitBLeadResp.json()).id;

      const mgrLeadResp = await page.request.post(`${API_URL}/api/leads`, {
        headers: adminHeaders,
        data: {
          full_name: `E2E_MgrUnit_Lead_${Date.now()}`,
          phone: generatePhone(),
          source: "walk_in",
          unit_id: managerUnitId,
        },
      });
      await expectOk(
        mgrLeadResp,
        `admin tạo lead ở đơn vị #${managerUnitId} của manager`,
        [200, 201]
      );
      const mgrLeadBody = await mgrLeadResp.json();
      managerUnitLeadId = mgrLeadBody.id;
      expect(mgrLeadBody.unit_id).toBe(managerUnitId);
      console.log(
        `Chứng cứ: lead ngoài phạm vi #${unitBLeadId} (đơn vị #${unitBId}) · ` +
          `lead trong phạm vi #${managerUnitLeadId} (đơn vị #${managerUnitId})`
      );
    });

    // --- Step 4: Probe — check MFA enforcement ---
    await test.step("Probe manager API access (MFA check)", async () => {
      managerHeaders = await restoreCookies(page, managerCookies);

      const probeResp = await page.request.get(`${API_URL}/api/leads`, { headers: managerHeaders });
      if (probeResp.status() === 403) {
        const probeErr = await probeResp.json();
        console.log(`Manager probe failed 403: ${safeBody(probeErr)}`);
        if (/mfa|multi.factor/i.test(safeBody(probeErr))) {
          test.skip(
            true,
            "Manager MFA enforcement active but mfa_enabled=False — set E2E_MANAGER_TOTP_SECRET or enable MFA"
          );
          return;
        }
      }
      expect(probeResp.ok()).toBeTruthy();
      console.log("Manager probe succeeded");
    });

    // --- Step 5: Manager list → chỉ thấy lead trong ĐƠN VỊ CỦA MANAGER ---
    await test.step("Manager list — thấy lead cùng đơn vị, KHÔNG thấy lead unitB", async () => {
      managerHeaders = await restoreCookies(page, managerCookies);

      // page_size tối đa của `/api/leads` là 100 (Query(..., le=100)).
      const mgrListResp = await page.request.get(`${API_URL}/api/leads?page_size=100`, {
        headers: managerHeaders,
      });
      await expectOk(mgrListResp, "manager GET /api/leads", [200]);
      const mgrBody = await mgrListResp.json();

      // Dương tính: manager THẤY lead vừa tạo trong chính đơn vị mình.
      expect(
        mgrBody.leads.some((l: { id: number }) => l.id === managerUnitLeadId),
        `Manager (đơn vị #${managerUnitId}) phải thấy lead #${managerUnitLeadId} ` +
          `cùng đơn vị. Nhận ${mgrBody.leads.length} lead, total=${mgrBody.total_count}.`
      ).toBeTruthy();
      // Âm tính: manager KHÔNG thấy lead của đơn vị khác.
      expect(
        mgrBody.leads.find((l: { id: number }) => l.id === unitBLeadId),
        `Manager KHÔNG được thấy lead #${unitBLeadId} ở đơn vị #${unitBId}.`
      ).toBeFalsy();
      // Bất biến phạm vi: mọi lead trả về đều thuộc ĐƠN VỊ CỦA MANAGER.
      const ngoaiPhamVi = mgrBody.leads.filter(
        (l: { id: number; unit_id: number }) => l.unit_id !== managerUnitId
      );
      expect(
        ngoaiPhamVi.map((l: { id: number; unit_id: number }) => `#${l.id}@${l.unit_id}`),
        `Manager đơn vị #${managerUnitId} nhận được lead ngoài phạm vi.`
      ).toEqual([]);
      console.log(`Manager list: total_count=${mgrBody.total_count}, unitB lead hidden`);
    });

    // --- Step 6: Manager filter with unit_id=unitB → server override (no unitB results) ---
    await test.step("Manager filter unit_id=unitB → server scope override", async () => {
      managerHeaders = await restoreCookies(page, managerCookies);

      const overrideResp = await page.request.get(
        `${API_URL}/api/leads?unit_id=${unitBId}`,
        { headers: managerHeaders }
      );
      expect(overrideResp.ok()).toBeTruthy();
      const overrideBody = await overrideResp.json();
      expect(overrideBody.leads.find((l: { id: number }) => l.id === unitBLeadId)).toBeFalsy();
      console.log(`Manager unit_id=unitB override: unitB lead still hidden`);
    });

    // --- Step 7: Admin sees unitB lead with unit_id=unitB filter ---
    await test.step("Admin sees unitB lead — positive control", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const adminUnitBResp = await page.request.get(
        `${API_URL}/api/leads?unit_id=${unitBId}`,
        { headers: adminHeaders }
      );
      expect(adminUnitBResp.ok()).toBeTruthy();
      const adminUnitBBody = await adminUnitBResp.json();
      expect(adminUnitBBody.leads.some((l: { id: number }) => l.id === unitBLeadId)).toBeTruthy();
      console.log(`Admin sees unitB lead ${unitBLeadId}: confirmed`);
    });
  });
});

// ===========================================================================
// Test 8C — ĐỘC LẬP: Terminal Status Hard Block
// ===========================================================================
//
// BẤT BIẾN ĐƯỢC CANH: một lead ở trạng thái TERMINAL (`is_final=true`) phải
// TỪ CHỐI consultation mới bằng 400.
//
// VÌ SAO NÓ NẰM Ở DESCRIBE RIÊNG — ba sự thật đo được, không phải sở thích:
//
//  1. `Lead Management Workflow` chạy `mode: "serial"`. Test 6 (import CSV)
//     đang đỏ ⇒ Playwright **skip** test 7..10, chúng in ra "did not run".
//     Ca terminal nằm trong test 8 nên nó CHƯA TỪNG thực thi lần nào — kể cả
//     những đêm nightly có nó trong tệp. Một ca không chạy không canh gì cả.
//  2. Chạy riêng bằng `-g "terminal"` cũng hỏng: test 8 đọc `adminCookies`,
//     `adminHeaders`, `offeringId`, `unitId`, `initialStatusId` — toàn biến
//     module do test 1 gán. Lọc `-g` bỏ test 1 ⇒ `adminCookies` là `[]` ⇒
//     `GET /api/pipeline/all` đi ra không phiên.
//  3. Describe này KHÔNG chia sẻ một biến module nào với describe trên. Nó tự
//     đăng nhập vào `APIRequestContext` RIÊNG (`loginPrincipal`), tự khám phá
//     pipeline / đơn vị / offering, tự tạo lead. Test 6 đỏ hay xanh không đổi
//     được gì ở đây.
//
// BA ĐIỀU KHÔNG ĐƯỢC NỚI, dù có vẻ tiện:
//  * 401/403/500 TUYỆT ĐỐI không được biến thành `return` coi như thành công.
//    Bản cũ có đúng hai đường như thế (`if (!enrolledFinalStatusId) return;`
//    và `if (!patchResp.ok()) { expect(status).not.toBe(422); return; }`);
//    đường sau chỉ loại 422 nên 401/403/500 lọt qua rồi `return` — ca xanh mà
//    không đo gì.
//  * Tiền đề `is_final` phải được CHỨNG MINH bằng cách ĐỌC LẠI lead, không
//    được suy từ "PATCH trả 200". Chưa terminal thì một 400 ở bước cuối có thể
//    đến từ bất kỳ luật nào khác, và phép kiểm đo nhầm thứ khác.
//  * Không đường nào tới được terminal ⇒ ĐỎ kèm chẩn đoán TỪNG LƯỢT THỬ.
test.describe("Lead terminal hard block — độc lập", () => {
  test.describe.configure({ timeout: 300_000, mode: "serial" });

  let terminalAdmin: Principal | undefined;

  test.afterAll(async () => {
    await terminalAdmin?.dispose();
  });

  test("Terminal lead chặn consultation mới bằng 400", async ({ playwright }) => {
    // --- 1. Phiên RIÊNG, không mượn cookie của bất kỳ test nào ---
    await test.step("Admin login (APIRequestContext riêng)", async () => {
      terminalAdmin = await loginPrincipal(playwright.request, {
        label: "admin-terminal",
        username: ADMIN_USERNAME,
        password: ADMIN_PASSWORD,
        totpSecret: ADMIN_TOTP_SECRET,
      });
      expect(
        terminalAdmin.user.role,
        `Tài khoản "${ADMIN_USERNAME}" phải có role admin để PATCH status tự do`
      ).toBe("admin");
      console.log(
        `admin-terminal: user #${terminalAdmin.user.id} role=${terminalAdmin.user.role}`
      );
    });
    const admin = terminalAdmin as Principal;

    // --- 2. Khám phá pipeline / đơn vị / offering qua CHÍNH jar ấy ---
    type FullStatus = {
      id: string;
      name: string;
      phase: string;
      is_final: boolean;
      outcome_type: string;
    };
    let finalIds = new Set<string>();
    let candidates: string[] = [];
    let nonFinalStatusId = "";
    let leadId = 0;

    await test.step("Khám phá pipeline + tạo lead của riêng ca này", async () => {
      const pipeResp = await admin.ctx.get(`${API_URL}/api/pipeline/all`);
      await expectOk(pipeResp, "GET /api/pipeline/all (khám phá)", [200]);
      const pipeline = await pipeResp.json();
      const statuses = pipeline.statuses as FullStatus[];
      const transitions: Array<{ from_status_id: string; to_status_id: string }> =
        pipeline.allowed_transitions || [];

      finalIds = new Set(statuses.filter((s) => s.is_final).map((s) => s.id));
      expect(
        finalIds.size,
        "Seed không có trạng thái nào `is_final=true` — không thể canh bất biến " +
          "terminal. Đây là lỗi dữ liệu seed, KHÔNG phải lý do bỏ qua phép kiểm."
      ).toBeGreaterThan(0);

      // Thứ tự ưu tiên: `enrolled` (ca thật hay gặp) → âm-cuối-cùng của
      // consultation → MỌI trạng thái final còn lại. Thử đủ, không dừng ở hai.
      const uuTien = [
        ...statuses.filter((s) => s.is_final && s.phase === "enrolled"),
        ...statuses.filter(
          (s) => s.is_final && s.outcome_type === "negative" && s.phase === "consultation"
        ),
        ...statuses.filter((s) => s.is_final),
      ];
      candidates = [...new Set(uuTien.map((s) => s.id))];

      // Trạng thái KHỞI ĐIỂM cho lượt POST bị chặn: phải KHÔNG final, nếu
      // không thì một 400 có thể đến từ chính luật "không nhảy vào final".
      const batDau =
        transitions.find((t) => !finalIds.has(t.from_status_id))?.from_status_id ??
        statuses.find((s) => !s.is_final)?.id;
      expect(
        batDau,
        "Seed không có trạng thái KHÔNG-final nào để làm status khởi điểm"
      ).toBeTruthy();
      nonFinalStatusId = batDau as string;

      // Đơn vị đọc RA TỪ officer thật (cặp đơn vị/officer luôn tương thích),
      // không lấy `units[0]` rời rạc.
      const officer = await pickAssignableOfficer(admin.ctx);
      const offResp = await admin.ctx.get(
        `${API_URL}/api/program-offerings?is_active=true&limit=1`
      );
      await expectOk(offResp, "GET /api/program-offerings", [200]);
      const offerings = await offResp.json();
      expect(
        offerings.length,
        "Seed không có program-offering active nào"
      ).toBeGreaterThan(0);

      const createResp = await admin.ctx.post(`${API_URL}/api/leads`, {
        headers: admin.headers,
        data: {
          full_name: `E2E_TerminalSolo_${Date.now()}`,
          phone: generatePhone(),
          source: "walk_in",
          offering_id: offerings[0].id,
          unit_id: officer.unit_id,
        },
      });
      await expectOk(createResp, "admin tạo lead cho ca terminal block", [200, 201]);
      leadId = (await createResp.json()).id;
      console.log(
        `Lead #${leadId} (unit ${officer.unit_id}) · ${candidates.length} ứng viên ` +
          `terminal · status khởi điểm ${nonFinalStatusId}`
      );
    });

    // --- 3. Đưa lead tới terminal, thử MỌI đường, không `return` giữa chừng ---
    let reached: string | null = null;
    const attempts: string[] = [];

    await test.step("Đưa lead tới trạng thái terminal", async () => {
      for (const statusId of candidates) {
        const leadResp = await admin.ctx.get(`${API_URL}/api/leads/${leadId}`);
        await expectOk(leadResp, `GET lead #${leadId} lấy version`, [200]);
        const version = (await leadResp.json()).version as number;

        // Đường 1 — PATCH status (`LeadStatusUpdate` bắt buộc `version`).
        const patchResp = await admin.ctx.patch(
          `${API_URL}/api/leads/${leadId}/status`,
          {
            headers: admin.headers,
            data: { consultation_status_id: statusId, version },
          }
        );
        if (patchResp.ok()) {
          reached = statusId;
          break;
        }
        attempts.push(
          `PATCH status → ${statusId}: ` +
            summarizeApiError(patchResp.status(), await patchResp.text())
        );

        // Đường 2 — POST consultation kèm `loss_reason_code`, đúng đường sản
        // phẩm mà UI dùng khi đóng lead ở trạng thái âm.
        const consResp = await admin.ctx.post(
          `${API_URL}/api/leads/${leadId}/consultations`,
          {
            headers: admin.headers,
            data: {
              status_id: statusId,
              method: "phone",
              notes: "E2E: đưa lead sang trạng thái terminal",
              loss_reason_code: "NO_CONTACT",
              loss_reason_note: "E2E terminal setup",
            },
          }
        );
        if (consResp.ok()) {
          reached = statusId;
          break;
        }
        attempts.push(
          `POST consultation → ${statusId}: ` +
            summarizeApiError(consResp.status(), await consResp.text())
        );
      }

      expect(
        reached,
        `Không đường nào đưa lead #${leadId} tới trạng thái terminal. ` +
          `Đã thử ${candidates.length} trạng thái × 2 đường — ${attempts.join(" ｜ ")}`
      ).not.toBeNull();
    });

    // --- 4. TIỀN ĐỀ phải được CHỨNG MINH, không được giả định ---
    let afterStatusId = "";
    await test.step("Chứng minh lead ĐANG ở trạng thái is_final", async () => {
      await assertPrincipal(admin);
      const afterResp = await admin.ctx.get(`${API_URL}/api/leads/${leadId}`);
      await expectOk(afterResp, `GET lead #${leadId} sau chuyển terminal`, [200]);
      afterStatusId = (await afterResp.json()).consultation_status_id as string;
      expect(
        finalIds.has(afterStatusId),
        `Lead #${leadId} phải đang ở trạng thái is_final sau khi chuyển; thực tế ` +
          `đang ở ${afterStatusId}. Chuyển được nhưng không terminal ⇒ phép kiểm ` +
          `dưới đây sẽ đo nhầm luật khác. Các lượt đã thử: ${attempts.join(" ｜ ")}`
      ).toBe(true);
      console.log(`Lead ở trạng thái terminal: ${afterStatusId} (qua ${reached})`);
    });

    // --- 5. Phép kiểm thật — CHẠY VÔ ĐIỀU KIỆN ---
    await test.step("Consultation mới trên lead terminal phải 400", async () => {
      const blockResp = await admin.ctx.post(
        `${API_URL}/api/leads/${leadId}/consultations`,
        {
          headers: admin.headers,
          data: {
            status_id: nonFinalStatusId,
            method: "phone",
            notes: "E2E: should be hard blocked",
          },
        }
      );
      // Đọc thân MỘT LẦN rồi parse: `APIResponse` của Playwright không có
      // `clone()`, và gọi `.text()` sau `.json()` là đọc lại cùng bộ đệm.
      const blockText = await blockResp.text();
      expect(
        blockResp.status(),
        `Lead terminal ${afterStatusId} phải CHẶN consultation mới bằng 400. ` +
          summarizeApiError(blockResp.status(), blockText)
      ).toBe(400);
      const blockErr = JSON.parse(blockText) as { detail?: string };
      expect(blockErr.detail).toMatch(
        /nhập học|enrolled|hoàn tất|hard.block|terminal|kết thúc/i
      );
      console.log(`Hard block confirmed: 400 — ${safeBody({ detail: blockErr.detail })}`);
    });
  });
});
