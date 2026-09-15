/**
 * E2E Test: Lead to Admission Complete Workflow
 *
 * Coverage:
 *   Phase 1: lead creation → admin assign → UI "Cán bộ" column verify →
 *            officer reassign → API null+reassign_pending → UI "Chưa gán" →
 *            admin re-assign → UI officer name returns →
 *            2 consultations (FSM transition) → UI status+stage badge
 *   Phase 2: admission profile (fill + docs) → submit →
 *            UI list: verify "Chờ duyệt" badge
 *   Phase 3: admin approve → UI detail: verify "Đã duyệt"
 *   Phase 4: admin override → admin finalize →
 *            UI detail: verify "Đã nhập học" + all 6 action buttons NOT visible
 *   Phase 5: 2nd lead → submit → reject → UI "Từ chối" →
 *            resubmit → request revision → UI "Yêu cầu bổ sung" →
 *            resubmit → UI "Đã nộp lại" → approve → UI "Đã duyệt"
 *
 * Finance tested separately in finance-lifecycle.spec.ts (maker-checker).
 * Withdraw excluded (no public API route).
 *
 * Chạy:
 *   npx playwright test lead-to-admission-workflow --project=e2e-workflow --reporter=list
 *   npx playwright test lead-to-admission-workflow --project=e2e-workflow --headed
 */

import { test, expect, type Page, type Cookie } from "@playwright/test";
import { FIXTURE_MA_XA, FIXTURE_TINH, FIXTURE_XA, createAdmissionProfile, expectOk, fixtureAcademicHistory, resolveAdmissionContext, resolveFixtureSchoolId, safeBody, summarizeApiError, type AdmissionPathContext, xacThucMfa } from "./helpers/e2e-fixtures";

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

// Vietnamese labels from columns.tsx:38-48
const LABEL = {
  draft: "Nháp",
  submitted: "Chờ duyệt",
  resubmitted: "Đã nộp lại",
  approved: "Đã duyệt",
  rejected: "Từ chối",
  revision_requested: "Yêu cầu bổ sung",
  confirmed: "Đã xác nhận",
  overridden: "Đã override",
  enrolled: "Đã nhập học",
} as const;

// Action button labels from AdmissionActions.tsx:208-286
const ACTION = {
  approve: "Phê duyệt",       // :215
  reject: "Từ chối",           // :226 (button text, not badge)
  claim: "Nhận duyệt",         // :236
  unclaim: "Bỏ nhận",          // :261
  enroll: "Xác nhận nhập học",  // :285
  resubmit: "Nộp lại hồ sơ",   // :187
} as const;

// ---------------------------------------------------------------------------
// Shared state (serial execution)
// ---------------------------------------------------------------------------

let adminHeaders: Record<string, string> = {};
let adminCookies: Cookie[] = [];
let officerHeaders: Record<string, string> = {};
let officerCookies: Cookie[] = [];

// Discovery (dynamic, not hardcoded)
let unitId: number;
let offeringId: number;
let admissionMethodId: number;
/**
 * (offering, path, round, năm, phương thức) từ MỘT AdmissionPath — nguồn
 * chuẩn `GET /api/admission-config/paths/for-offering/{id}`, đúng thứ UI
 * dùng. `AdmissionProfileCreate` đòi đủ bốn trường; payload hai trường của
 * bản cũ trả 422 (đo thật ở :614 của nightly 34678745325).
 */
let pathContext: AdmissionPathContext;
let initialStatusId: string;
let secondStatusId: string;
let officerUserId: number;
let officerFullName: string;

// Happy path (Phase 1-4)
let leadId1: number;
let leadName1: string;
let leadPhone1: string;
let profileId1: number;
let profileVersion1: number;

// Rejection + recovery path (Phase 5)
let leadId2: number;
let leadName2: string;
let profileId2: number;
let profileVersion2: number;

// ---------------------------------------------------------------------------
// Helpers (from admission-lifecycle.spec.ts, self-contained)
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
  response: import("@playwright/test").APIResponse
): Promise<string | undefined> {
  const setCookieHeaders = response
    .headersArray()
    .filter((h) => h.name.toLowerCase() === "set-cookie");
  let csrf: string | undefined;

  for (const h of setCookieHeaders) {
    const m = h.value.match(/^([^=]+)=([^;]+)/);
    if (!m) continue;
    await page.context().addCookies([
      {
        name: m[1].trim(),
        value: m[2],
        domain: new URL(API_URL).hostname,
        path: "/",
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
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.context().clearCookies();

    const loginResp = await page.request.post(`${API_URL}/api/auth/login`, {
      form: { username, password },
    });
    if (loginResp.status() === 429) {
      console.log(
        `Login rate limited for ${username}, waiting 65s (attempt ${attempt + 1})...`
      );
      await new Promise((r) => setTimeout(r, 65_000));
      continue;
    }
    if (!loginResp.ok()) {
      throw new Error(
        `Login failed for ${username}: ${loginResp.status()} ${summarizeApiError(loginResp.status(), await loginResp.text())}`
      );
    }

    const loginBody = await loginResp.json();
    let authResp = loginResp;

    if (loginBody.mfa_required) {
      if (!opts?.totpSecret)
        throw new Error(`MFA required for ${username} but no TOTP secret`);
      // Điều phối viên TOTP giữ khoá tài khoản xuyên qua lượt gửi này, nên hai
      // tiến trình `npx playwright test` không bao giờ tiêu cùng một counter.
      // Hỏng ⇒ NÉM NGAY: nhánh `sleep(31s); continue` cũ biến mọi nguyên nhân
      // (mật khẩu sai, tài khoản bị khoá, MFA bị tắt) thành cùng một thất bại
      // sau 93 giây, và còn đốt hạn mức đăng nhập.
      authResp = await xacThucMfa(
        username,
        opts.totpSecret,
        loginBody.mfa_token,
        (payload) =>
          page.request.post(`${API_URL}/api/auth/verify-mfa`, { data: payload })
      );
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
  if (cookies.length > 0) await page.context().addCookies(cookies);
  const csrf = await getCSRFToken(page);
  return csrf ? { "X-CSRF-Token": csrf } : {};
}

/** Resilient table selector (from admission-ui-smoke.spec.ts:128) */
const TABLE_SELECTOR =
  "table, [role='table'], [data-testid='admissions-list']";

// ---------------------------------------------------------------------------
// Tài liệu bắt buộc — NỘP rồi XÁC MINH, một nguồn chuẩn cho CẢ HAI chỗ dựng
// hồ sơ trong tệp này (test 8 "happy path" và test 16 "rejection path").
// ---------------------------------------------------------------------------

/** Một dòng `documents_checklist` — chỉ những trường harness thật sự đọc. */
interface ChecklistItem {
  code: string;
  status: "missing" | "uploaded" | "verified" | "rejected" | "paper_submitted";
  is_mandatory?: boolean | null;
  requires_upload?: boolean | null;
}

/**
 * Đọc `documents_checklist` của hồ sơ — FAIL-CLOSED.
 *
 * Bản cũ gọi `page.request.get(...)` rồi `await getResp.json()` thẳng, không
 * nhìn status lần nào: một 401/404/500 sẽ cho `fresh.documents_checklist ===
 * undefined`, `missingDocs` rỗng, vòng upload chạy 0 lần, và test vẫn đi tiếp
 * tới `submit` như thể đã nộp đủ giấy tờ.
 */
async function fetchChecklist(
  page: Page,
  profileId: number,
  headers: Record<string, string>,
  label: string
): Promise<{ version: number; checklist: ChecklistItem[] }> {
  const resp = await page.request.get(
    `${API_URL}/api/admissions/${profileId}`,
    { headers }
  );
  await expectOk(resp, `GET /api/admissions/${profileId} (${label})`, [200]);
  const body = (await resp.json()) as {
    version: number;
    documents_checklist?: ChecklistItem[] | null;
  };
  expect(
    Array.isArray(body.documents_checklist),
    `${label}: hồ sơ #${profileId} không trả về documents_checklist dạng mảng — ` +
      `${safeBody(body)}`
  ).toBeTruthy();
  return { version: body.version, checklist: body.documents_checklist ?? [] };
}

/**
 * Đưa MỌI tài liệu bắt buộc của hồ sơ về trạng thái ĐÃ XÁC MINH, rồi khẳng
 * định điều đó TRƯỚC khi test gọi `submit`.
 *
 * VÌ SAO PHẢI CÓ BƯỚC VERIFY — dẫn mã, không suy đoán:
 *   `admission_service._validate_documents` (:1255-1260) ở chế độ NGHIÊM
 *   (`applied_rules.allow_unverified_submission == false`) chỉ tính tài liệu
 *   `verified` / `paper_submitted` là đã nộp; một tài liệu mới `uploaded`
 *   rơi vào `pending_verify_codes` và sinh lỗi *"Tài liệu {code} chưa được
 *   xác minh…"* (:1284). `submit_and_evaluate` trả lỗi ấy dưới dạng
 *   **HTTP 200 + `{"status":"draft","validation_errors":[…]}`** (:7121-7123)
 *   chứ KHÔNG phải 4xx — nên một harness chỉ nhìn `resp.ok()` sẽ thấy "xanh"
 *   ở mọi request rồi ngã ở dòng `expect(status).toBe("submitted")` mà không
 *   nói được vì sao.
 *
 * AI ĐƯỢC VERIFY: `DocumentActionPolicy.authorize("verify", …)`
 *   (`app/services/admission_document_policy.py`) đòi `reviewer_scope` =
 *   **admin HOẶC manager cùng đơn vị**; officer — kể cả officer phụ trách —
 *   KHÔNG có quyền. Casbin cũng chỉ cấp route cho manager
 *   (`policy_templates.py:648`, admin thừa kế qua wildcard `/*`). Vì vậy hàm
 *   này ĐỔI sang principal admin đúng cho bước verify rồi trả officer về.
 *
 * ENDPOINT: `PATCH /api/admissions/{profile_id}/documents/{doc_code}/verify-format`
 *   (`app/routers/admissions.py:1187-1194`), thân `{"format": "original" |
 *   "certified_copy" | "photo"}` (`schemas.DocumentFormatVerifyRequest`).
 *   Phương thức là **PATCH** — POST vào đúng URL ấy trả 405.
 *
 * Trả về `version` mới nhất của hồ sơ, đọc bằng principal officer (chính
 * người sẽ gọi `submit`).
 */
async function satisfyMandatoryDocuments(
  page: Page,
  profileId: number,
  label: string
): Promise<number> {
  // --- 1. NỘP (officer) --------------------------------------------------
  let officerHdrs = await restoreCookies(page, officerCookies);
  let { checklist } = await fetchChecklist(
    page,
    profileId,
    officerHdrs,
    `${label} · trước khi nộp giấy tờ`
  );

  const mandatoryCodes = checklist
    .filter((d) => d.is_mandatory)
    .map((d) => d.code);
  expect(
    mandatoryCodes.length,
    `${label}: hồ sơ #${profileId} KHÔNG có tài liệu bắt buộc nào — ` +
      `fixture sai thì phép kiểm "đã xác minh" không canh gì cả`
  ).toBeGreaterThan(0);

  for (const doc of checklist.filter(
    (d) => d.is_mandatory && d.status === "missing"
  )) {
    if (doc.requires_upload === false) {
      // Tài liệu chỉ nộp GIẤY: không có đường upload, `authorize("upload")`
      // đòi `requires_upload === true` nên POST /upload sẽ 404.
      const paperResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId}/documents/${doc.code}/paper-submitted`,
        {
          headers: officerHdrs,
          data: { actual_submission_format: "photo" },
        }
      );
      await expectOk(
        paperResp,
        `POST paper-submitted ${doc.code} (${label})`,
        [200]
      );
    } else {
      const upResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId}/documents/${doc.code}/upload`,
        {
          headers: officerHdrs,
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
      await expectOk(upResp, `POST upload ${doc.code} (${label})`, [200]);
    }
  }

  // --- 2. ĐỌC LẠI bằng officer: cái gì còn chờ xác minh ------------------
  ({ checklist } = await fetchChecklist(
    page,
    profileId,
    officerHdrs,
    `${label} · sau khi nộp giấy tờ`
  ));
  const pendingVerify = checklist.filter(
    (d) => d.is_mandatory && d.status === "uploaded"
  );

  // --- 3. XÁC MINH bằng ADMIN (officer không có quyền) -------------------
  const adminHdrs = await restoreCookies(page, adminCookies);
  for (const doc of pendingVerify) {
    const vResp = await page.request.patch(
      `${API_URL}/api/admissions/${profileId}/documents/${doc.code}/verify-format`,
      { headers: adminHdrs, data: { format: "photo" } }
    );
    await expectOk(
      vResp,
      `PATCH verify-format ${doc.code} (${label})`,
      [200]
    );
  }

  // --- 4. ĐỌC LẠI và KHẲNG ĐỊNH trạng thái trước khi submit --------------
  // Khẳng định trên ảnh chụp MỚI đọc từ server, không phải trên thân phản
  // hồi của chính lệnh verify: một lệnh verify trả 200 mà không đổi trạng
  // thái vẫn phải làm ca này ĐỎ.
  const after = await fetchChecklist(
    page,
    profileId,
    adminHdrs,
    `${label} · sau khi xác minh`
  );
  for (const doc of after.checklist.filter((d) => d.is_mandatory)) {
    const mong = doc.requires_upload === false ? "paper_submitted" : "verified";
    expect(
      doc.status,
      `${label}: tài liệu bắt buộc ${doc.code} phải ở "${mong}" TRƯỚC khi nộp ` +
        `hồ sơ (chế độ nghiêm: chỉ verified/paper_submitted mới tính là đã nộp)`
    ).toBe(mong);
  }
  console.log(
    `${label}: ${mandatoryCodes.length} tài liệu bắt buộc — ` +
      `đã xác minh ${pendingVerify.length} qua PATCH verify-format (admin)`
  );

  // --- 5. Trả principal officer + version mới nhất -----------------------
  officerHdrs = await restoreCookies(page, officerCookies);
  const cuoi = await fetchChecklist(
    page,
    profileId,
    officerHdrs,
    `${label} · lấy version trước submit`
  );
  return cuoi.version;
}

// ---------------------------------------------------------------------------
// Test Suite
// ---------------------------------------------------------------------------

test.describe("Lead to Admission Workflow", () => {
  test.describe.configure({ mode: "serial", timeout: 600_000 });
  // Tra một lần ở bước Setup rồi dùng lại — id trường là số tự tăng nên
  // hard-code sẽ vỡ khi thứ tự seed đổi.
  let fixtureSchoolId = 0;

  // =========================================================================
  // SETUP
  // =========================================================================

  test("Setup: login admin + officer, discover resources", async ({
    page,
  }) => {
    // Admin login (MFA)
    adminHeaders = await loginViaAPI(page, ADMIN_USERNAME, ADMIN_PASSWORD, {
      totpSecret: ADMIN_TOTP_SECRET,
    });
    adminCookies = await page.context().cookies();
    console.log("Admin logged in");

    // Officer login (no MFA)
    officerHeaders = await loginViaAPI(page, OFFICER_USERNAME, OFFICER_PASSWORD);
    officerCookies = await page.context().cookies();
    console.log("Officer logged in");

    // Discover resources (dynamic — pattern from lead-workflow.spec.ts:243)
    adminHeaders = await restoreCookies(page, adminCookies);

    // Tra `school_id` của fixture — PHẢI sau khi đăng nhập, endpoint này đòi
    // xác thực (đặt trước login thì 401 INVALID_TOKEN).
    fixtureSchoolId = await resolveFixtureSchoolId(page.request);

    const pipelineResp = await page.request.get(
      `${API_URL}/api/pipeline/all`
    );
    await expectOk(pipelineResp, "GET /api/pipeline/all", [200]);
    const pipeline = await pipelineResp.json();
    const transitions: Array<{
      from_status_id: string;
      to_status_id: string;
    }> = pipeline.allowed_transitions || [];
    expect(pipeline.statuses.length).toBeGreaterThanOrEqual(2);

    if (transitions.length > 0) {
      initialStatusId = transitions[0].from_status_id;
      secondStatusId = transitions[0].to_status_id;
    } else {
      initialStatusId = pipeline.statuses[0].id;
      secondStatusId = pipeline.statuses[1].id;
    }

    const unitsResp = await page.request.get(
      `${API_URL}/api/organization-units`
    );
    await expectOk(unitsResp, "GET /api/organization-units", [200]);
    unitId = (await unitsResp.json())[0]?.id;
    expect(unitId).toBeTruthy();

    // Discover officer profile FIRST (need unit_id for offering filter)
    officerHeaders = await restoreCookies(page, officerCookies);
    const meResp = await page.request.get(`${API_URL}/api/profile`, {
      headers: officerHeaders,
    });
    await expectOk(meResp, "GET /api/profile (officer)", [200]);
    const me = await meResp.json();
    officerUserId = me.id;
    officerFullName = me.full_name;
    expect(officerUserId).toBeTruthy();
    expect(officerFullName).toBeTruthy();
    // Use officer's unit for lead creation (IDOR requires same unit)
    if (me.unit_id) unitId = me.unit_id;

    // Discover offering + method — filter by officer's unit scope
    adminHeaders = await restoreCookies(page, adminCookies);
    const offeringsResp = await page.request.get(
      `${API_URL}/api/program-offerings?is_active=true&limit=50`
    );
    await expectOk(offeringsResp, "GET /api/program-offerings", [200]);
    const allOfferings: Array<{ id: number; program?: { unit_id?: number } }> =
      await offeringsResp.json();

    // Ưu tiên offering thuộc đơn vị officer, NHƯNG chỉ chấp nhận offering
    // thật sự CÓ admission path dùng được — `create_profile` tra path theo
    // bộ ba (round, academic_info, method), không có path là 400.
    const unitOffering = allOfferings.find((o) => o.program?.unit_id === unitId);
    pathContext = await resolveAdmissionContext(page.request, {
      preferOfferingIds: unitOffering ? [unitOffering.id] : [],
    });
    offeringId = pathContext.offeringId;
    admissionMethodId = pathContext.admissionMethodId;

    console.log(
      `Config: unit=${unitId} offering=${offeringId} method=${admissionMethodId} status=${initialStatusId}→${secondStatusId} officer=${officerUserId}(${officerFullName})`
    );
  });

  // =========================================================================
  // PHASE 1: Lead → Consultation → UI Verify
  // =========================================================================

  test.describe("Phase 1: Lead Ownership + Consultation", () => {
    test("1. Admin creates lead (unassigned)", async ({ page }) => {
      // Admin creates lead WITHOUT offering_id, WITH unit_id → lead starts unassigned.
      // This ensures test 2 covers a real unassigned→assigned transition.
      // Per LeadCreate schema: admin without offering_id must provide unit_id.
      adminHeaders = await restoreCookies(page, adminCookies);
      leadPhone1 = generatePhone();
      leadName1 = `E2E_Flow_${Date.now()}`;

      const resp = await page.request.post(`${API_URL}/api/leads`, {
        headers: adminHeaders,
        data: {
          full_name: leadName1,
          phone: leadPhone1,
          source: "walk_in",
          unit_id: unitId,
          // No offering_id, no assigned_officer_id → lead created unassigned
        },
      });
      if (!resp.ok() && resp.status() !== 201) {
        throw new Error(
          `Admin create lead failed (${resp.status()}): ${summarizeApiError(resp.status(), await resp.text())}`
        );
      }
      const body = await resp.json();
      leadId1 = body.id;
      // Admin-created lead without assigned_officer_id → should be unassigned
      expect(body.assigned_officer_id).toBeNull();
      console.log(
        `Lead created by admin: id=${leadId1}, assigned_officer_id=null`
      );
    });

    test("2. Admin assigns lead → UI shows officer in 'Cán bộ' column", async ({
      page,
    }) => {
      // Admin assigns lead to officer
      adminHeaders = await restoreCookies(page, adminCookies);
      const assignResp = await page.request.post(
        `${API_URL}/api/leads/${leadId1}/assign`,
        {
          headers: adminHeaders,
          data: { officer_id: officerUserId },
        }
      );
      expect(assignResp.ok()).toBeTruthy();
      const assignedLead = await assignResp.json();
      expect(assignedLead.assigned_officer_id).toBe(officerUserId);
      console.log(`Lead assigned to officer ${officerUserId}`);

      // UI verify: officer name in "Cán bộ" column (LeadsTable.tsx:480)
      await page.goto("/leads");
      await page.waitForLoadState("domcontentloaded");
      const leadRow = page.locator("tr").filter({ hasText: leadName1 });
      await expect(leadRow.first()).toBeVisible({ timeout: 15_000 });
      await expect(leadRow.first()).toContainText(officerFullName);
      console.log(`UI: Lead row shows officer "${officerFullName}"`);
    });

    test("3. Officer reassigns own lead → API null + UI 'Chưa gán'", async ({
      page,
    }) => {
      officerHeaders = await restoreCookies(page, officerCookies);

      // Check quota first — skip if exhausted (data accumulation from prior runs).
      // FAIL-CLOSED trên chính lượt ĐỌC hạn mức: `if (quotaResp.ok())` cũ coi
      // một 401/500 là "cứ chạy tiếp", tức chính cái nhánh mà bước kiểm này
      // sinh ra để canh lại bị bỏ qua im lặng.
      const quotaResp = await page.request.get(
        `${API_URL}/api/leads/my/reassign-quota`,
        { headers: officerHeaders }
      );
      await expectOk(quotaResp, "GET /api/leads/my/reassign-quota", [200]);
      {
        const quota = await quotaResp.json();
        if (!quota.allowed) {
          console.log(
            `SKIP: Officer reassign quota exhausted (${quota.used}/${quota.limit}). ` +
            `Clean test data or wait for weekly reset.`
          );
          test.skip();
          return;
        }
      }

      // Officer reassigns via POST /api/leads/{id}/action
      const reassignResp = await page.request.post(
        `${API_URL}/api/leads/${leadId1}/action`,
        {
          headers: officerHeaders,
          data: { action: "reassign", reason: "E2E: Testing reassign flow" },
        }
      );
      if (!reassignResp.ok()) {
        throw new Error(`Reassign failed (${reassignResp.status()}): ${summarizeApiError(reassignResp.status(), await reassignResp.text())}`);
      }
      const reassigned = await reassignResp.json();

      // API verify: officer cleared, status = reassign_pending
      expect(reassigned.assigned_officer_id).toBeNull();
      expect(reassigned.assignment_status).toBe("reassign_pending");
      console.log(
        `Lead reassigned: officer=null, status=${reassigned.assignment_status}`
      );

      // UI verify: "Cán bộ" column shows "Chưa gán" fallback (LeadsTable.tsx:480)
      // Need admin context to see reassigned lead (officer lost access after reassign)
      adminHeaders = await restoreCookies(page, adminCookies);
      await page.goto("/leads");
      await page.waitForLoadState("domcontentloaded");
      const leadRow = page.locator("tr").filter({ hasText: leadName1 });
      await expect(leadRow.first()).toBeVisible({ timeout: 15_000 });
      // Officer name must NOT appear
      await expect(leadRow.first()).not.toContainText(officerFullName);
      // "Chưa gán" fallback must appear
      await expect(leadRow.first()).toContainText("Chưa gán");
      console.log('UI: Lead row shows "Chưa gán" (officer removed)');
    });

    test("4. Admin re-assigns lead → officer name returns", async ({
      page,
    }) => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const assignResp = await page.request.post(
        `${API_URL}/api/leads/${leadId1}/assign`,
        {
          headers: adminHeaders,
          data: { officer_id: officerUserId },
        }
      );
      expect(assignResp.ok()).toBeTruthy();
      const lead = await assignResp.json();
      expect(lead.assigned_officer_id).toBe(officerUserId);
      console.log(`Lead re-assigned to officer ${officerUserId}`);

      // UI verify: officer name back
      await page.goto("/leads");
      await page.waitForLoadState("domcontentloaded");
      const leadRow = page.locator("tr").filter({ hasText: leadName1 });
      await expect(leadRow.first()).toBeVisible({ timeout: 15_000 });
      await expect(leadRow.first()).toContainText(officerFullName);
      console.log(`UI: Officer "${officerFullName}" back in lead row`);
    });

    test("5. Officer sets offering on lead (required for admission)", async ({
      page,
    }) => {
      // Lead was created without offering_id for ownership test.
      // Admission requires offering → update lead with offering_id now.
      officerHeaders = await restoreCookies(page, officerCookies);
      const resp = await page.request.put(
        `${API_URL}/api/leads/${leadId1}`,
        {
          headers: officerHeaders,
          data: { offering_id: offeringId },
        }
      );
      // `expect(resp.ok()).toBeTruthy()` cũ in đúng "Received: false" — không
      // status, không error_code. `expectOk` giữ nguyên độ chặt và thêm chẩn đoán.
      await expectOk(resp, `PUT /api/leads/${leadId1} (gán offering)`, [200]);
      const lead = await resp.json();
      expect(lead.offering_id).toBe(offeringId);
      console.log(`Lead updated: offering_id=${offeringId}`);
    });

    test("6. Officer adds consultations, FSM status transitions", async ({
      page,
    }) => {
      officerHeaders = await restoreCookies(page, officerCookies);

      // First consultation with initial status
      const resp1 = await page.request.post(
        `${API_URL}/api/leads/${leadId1}/consultations`,
        {
          headers: officerHeaders,
          data: {
            status_id: initialStatusId,
            method: "phone",
            notes: "E2E: Initial contact",
          },
        }
      );
      expect(resp1.ok() || resp1.status() === 201).toBeTruthy();

      // Second consultation with next status (verify FSM transition works)
      const resp2 = await page.request.post(
        `${API_URL}/api/leads/${leadId1}/consultations`,
        {
          headers: officerHeaders,
          data: {
            status_id: secondStatusId,
            method: "phone",
            notes: "E2E: Follow-up, interested",
          },
        }
      );
      expect(resp2.ok() || resp2.status() === 201).toBeTruthy();

      // Verify lead status updated
      const leadResp = await page.request.get(
        `${API_URL}/api/leads/${leadId1}`,
        { headers: officerHeaders }
      );
      await expectOk(leadResp, `GET /api/leads/${leadId1} (kiểm trạng thái)`, [200]);
      const lead = await leadResp.json();
      expect(lead.consultation_status_id).toBe(secondStatusId);
      console.log(
        `Lead status: ${lead.consultation_status_id} (expected: ${secondStatusId})`
      );
    });

    test("7. UI: Lead list shows status + stage badges", async ({
      page,
    }) => {
      officerHeaders = await restoreCookies(page, officerCookies);

      // First: get the expected status name from API (dynamic, not hardcoded)
      const statusResp = await page.request.get(
        `${API_URL}/api/leads/${leadId1}`,
        { headers: officerHeaders }
      );
      await expectOk(statusResp, `GET /api/leads/${leadId1} (tên trạng thái kỳ vọng)`, [200]);
      const lead = await statusResp.json();
      const expectedStatusName = lead.consultation_status?.name;
      const expectedStageName = lead.pipeline_stage?.name;
      expect(expectedStatusName).toBeTruthy();
      console.log(
        `Expected UI: stage="${expectedStageName}", status="${expectedStatusName}"`
      );

      // Navigate to lead list
      await page.goto("/leads");
      await page.waitForLoadState("domcontentloaded");

      // Find lead row by name (phone not shown as column in LeadsTable)
      const leadRow = page.locator("tr").filter({ hasText: leadName1 });
      await expect(leadRow.first()).toBeVisible({ timeout: 15_000 });

      // Verify consultation status badge rendered in lead row
      // LeadsTable.tsx:460-473 renders consultation_status.name via DynamicColorBadge
      await expect(leadRow.first()).toContainText(expectedStatusName);

      // Verify pipeline stage badge if present
      // LeadsTable.tsx:436-454 renders pipeline_stage.name via Badge
      if (expectedStageName) {
        await expect(leadRow.first()).toContainText(expectedStageName);
      }

      console.log(
        `UI: Lead row has status="${expectedStatusName}", stage="${expectedStageName}"`
      );
    });
  });

  // =========================================================================
  // PHASE 2: Admission Profile → Submit → UI Verify
  // =========================================================================

  test.describe("Phase 2: Admission Profile", () => {
    test("8. Officer creates admission profile + fills data + uploads docs", async ({
      page,
    }) => {
      officerHeaders = await restoreCookies(page, officerCookies);

      // Create profile — payload ĐỦ BỐN TRƯỜNG từ nguồn chuẩn.
      const profile = (await createAdmissionProfile(
        page.request,
        leadId1,
        pathContext,
        officerHeaders
      )) as {
        id: number;
        version: number;
        applied_rules?: { allowed_subject_codes?: string[] };
      };
      profileId1 = profile.id;
      profileVersion1 = profile.version;

      // Fill personal info + scores
      const allowedSubjects: string[] =
        profile.applied_rules?.allowed_subject_codes || [];
      const subjectScores: Record<string, number> = {};
      for (const subj of allowedSubjects.slice(0, 3)) {
        subjectScores[subj] = 7 + Math.random() * 3;
      }

      const updateResp = await page.request.put(
        `${API_URL}/api/admissions/${profileId1}`,
        {
          headers: officerHeaders,
          data: {
            version: profileVersion1,
            citizen_id: generateCitizenId(),
            gender: "female",
            dob: "2001-06-20",
            nationality: "Viet Nam",
            ethnicity: "Kinh",
            place_of_birth: "Dak Lak",
            // Bắt buộc tại submit: `priority_service.validate_eligibility`
            // đọc thẳng `profile.cultural_education_level`.
            cultural_education_level: "graduated_thpt",
            vocational_qualification: "none",
            // Khớp fixture danh mục (`seed_e2e_catalog_fixture`): xã 22045 có
            // hàng `administrative_nodes` đương thời + `vn_commune_area_map`.
            permanent_province: FIXTURE_TINH,
            permanent_ward: FIXTURE_XA,
            permanent_commune_code: FIXTURE_MA_XA,
            family_info: [
              {
                relationship: "Cha",
                full_name: "Nguyen Van A",
                phone: "0901234567",
                occupation: "Nong dan",
                is_primary_guardian: true,
              },
            ],
            academic_history: fixtureAcademicHistory(fixtureSchoolId, 2019, 2022),
            admission_scores: { subject_scores: subjectScores, gpa: 8.5 },
          },
        }
      );
      // FAIL-CLOSED: `if (updateResp.ok())` cũ nuốt trọn một 409/422 — hồ sơ
      // ở lại không có CCCD/điểm/hộ khẩu và mọi thứ sau đó đo nhầm chỗ.
      await expectOk(
        updateResp,
        `PUT /api/admissions/${profileId1} (điền thông tin hồ sơ 1)`,
        [200]
      );
      profileVersion1 = (await updateResp.json()).version;

      // Nộp + XÁC MINH tài liệu bắt buộc (một nguồn chuẩn, xem
      // `satisfyMandatoryDocuments`).
      profileVersion1 = await satisfyMandatoryDocuments(
        page,
        profileId1,
        "hồ sơ 1"
      );
      officerHeaders = await restoreCookies(page, officerCookies);

      console.log(`Profile created: id=${profileId1}, version=${profileVersion1}`);
    });

    test("9. Officer submits profile", async ({ page }) => {
      officerHeaders = await restoreCookies(page, officerCookies);

      // Re-fetch current version (doc uploads may have changed it) —
      // FAIL-CLOSED: một GET hỏng ở đây trước kia để lại `profileVersion1`
      // cũ và biến lỗi thành 409 khó đọc ở bước submit.
      const freshResp = await page.request.get(
        `${API_URL}/api/admissions/${profileId1}`,
        { headers: officerHeaders }
      );
      await expectOk(
        freshResp,
        `GET /api/admissions/${profileId1} (lấy version trước submit)`,
        [200]
      );
      profileVersion1 = (await freshResp.json()).version;

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId1}/submit`,
        {
          headers: officerHeaders,
          data: { version: profileVersion1 },
        }
      );
      if (!resp.ok()) {
        const errText = summarizeApiError(resp.status(), await resp.text());
        throw new Error(`Submit failed (${resp.status()}): ${errText}`);
      }
      const body = await resp.json();
      // `submit_and_evaluate` trả **200 + status="draft" + validation_errors**
      // khi validation trượt, nên `resp.ok()` ở trên KHÔNG đủ. In chẩn đoán
      // đã KHỬ PII: `validation_errors` là văn xuôi tiếng Việt có nhúng tên
      // phường/trường ⇒ chỉ lộ độ dài + băm tương quan qua `safeBody`.
      expect(
        body.status,
        `Submit hồ sơ 1 không đạt "submitted" — ${safeBody({
          status: body.status,
          validation_errors: body.validation_errors,
        })}`
      ).toBe("submitted");
      // Don't capture body.version here — submit may not return it reliably.
      // All subsequent transitions use re-fetch pattern before acting.
      console.log(`Profile submitted: status=${body.status}`);
    });

    test(`10. UI: Profile shows "${LABEL.submitted}" in list`, async ({
      page,
    }) => {
      officerHeaders = await restoreCookies(page, officerCookies);
      await page.goto("/admissions");
      await page.waitForLoadState("domcontentloaded");

      await expect(page.locator(TABLE_SELECTOR)).toBeVisible({
        timeout: 15_000,
      });
      const row = page.locator("tr").filter({ hasText: leadName1 });
      await expect(row.first()).toBeVisible({ timeout: 10_000 });
      await expect(row.first()).toContainText(LABEL.submitted);
      console.log(`UI: Profile badge = "${LABEL.submitted}"`);
    });
  });

  // =========================================================================
  // PHASE 3: Manager Review → Approve → UI Verify
  // =========================================================================

  test.describe("Phase 3: Manager Review", () => {
    test("11. Admin approves profile", async ({ page }) => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // Re-fetch current version before approve (version may have changed from doc uploads)
      const freshResp = await page.request.get(
        `${API_URL}/api/admissions/${profileId1}`,
        { headers: adminHeaders }
      );
      await expectOk(
        freshResp,
        `GET /api/admissions/${profileId1} (version trước approve)`,
        [200]
      );
      profileVersion1 = (await freshResp.json()).version;

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId1}/approve`,
        {
          headers: adminHeaders,
          data: { notes: "E2E: Approved", version: profileVersion1 },
        }
      );
      if (!resp.ok()) {
        const errText = summarizeApiError(resp.status(), await resp.text());
        throw new Error(`Approve failed (${resp.status()}): ${errText}`);
      }
      const body = await resp.json();
      profileVersion1 = body.version;
      expect(body.status).toBe("approved");
      console.log(`Profile approved: v=${profileVersion1}`);
    });

    test(`12. UI: Detail page shows "${LABEL.approved}"`, async ({ page }) => {
      adminHeaders = await restoreCookies(page, adminCookies);
      await page.goto(`/admissions/${profileId1}`);
      await page.waitForLoadState("domcontentloaded");

      await expect(
        page.locator(`text=${LABEL.approved}`).first()
      ).toBeVisible({ timeout: 10_000 });
      console.log(`UI: Detail shows "${LABEL.approved}"`);
    });
  });

  // =========================================================================
  // PHASE 4: Override → Enroll → UI Actions Locked
  // =========================================================================

  test.describe("Phase 4: Override + Enroll", () => {
    test("13. Admin overrides (approved → overridden)", async ({ page }) => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // Re-fetch current version — FAIL-CLOSED.
      const fr = await page.request.get(`${API_URL}/api/admissions/${profileId1}`, { headers: adminHeaders });
      await expectOk(fr, `GET /api/admissions/${profileId1} (lấy version)`, [200]);
      profileVersion1 = (await fr.json()).version;

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId1}/override`,
        {
          headers: adminHeaders,
          data: {
            reason: "E2E: Admin override for enrollment",
            version: profileVersion1,
          },
        }
      );
      if (!resp.ok()) throw new Error(`Override failed (${resp.status()}): ${summarizeApiError(resp.status(), await resp.text())}`);
      const body = await resp.json();
      profileVersion1 = body.version;
      expect(body.status).toBe("overridden");
      console.log(`Profile overridden: v=${profileVersion1}`);
    });

    test("14. Admin finalizes enrollment (overridden → enrolled)", async ({
      page,
    }) => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // Re-fetch current version — FAIL-CLOSED.
      const fr = await page.request.get(`${API_URL}/api/admissions/${profileId1}`, { headers: adminHeaders });
      await expectOk(fr, `GET /api/admissions/${profileId1} (lấy version)`, [200]);
      profileVersion1 = (await fr.json()).version;

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId1}/finalize`,
        {
          headers: adminHeaders,
          data: { version: profileVersion1 },
        }
      );
      if (!resp.ok()) throw new Error(`Finalize failed (${resp.status()}): ${summarizeApiError(resp.status(), await resp.text())}`);
      const body = await resp.json();
      profileVersion1 = body.version;
      expect(body.status).toBe("enrolled");
      console.log(`Enrolled: v=${profileVersion1}`);
    });

    test(`15. UI: "${LABEL.enrolled}" visible, manager actions hidden`, async ({
      page,
    }) => {
      adminHeaders = await restoreCookies(page, adminCookies);
      await page.goto(`/admissions/${profileId1}`);
      await page.waitForLoadState("domcontentloaded");

      // Status badge shows enrolled
      await expect(
        page.locator(`text=${LABEL.enrolled}`).first()
      ).toBeVisible({ timeout: 10_000 });

      // ALL manager/reviewer action buttons NOT visible (terminal enrolled state)
      // Full action surface from AdmissionActions.tsx:208-286
      for (const [key, label] of Object.entries(ACTION)) {
        await expect(
          page.locator(`button:has-text("${label}")`)
        ).not.toBeVisible({ timeout: 3_000 });
        console.log(`  ✓ "${label}" (${key}) — not visible`);
      }

      console.log("UI: Enrolled, all 6 action buttons locked");
    });
  });

  // =========================================================================
  // PHASE 5: Rejection → Request Revision → Resubmit → Approve
  // =========================================================================

  test.describe("Phase 5: Rejection + Recovery", () => {
    test("16. Create 2nd lead + profile + submit", async ({ page }) => {
      officerHeaders = await restoreCookies(page, officerCookies);
      leadName2 = `E2E_Reject_${Date.now()}`;

      // Create lead
      const leadResp = await page.request.post(`${API_URL}/api/leads`, {
        headers: officerHeaders,
        data: {
          full_name: leadName2,
          phone: generatePhone(),
          source: "walk_in",
          offering_id: offeringId,
        },
      });
      // FAIL-CLOSED: không có khẳng định nào ở đây thì một 400/429 cho
      // `leadId2 === undefined`, và mọi URL phía sau thành `/api/leads/undefined`.
      await expectOk(leadResp, "POST /api/leads (lead 2)");
      leadId2 = (await leadResp.json()).id;
      expect(leadId2, "POST /api/leads (lead 2) không trả về id").toBeTruthy();

      // Consultation
      const consultResp = await page.request.post(
        `${API_URL}/api/leads/${leadId2}/consultations`,
        {
          headers: officerHeaders,
          data: {
            status_id: initialStatusId,
            method: "phone",
            notes: "E2E rejection flow",
          },
        }
      );
      await expectOk(
        consultResp,
        `POST /api/leads/${leadId2}/consultations (lead 2)`
      );

      // Profile + fill data + docs — payload ĐỦ BỐN TRƯỜNG từ nguồn chuẩn.
      const profile = (await createAdmissionProfile(
        page.request,
        leadId2,
        pathContext,
        officerHeaders
      )) as {
        id: number;
        version: number;
        applied_rules?: { allowed_subject_codes?: string[] };
      };
      profileId2 = profile.id;
      profileVersion2 = profile.version;

      const allowedSubjects: string[] =
        profile.applied_rules?.allowed_subject_codes || [];
      const subjectScores: Record<string, number> = {};
      for (const subj of allowedSubjects.slice(0, 3)) {
        subjectScores[subj] = 6 + Math.random() * 2;
      }

      const updateResp = await page.request.put(
        `${API_URL}/api/admissions/${profileId2}`,
        {
          headers: officerHeaders,
          data: {
            version: profileVersion2,
            citizen_id: generateCitizenId(),
            gender: "male",
            dob: "2002-01-15",
            nationality: "Viet Nam",
            ethnicity: "Kinh",
            place_of_birth: "Dak Lak",
            // Bắt buộc tại submit: `priority_service.validate_eligibility`
            // đọc thẳng `profile.cultural_education_level`.
            cultural_education_level: "graduated_thpt",
            vocational_qualification: "none",
            // Khớp fixture danh mục (`seed_e2e_catalog_fixture`): xã 22045 có
            // hàng `administrative_nodes` đương thời + `vn_commune_area_map`.
            permanent_province: FIXTURE_TINH,
            permanent_ward: FIXTURE_XA,
            permanent_commune_code: FIXTURE_MA_XA,
            family_info: [
              {
                relationship: "Cha",
                full_name: "Tran Van C",
                phone: "0907654321",
                occupation: "Cong nhan",
                is_primary_guardian: true,
              },
            ],
            academic_history: fixtureAcademicHistory(fixtureSchoolId, 2020, 2023),
            admission_scores: { subject_scores: subjectScores, gpa: 7.0 },
          },
        }
      );
      // FAIL-CLOSED — cùng lỗ hổng đã vá ở test 8 (luật "vá một nhánh thì còn bốn").
      await expectOk(
        updateResp,
        `PUT /api/admissions/${profileId2} (điền thông tin hồ sơ 2)`,
        [200]
      );
      profileVersion2 = (await updateResp.json()).version;

      // Nộp + XÁC MINH tài liệu bắt buộc — CÙNG helper với test 8.
      profileVersion2 = await satisfyMandatoryDocuments(
        page,
        profileId2,
        "hồ sơ 2"
      );
      officerHeaders = await restoreCookies(page, officerCookies);

      // Submit
      const submitResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId2}/submit`,
        {
          headers: officerHeaders,
          data: { version: profileVersion2 },
        }
      );
      await expectOk(
        submitResp,
        `POST /api/admissions/${profileId2}/submit (hồ sơ 2)`,
        [200]
      );
      const submitBody = await submitResp.json();
      expect(
        submitBody.status,
        `Submit hồ sơ 2 không đạt "submitted" — ${safeBody({
          status: submitBody.status,
          validation_errors: submitBody.validation_errors,
        })}`
      ).toBe("submitted");
      console.log(`2nd profile submitted: id=${profileId2}, status=${submitBody.status}`);
    });

    test("17. Admin rejects profile", async ({ page }) => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // Re-fetch version — FAIL-CLOSED.
      const fr = await page.request.get(`${API_URL}/api/admissions/${profileId2}`, { headers: adminHeaders });
      await expectOk(fr, `GET /api/admissions/${profileId2} (lấy version)`, [200]);
      profileVersion2 = (await fr.json()).version;

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId2}/reject`,
        {
          headers: adminHeaders,
          data: {
            reason: "E2E: Documents insufficient, needs revision",
            version: profileVersion2,
          },
        }
      );
      if (!resp.ok()) throw new Error(`Reject failed (${resp.status()}): ${summarizeApiError(resp.status(), await resp.text())}`);
      const body = await resp.json();
      profileVersion2 = body.version;
      expect(body.status).toBe("rejected");
      console.log(`Profile rejected: v=${profileVersion2}`);
    });

    test(`18. UI: List shows "${LABEL.rejected}"`, async ({ page }) => {
      adminHeaders = await restoreCookies(page, adminCookies);
      await page.goto("/admissions");
      await page.waitForLoadState("domcontentloaded");

      const row = page.locator("tr").filter({ hasText: leadName2 });
      await expect(row.first()).toBeVisible({ timeout: 10_000 });
      await expect(row.first()).toContainText(LABEL.rejected);
      console.log(`UI: 2nd profile shows "${LABEL.rejected}"`);
    });

    test("19. Resubmit → revision request → resubmit again (3 transitions asserted)", async ({
      page,
    }) => {
      // Step A: Officer resubmits after rejection (rejected → resubmitted)
      officerHeaders = await restoreCookies(page, officerCookies);
      // Re-fetch version
      const frA = await page.request.get(`${API_URL}/api/admissions/${profileId2}`, { headers: officerHeaders });
      await expectOk(frA, `GET /api/admissions/${profileId2} (version trước resubmit)`, [200]);
      profileVersion2 = (await frA.json()).version;
      const resubResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId2}/resubmit`,
        {
          headers: officerHeaders,
          data: {
            notes: "E2E: Fixed documents, resubmitting",
            version: profileVersion2,
          },
        }
      );
      expect(resubResp.ok()).toBeTruthy();
      let body = await resubResp.json();
      profileVersion2 = body.version;
      expect(body.status).toBe("resubmitted");
      console.log(`Step A: rejected → resubmitted (v=${profileVersion2})`);

      // Step B: Admin requests revision (resubmitted → revision_requested)
      adminHeaders = await restoreCookies(page, adminCookies);
      const revResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId2}/request-revision`,
        {
          headers: adminHeaders,
          data: {
            reason: "E2E: Please add missing health certificate",
            version: profileVersion2,
          },
        }
      );
      expect(revResp.ok()).toBeTruthy();
      body = await revResp.json();
      profileVersion2 = body.version;
      expect(body.status).toBe("revision_requested");
      console.log(
        `Step B: resubmitted → revision_requested (v=${profileVersion2})`
      );

      // UI verify: revision_requested shows "Yêu cầu bổ sung" on list
      await page.goto("/admissions");
      await page.waitForLoadState("domcontentloaded");
      const revRow = page.locator("tr").filter({ hasText: leadName2 });
      await expect(revRow.first()).toContainText(LABEL.revision_requested);
      console.log(`UI: "${LABEL.revision_requested}" badge confirmed`);

      // Step C: Officer resubmits again (revision_requested → resubmitted)
      officerHeaders = await restoreCookies(page, officerCookies);
      const resub2Resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId2}/resubmit`,
        {
          headers: officerHeaders,
          data: {
            notes: "E2E: Added health certificate",
            version: profileVersion2,
          },
        }
      );
      expect(resub2Resp.ok()).toBeTruthy();
      body = await resub2Resp.json();
      profileVersion2 = body.version;
      expect(body.status).toBe("resubmitted");
      console.log(
        `Step C: revision_requested → resubmitted (v=${profileVersion2})`
      );

      // UI verify: resubmitted shows "Đã nộp lại" on list
      await page.goto("/admissions");
      await page.waitForLoadState("domcontentloaded");
      const resubRow = page.locator("tr").filter({ hasText: leadName2 });
      await expect(resubRow.first()).toContainText(LABEL.resubmitted);
      console.log(`UI: "${LABEL.resubmitted}" badge confirmed`);
    });

    test(`20. Admin approves recovered profile → UI "${LABEL.approved}"`, async ({
      page,
    }) => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // Re-fetch version before approve
      const frApprove = await page.request.get(`${API_URL}/api/admissions/${profileId2}`, { headers: adminHeaders });
      await expectOk(frApprove, `GET /api/admissions/${profileId2} (version trước approve)`, [200]);
      profileVersion2 = (await frApprove.json()).version;

      // Approve
      const approveResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId2}/approve`,
        {
          headers: adminHeaders,
          data: {
            notes: "E2E: Approved after revision",
            version: profileVersion2,
          },
        }
      );
      expect(approveResp.ok()).toBeTruthy();
      const body = await approveResp.json();
      profileVersion2 = body.version;
      expect(body.status).toBe("approved");
      console.log(`Recovered profile approved: v=${profileVersion2}`);

      // UI verify
      await page.goto(`/admissions/${profileId2}`);
      await page.waitForLoadState("domcontentloaded");
      await expect(
        page.locator(`text=${LABEL.approved}`).first()
      ).toBeVisible({ timeout: 10_000 });
      console.log(`UI: Recovered profile shows "${LABEL.approved}"`);
    });
  });
});
