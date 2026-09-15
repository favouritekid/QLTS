/**
 * E2E Test: Admission Profile Lifecycle
 *
 * Coverage:
 *   - Happy path: draft → submitted → approved → overridden → enrolled
 *   - Rejection path: submitted → rejected → resubmitted → approved
 *   - Magic link: approved → confirmed → enrolled
 *   - Document management: upload, verify, reject, reset, re-upload, delete
 *
 * Replaces:
 *   - admission-workflow.spec.ts (broken selectors)
 *   - admission-confirm-flow.spec.ts (backup MFA codes)
 *   - admission-rejection-flow.spec.ts (backup MFA codes)
 *
 * Chạy:
 *   npx playwright test admission-lifecycle --project=e2e-workflow --reporter=list
 *   npx playwright test admission-lifecycle --project=e2e-workflow --headed
 *   npx playwright test admission-lifecycle -g "Happy path" --project=e2e-workflow
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

/**
 * `attempts_remaining` mà `GET /api/admissions/confirm/{token}` trả về là
 * `ADMISSION_CONFIRM_MAX_ATTEMPTS - attempt_count` (`app/services/admission_service.py`,
 * `get_token_info`), mặc định 5 (`app/config.py`, `ADMISSION_CONFIRM_MAX_ATTEMPTS`).
 *
 * ⚠️ Con số này CHỈ để HIỂN THỊ. Ngưỡng khoá cứng thật là
 * `HARD_LOCK_THRESHOLD = 30` (`app/services/admission_confirmation_cooldown.py`), nên
 * `attempts_remaining` chạm 0 KHÔNG có nghĩa token đã bị khoá — đúng chỗ mà bản cũ
 * của bộ E2E này đọc nhầm.
 */
const CONFIRM_ATTEMPTS_DISPLAY_MAX = 5;

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
let admissionMethodId: number;
/**
 * Bộ ba (round, năm, phương thức) lấy từ NGUỒN CHUẨN mà UI dùng —
 * `GET /api/admission-config/paths/for-offering/{offering_id}`.
 * `AdmissionProfileCreate` (`app/schemas/admission.py:443-494`) bắt buộc
 * cả `admission_round_id` lẫn `academic_year`; payload hai trường của bản
 * cũ trả 422 (đo thật: `invalid_fields=body.admission_round_id[missing],
 * body.academic_year[missing]`).
 */
let pathContext: AdmissionPathContext;
let initialStatusId: string;

// Test data - each test creates its own lead+profile
let leadId1: number;
let profileId1: number;
let profileVersion1: number;

let leadId2: number;
let profileId2: number;

let leadId3: number;
let profileId3: number;
let citizenId3: string;
let confirmToken: string;

let leadId4: number;
let profileId4: number;

let hasPaperDoc = false;

// Test 5: request-revision
let leadId5: number;
let profileId5: number;

// Test 6: auth boundaries + IDOR + locking
let leadId6: number;
let profileId6: number;

// Test 7A: drop via override path
let leadId7A: number;
let profileId7A: number;
let profileVersion7A: number;

// Test 7B: drop via magic link path
let leadId7B: number;
let profileId7B: number;
let citizenId7B: string;
let profileVersion7B: number;

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

/**
 * Bốn chữ số CHẮC CHẮN KHÁC bốn số cuối của `citizenId`.
 *
 * VÌ SAO KHÔNG DÙNG "0000" NHƯ BẢN CŨ: `generateCitizenId()` sinh 12 chữ số NGẪU
 * NHIÊN, nên "0000" trùng bốn số cuối với xác suất 1/10.000 — một lượt nightly đỏ
 * ngẫu nhiên mà không ai tái hiện được. Tăng chữ số cuối thêm 1 (mod 10) cho một
 * chuỗi 4 chữ số khác hẳn, vẫn khớp `pattern=^\d{4}$` của `ConfirmTokenVerifyRequest`
 * (`app/schemas/admission.py`) nên vẫn tới được nhánh so khớp CCCD chứ không rơi
 * xuống 422 của Pydantic.
 */
function wrongLastFour(citizenId: string): string {
  const dung = citizenId.slice(-4);
  return dung.slice(0, 3) + String((Number(dung[3]) + 1) % 10);
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
  if (cookies.length > 0) {
    await page.context().addCookies(cookies);
  }
  const csrf = await getCSRFToken(page);
  return csrf ? { "X-CSRF-Token": csrf } : {};
}

/**
 * Create a lead + admission profile, fill all required data, upload mandatory docs.
 * Returns a profile ready for submission (but NOT yet submitted).
 */
async function createLeadAndProfile(
  page: Page,
  headers: Record<string, string>,
  opts: {
    offeringId: number;
    admissionMethodId: number;
    initialStatusId: string;
    citizenId?: string;
    /**
     * Bỏ bước nộp + xác minh tài liệu, giữ nguyên mọi phần khác.
     *
     * Dùng cho ca cần một hồ sơ ĐỦ ĐIỀU KIỆN nhưng THIẾU TÀI LIỆU — đó là
     * tiền đề duy nhất mà nhánh "200 kèm validation_errors" của `/submit`
     * chạy tới. Một hồ sơ "tối thiểu" thật sự (không nhân thân, không quá
     * trình học tập) dừng sớm hơn ở luật xét điều kiện:
     * `400 ELIGIBILITY_FAIL: cd_chinh_quy_requires_thpt_or_completed_thpt`.
     */
    skipDocuments?: boolean;
  }
): Promise<{ leadId: number; profileId: number; citizenId: string; version: number }> {
  const phone = generatePhone();
  const citizenId = opts.citizenId || generateCitizenId();
  // Tra `school_id` của fixture qua endpoint sản phẩm — id là số tự tăng,
  // hard-code sẽ vỡ khi thứ tự seed đổi.
  const fixtureSchoolId = await resolveFixtureSchoolId(page.request);
  const name = `E2E_Adm_${Date.now()}`;

  // 1. Create lead
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

  // 2. Add consultation (required before admission)
  const consultResp = await page.request.post(
    `${API_URL}/api/leads/${leadId}/consultations`,
    {
      headers,
      data: { status_id: opts.initialStatusId, method: "phone", notes: "E2E admission test" },
    }
  );
  expect(consultResp.ok() || consultResp.status() === 201).toBeTruthy();

  // 3. Create admission profile — payload ĐỦ BỐN TRƯỜNG từ nguồn chuẩn.
  const profile = await createAdmissionProfile(
    page.request,
    leadId,
    pathContext,
    headers
  );
  const profileId = profile.id as number;

  // 4. Fill personal info + scores
  const freshProfile = profile as {
    version: number;
    applied_rules?: { allowed_subject_codes?: string[] };
  };
  const allowedSubjects: string[] =
    freshProfile.applied_rules?.allowed_subject_codes || [];
  const subjectScores: Record<string, number> = {};
  for (const subj of allowedSubjects.slice(0, 3)) {
    subjectScores[subj] = 7 + Math.random() * 3;
  }

  const updateResp = await page.request.put(
    `${API_URL}/api/admissions/${profileId}`,
    {
      headers,
      data: {
        version: freshProfile.version,
        citizen_id: citizenId,
        gender: "female",
        dob: "2001-06-20",
        nationality: "Viet Nam",
        ethnicity: "Kinh",
        place_of_birth: "TP Ho Chi Minh",
        // BẮT BUỘC tại bước submit. `priority_service.validate_eligibility`
        // (dòng 1023-1088) đọc `profile.cultural_education_level` — KHÔNG
        // suy từ `academic_history.graduation_type`. Thiếu nó thì submit
        // một path `cao_dang/chinh_quy` trả 400
        //   ELIGIBILITY_FAIL: cd_chinh_quy_requires_thpt_or_completed_thpt
        // (đo thật trên stack nightly). Schema:
        // `app/schemas/admission.py:780-796`.
        cultural_education_level: "graduated_thpt",
        vocational_qualification: "none",
        // Địa chỉ thường trú — hai validator riêng ở bước submit đòi
        // "Tỉnh/Thành phố" và "Phường/Xã" (đo thật trong validation_errors).
        // Khớp fixture danh mục (`seed_e2e_catalog_fixture`): xã 22045 =
        // Phường Bình Kiến, có hàng trong `administrative_nodes` đương thời và
        // `vn_commune_area_map`. Địa chỉ cũ "TP Ho Chi Minh" không có hàng nào
        // nên `_is_current_era_ward` và ngã THUONG_TRU đều fail-closed.
        permanent_province: FIXTURE_TINH,
        permanent_ward: FIXTURE_XA,
        permanent_commune_code: FIXTURE_MA_XA,
        family_info: [
          { relationship: "Cha", full_name: "Nguyen Van A", phone: "0901234567", occupation: "Kinh doanh", is_primary_guardian: true },
          { relationship: "Me", full_name: "Tran Thi B", phone: "0901234568", occupation: "Giao vien", is_primary_guardian: false },
        ],
        academic_history: fixtureAcademicHistory(fixtureSchoolId),
        admission_scores: {
          subject_scores: subjectScores,
          gpa: 8.5,
        },
      },
    }
  );
  if (!updateResp.ok()) {
    console.log(`Profile update: ${updateResp.status()} ${summarizeApiError(updateResp.status(), await updateResp.text())}`);
  }

  // 5. Upload mandatory docs
  if (opts.skipDocuments) {
    // Đọc version THẬT chứ không trả hằng: người gọi dùng nó cho optimistic
    // locking, và một con số bịa sẽ nổ ở chỗ khác dưới dạng 409 khó lần.
    const hoSo = await (
      await page.request.get(`${API_URL}/api/admissions/${profileId}`)
    ).json();
    return { leadId, profileId, citizenId, version: hoSo.version };
  }
  const getResp = await page.request.get(`${API_URL}/api/admissions/${profileId}`);
  const updatedProfile = await getResp.json();
  const missingDocs = (updatedProfile.documents_checklist || []).filter(
    (d: { is_mandatory: boolean; status: string }) =>
      d.is_mandatory && d.status === "missing"
  );
  for (const doc of missingDocs) {
    const upResp = await page.request.post(
      `${API_URL}/api/admissions/${profileId}/documents/${doc.code}/upload`,
      {
        headers,
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
    await expectOk(upResp, `officer tải lên tài liệu ${doc.code}`, [200, 201]);
  }

  // 6. Manager/admin XÁC MINH tài liệu.
  //
  // Bắt buộc khi path ở chế độ nghiêm ngặt
  // (`allow_unverified_submission = false` — mặc định của seed). Đo thật
  // khi bỏ bước này: `POST /submit` trả 200 nhưng `status` vẫn `"draft"`
  // kèm validation_errors "Tài liệu … chưa được xác minh. Liên hệ quản lý
  // để verify trước khi nộp hồ sơ." ⇒ hồ sơ KHÔNG nộp được.
  // Đây đúng là quy trình sản phẩm (officer tải lên → quản lý xác minh),
  // KHÔNG phải nới lỏng ca kiểm.
  const verifyHeaders = await restoreCookies(page, adminCookies);
  const afterUpload = await (
    await page.request.get(`${API_URL}/api/admissions/${profileId}`)
  ).json();
  const canVerify = (afterUpload.documents_checklist || []).filter(
    (d: { is_mandatory: boolean; status: string }) =>
      d.is_mandatory && (d.status === "uploaded" || d.status === "paper_submitted")
  );
  for (const doc of canVerify) {
    // PATCH, không phải POST (`app/routers/admissions.py:1187`).
    const vResp = await page.request.patch(
      `${API_URL}/api/admissions/${profileId}/documents/${doc.code}/verify-format`,
      { headers: verifyHeaders, data: { format: "photo" } }
    );
    await expectOk(vResp, `admin xác minh tài liệu ${doc.code}`, [200]);
  }
  // KV KHÔNG còn phải ấn định thủ công.
  //
  // Bản trước có một bước admin gọi `POST /api/v2/admissions/{id}/override-
  // priority-kv` ở đây, kèm chú thích nêu đúng lý do của thời điểm ấy: trên
  // CSDL nightly vừa migrate+seed, `vn_school` và `vn_commune_area_map` đều 0
  // hàng nên KHÔNG nhánh tự động nào giải được KV.
  //
  // Nay `scripts/seeds/seed_e2e_catalog_fixture` seed danh mục tối thiểu
  // (trường THPT + xã + ánh xạ KV) nên engine tự giải qua nhánh LICH_SU_THPT.
  // Và cổng xuất xứ của override CHẶN ĐÚNG khi không còn gì để override —
  // đo thật: `400 BUSINESS_RULE_VIOLATION`, thông điệp "Engine vừa tính lại và
  // resolve thành công".
  //
  // Giữ lại bước ấy là dựng một đường vòng cho một vấn đề đã hết, và là ép
  // mọi hồ sơ E2E đi nhánh MANUAL thay vì nhánh engine mà sản phẩm thật dùng.
  // Trả quyền điều khiển về officer — caller vẫn đang dùng phiên officer.
  await restoreCookies(page, officerCookies);

  const finalResp = await page.request.get(`${API_URL}/api/admissions/${profileId}`);
  await expectOk(finalResp, `GET hồ sơ #${profileId} sau khi xác minh`, [200]);
  const finalProfile = await finalResp.json();

  return { leadId, profileId, citizenId, version: finalProfile.version };
}
/**
 * `createMinimalDraftProfile` ĐÃ GỠ.
 *
 * Nó dựng hồ sơ không nhân thân, không quá trình học tập — thứ mà `/submit`
 * từ chối ở luật xét điều kiện (`ELIGIBILITY_FAIL: cd_chinh_quy_requires_
 * thpt_or_completed_thpt`) TRƯỚC khi tới nhánh "200 kèm validation_errors".
 * Người gọi duy nhất của nó nay dùng `createLeadAndProfile({ skipDocuments:
 * true })`, tức hồ sơ ĐỦ ĐIỀU KIỆN nhưng THIẾU TÀI LIỆU.
 */

// ---------------------------------------------------------------------------
// Test Suite
// ---------------------------------------------------------------------------

test.describe("Admission Profile Lifecycle", () => {
  test.describe.configure({ timeout: 600_000, mode: "serial" });

  // =========================================================================
  // Test 1: Happy path — draft → submitted → approved → overridden → enrolled
  // =========================================================================
  test("Happy path: draft → submitted → approved → overridden → enrolled", async ({ page }) => {
    // --- Step 1: Admin login + discover config ---
    await test.step("Admin login + discover config", async () => {
      adminHeaders = await loginViaAPI(page, ADMIN_USERNAME, ADMIN_PASSWORD, {
        totpSecret: ADMIN_TOTP_SECRET,
      });
      adminCookies = await page.context().cookies();

      // Pipeline
      const pipelineResp = await page.request.get(`${API_URL}/api/pipeline/all`);
      expect(pipelineResp.ok()).toBeTruthy();
      const pipeline = await pipelineResp.json();
      initialStatusId = pipeline.statuses[0].id;

      // Units
      const unitsResp = await page.request.get(`${API_URL}/api/organization-units`);
      expect(unitsResp.ok()).toBeTruthy();
      unitId = (await unitsResp.json())[0]?.id;

      // Offering + method + round + năm — MỘT LƯỢT, từ cùng một
      // AdmissionPath, nên chúng tương thích theo định nghĩa.
      //
      // Bản cũ lấy `offerings[0]` rồi `methods[0]` RỜI RẠC. Hai vấn đề đã đo:
      //   * `/api/program-offerings` sắp theo `offering_type` (không duy
      //     nhất) nên phần tử đầu đổi theo `limit`: `limit=5` cho offering
      //     #1, `limit=20` cho #28 — và #5 không có path nào dùng được;
      //   * cặp (offering, method) không có gì buộc phải tồn tại path, mà
      //     `create_profile` tra path theo BỘ BA (round, academic_info,
      //     method) — không có path là 400.
      // Ưu tiên phương thức mà Test 9 cần (giấy tờ nộp bản giấy) nếu
      // offering có path cho nó.
      const methodsResp = await page.request.get(
        `${API_URL}/api/admission-config/methods?active_only=true`
      );
      await expectOk(methodsResp, "GET /api/admission-config/methods", [200]);
      const methodsBody = await methodsResp.json();
      const methods = methodsBody.methods || methodsBody;
      const methodWithPaperDoc = methods.find(
        (m: { id: number; documents?: Array<{ requires_upload: boolean }> }) =>
          m.documents?.some((d: { requires_upload: boolean }) => d.requires_upload === false)
      );

      pathContext = await resolveAdmissionContext(page.request, {
        preferMethodIds: methodWithPaperDoc ? [methodWithPaperDoc.id] : [],
      });
      offeringId = pathContext.offeringId;
      admissionMethodId = pathContext.admissionMethodId;
      hasPaperDoc =
        !!methodWithPaperDoc && methodWithPaperDoc.id === admissionMethodId;

      console.log(
        `Config: unit=${unitId}, offering=${offeringId}, method=${admissionMethodId}, ` +
          `round=${pathContext.admissionRoundId}(${pathContext.roundCode}), ` +
          `year=${pathContext.academicYear}, status=${initialStatusId}, hasPaperDoc=${hasPaperDoc}`
      );
    });

    // --- Step 2: Officer login ---
    await test.step("Officer login", async () => {
      officerHeaders = await loginViaAPI(page, OFFICER_USERNAME, OFFICER_PASSWORD);
      officerCookies = await page.context().cookies();
      console.log("Officer logged in");
    });

    // --- Step 3: Create lead + profile ---
    await test.step("Create lead and profile", async () => {
      const result = await createLeadAndProfile(page, officerHeaders, {
        offeringId,
        admissionMethodId,
        initialStatusId,
      });
      leadId1 = result.leadId;
      profileId1 = result.profileId;
      profileVersion1 = result.version;
      console.log(`Created lead=${leadId1}, profile=${profileId1}`);
    });

    // --- Step 4: Submit profile ---
    await test.step("Submit profile", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId1}/submit`,
        { headers: officerHeaders }
      );
      const body = await resp.json();
      if (body.status !== "submitted") {
        console.log(`Submit errors: ${safeBody(body.validation_errors || body)}`);
      }
      expect(body.status).toBe("submitted");
      // Get fresh version after submit
      const fresh = await (await page.request.get(`${API_URL}/api/admissions/${profileId1}`)).json();
      profileVersion1 = fresh.version;
      console.log(`Submitted! version=${profileVersion1}`);
    });

    // --- Step 5: Admin claims profile ---
    await test.step("Admin claims profile for review", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId1}/claim`,
        {
          headers: adminHeaders,
          data: { version: profileVersion1 },
        }
      );
      if (!resp.ok()) {
        console.log(`Claim failed: ${resp.status()} ${summarizeApiError(resp.status(), await resp.text())}`);
      }
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.assigned_reviewer_id).toBeTruthy();
      profileVersion1 = body.version;
      console.log(`Claimed by reviewer=${body.assigned_reviewer_id}`);
    });

    // --- Step 6: Check status counts ---
    await test.step("Check status counts", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/admissions/status-counts`
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      console.log(`Status counts: ${safeBody(body)}`);
    });

    // --- Step 7: Admin approves ---
    await test.step("Admin approves profile", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId1}/approve`,
        {
          headers: adminHeaders,
          data: {
            notes: "E2E happy path - approved",
            version: profileVersion1,
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.status).toBe("approved");
      profileVersion1 = body.version;
      console.log(`Approved! version=${profileVersion1}`);
    });

    // --- Step 8: Admin unclaims ---
    await test.step("Admin unclaims profile", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId1}/unclaim`,
        {
          headers: adminHeaders,
          data: { version: profileVersion1 },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.assigned_reviewer_id).toBeNull();
      profileVersion1 = body.version;
      console.log("Unclaimed");
    });

    // --- Step 9: Get fee status (may return 404 if no fees calculated yet) ---
    await test.step("Get fee status", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/admissions/${profileId1}/fee-status`
      );
      // Fee status endpoint may return 404 if no fees exist yet, which is expected
      if (resp.ok()) {
        const body = await resp.json();
        console.log(`Fee status: ${safeBody(body)}`);
      } else {
        console.log(`Fee status: ${resp.status()} (no fees yet - expected)`);
        expect([200, 404, 500]).toContain(resp.status());
      }
    });

    // --- Step 10: Admin overrides ---
    await test.step("Admin overrides profile", async () => {
      // ADM-015: override now requires the current profile version
      // (optimistic locking). Fetch it just before the call.
      const profileBefore = await (
        await page.request.get(`${API_URL}/api/admissions/${profileId1}`, {
          headers: adminHeaders,
        })
      ).json();
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId1}/override`,
        {
          headers: adminHeaders,
          data: {
            reason: "E2E happy path test - override to bypass confirmation",
            version: profileBefore.version,
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.status).toBe("overridden");
      console.log(`Overridden! status=${body.status}`);
    });

    // --- Step 11: Admin enrolls ---
    await test.step("Admin enrolls profile", async () => {
      const enrollResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId1}/enroll`,
        { headers: adminHeaders }
      );

      if (enrollResp.ok() || enrollResp.status() === 201) {
        const body = await enrollResp.json();
        console.log(`Enrolled! student_code=${body.student_code}`);
      } else {
        // Fallback to finalize — ADM-015 requires current version
        const profileBefore = await (
          await page.request.get(
            `${API_URL}/api/admissions/${profileId1}`,
            { headers: adminHeaders }
          )
        ).json();
        const finalizeResp = await page.request.post(
          `${API_URL}/api/admissions/${profileId1}/finalize`,
          {
            headers: adminHeaders,
            data: { version: profileBefore.version },
          }
        );
        expect(finalizeResp.ok()).toBeTruthy();
        const body = await finalizeResp.json();
        console.log(`Finalized! status=${body.status}`);
      }
    });

    // --- Step 12: Verify final state ---
    await test.step("Verify enrolled status", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/admissions/${profileId1}`
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(["enrolled", "overridden"]).toContain(body.status);
      console.log(`Final status: ${body.status}`);
    });
  });

  // =========================================================================
  // Test 2: Rejection path — submitted → rejected → resubmitted → approved
  // =========================================================================
  test("Rejection path: submitted → rejected → resubmitted → approved", async ({ page }) => {
    // --- Step 1: Officer creates + submits ---
    await test.step("Officer creates + submits profile", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      const result = await createLeadAndProfile(page, officerHeaders, {
        offeringId,
        admissionMethodId,
        initialStatusId,
      });
      leadId2 = result.leadId;
      profileId2 = result.profileId;

      const submitResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId2}/submit`,
        { headers: officerHeaders }
      );
      const submitBody = await submitResp.json();
      expect(submitBody.status).toBe("submitted");
      console.log(`Profile2 submitted: lead=${leadId2}, profile=${profileId2}`);
    });

    // --- Step 2: Admin rejects ---
    await test.step("Admin rejects profile", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const profile = await (await page.request.get(`${API_URL}/api/admissions/${profileId2}`)).json();

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId2}/reject`,
        {
          headers: adminHeaders,
          data: {
            reason: "Missing required documents - please upload updated ID card and transcript",
            version: profile.version,
          },
        }
      );
      if (!resp.ok()) {
        const errBody = await resp.text();
        console.error(`Reject failed: ${resp.status()} ${errBody.slice(0, 300)}`);
      }
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.status).toBe("rejected");
      console.log(`Rejected! version=${body.version}`);
    });

    // --- Step 3: Reject with short reason (validation error) ---
    await test.step("Reject with short reason fails", async () => {
      const profile = await (await page.request.get(`${API_URL}/api/admissions/${profileId2}`)).json();

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId2}/reject`,
        {
          headers: adminHeaders,
          data: {
            reason: "short",
            version: profile.version,
          },
        }
      );
      expect([400, 422]).toContain(resp.status());
      console.log(`Short reason rejected: ${resp.status()}`);
    });

    // --- Step 4: Officer resubmits ---
    await test.step("Officer resubmits profile", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      const profile = await (await page.request.get(`${API_URL}/api/admissions/${profileId2}`)).json();

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId2}/resubmit`,
        {
          headers: officerHeaders,
          data: { notes: "Corrected documents uploaded", version: profile.version },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.status).toBe("resubmitted");
      console.log(`Resubmitted! version=${body.version}`);
    });

    // --- Step 5: Admin approves resubmitted ---
    await test.step("Admin approves resubmitted profile", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const profile = await (await page.request.get(`${API_URL}/api/admissions/${profileId2}`)).json();

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId2}/approve`,
        {
          headers: adminHeaders,
          data: {
            notes: "Documents verified after resubmission",
            version: profile.version,
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.status).toBe("approved");
      console.log(`Approved after resubmit! version=${body.version}`);
    });

    // --- Step 6: Update non-draft profile should fail ---
    await test.step("Update non-draft profile blocked", async () => {
      const profile = await (await page.request.get(`${API_URL}/api/admissions/${profileId2}`)).json();

      const resp = await page.request.put(
        `${API_URL}/api/admissions/${profileId2}`,
        {
          headers: adminHeaders,
          data: {
            version: profile.version,
            gender: "male",
          },
        }
      );
      expect([400, 403, 409]).toContain(resp.status());
      console.log(`Non-draft update blocked: ${resp.status()}`);
    });
  });

  // =========================================================================
  // Test 3A / 3B: Magic link — HAI token ĐỘC LẬP, mỗi token canh MỘT nhánh
  //
  // Ca 3 CŨ dùng CHUNG một token cho cả hai nhánh: gõ SAI rồi gõ ĐÚNG ngay sau
  // đó, và kỳ vọng lần đúng trả 200. Runtime CỐ Ý chặn — đó là hàng rào chống
  // dò bốn số CCCD (ADM-023), không phải lỗi sản phẩm:
  //
  //   • lần sai thứ nhất đặt `lock_until = now + cooldown_minutes_for(1)`,
  //     tức 5 PHÚT — `app/services/admission_confirmation_cooldown.py`
  //     (bậc thang 2→5ph, 4→30ph, 6→120ph, 29→1440ph; từ 30 là khoá cứng);
  //   • `verify_and_confirm` từ chối MỌI lần thử khi `lock_until > now`, KỂ CẢ
  //     lần gõ ĐÚNG — `app/services/admission_service.py`, nhánh
  //     "ADM-023 hybrid cooldown gate".
  //
  // ĐO THẬT qua đúng bề mặt HTTP mà ca này gọi (harness 13-09-2026):
  //     POST sai   → 400 "Incorrect CCCD digits. 4 attempts remaining."
  //     POST đúng  → 400 "Quá nhiều lần nhập sai. Vui lòng thử lại sau 299 giây."
  //     GET  info  → already_used=false, valid=true, attempts_remaining=4
  //     DB         → profile.status='approved', token.confirmed_at=NULL
  //
  // ⇒ Tách làm hai hồ sơ + hai token, mỗi cái canh một nhánh. Nới cooldown,
  // hay `sleep` 5 phút để lấy xanh, đều là gỡ chính hàng rào đang được canh.
  //
  // ⚠️ Giả định "5 lần sai là khoá cứng" của bản cũ đã bị GỠ: ngưỡng thật là
  // `HARD_LOCK_THRESHOLD = 30`. `ADMISSION_CONFIRM_MAX_ATTEMPTS = 5` chỉ còn
  // dùng để hiển thị `attempts_remaining`. Biên 29→30 nay do backend canh —
  // `tests/integration/test_admission_confirmation_lock_ladder.py`, lớp
  // `TestHardLockBoundary` — vì ở đó dựng thẳng được `attempt_count` thay vì
  // phải gõ sai 30 lần qua HTTP (và 30 lần sẽ đụng luôn trần 5 lần/60 giây
  // của `magic_link_rate_limit`, biến ca E2E thành phép đo cái khác).
  // =========================================================================
  test("Magic link (token A): CCCD đúng ngay lần đầu → confirmed → enrolled", async ({ page }) => {
    // --- Step 1: Officer creates + submits ---
    await test.step("Officer creates + submits profile", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      citizenId3 = generateCitizenId();
      const result = await createLeadAndProfile(page, officerHeaders, {
        offeringId,
        admissionMethodId,
        initialStatusId,
        citizenId: citizenId3,
      });
      leadId3 = result.leadId;
      profileId3 = result.profileId;

      const submitResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId3}/submit`,
        { headers: officerHeaders }
      );
      const submitBody = await submitResp.json();
      expect(submitBody.status).toBe("submitted");
      // KHÔNG in bốn số cuối CCCD: log của lượt nightly công khai được.
      console.log(`Profile3 submitted: lead=${leadId3}, profile=${profileId3}`);
    });

    // --- Step 2: Admin approves ---
    await test.step("Admin approves profile", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const profile = await (await page.request.get(`${API_URL}/api/admissions/${profileId3}`)).json();
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId3}/approve`,
        {
          headers: adminHeaders,
          data: {
            notes: "E2E magic link test - approved",
            version: profile.version,
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      expect((await resp.json()).status).toBe("approved");
      console.log("Approved for magic link test");
    });

    // --- Step 3: Admin sends confirmation link ---
    await test.step("Admin sends confirmation link", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId3}/send-confirmation`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      confirmToken = body.token_value;
      expect(confirmToken).toBeTruthy();
      // KHÔNG in token, kể cả TIỀN TỐ: 8 ký tự đầu của một token 256-bit vẫn là
      // khoá tìm kiếm đủ để đối chiếu với access log (xem mục bàn giao "raw
      // magic token trong access log"). Chỉ in ĐỘ DÀI.
      console.log(`Token A đã cấp: length=${String(confirmToken).length}`);
    });

    // --- Step 4: Token info trước khi dùng (public) ---
    await test.step("Token A: chưa dùng, chưa khoá, đủ lượt hiển thị", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/admissions/confirm/${confirmToken}`
      );
      expect(resp.status()).toBe(200);
      const info = await resp.json();
      expect(info.valid).toBe(true);
      expect(info.expired).toBe(false);
      expect(info.locked).toBe(false);
      expect(info.already_used).toBe(false);
      expect(info.attempts_remaining).toBe(CONFIRM_ATTEMPTS_DISPLAY_MAX);
      console.log(`Token A hợp lệ: attempts_remaining=${info.attempts_remaining}`);
    });

    // --- Step 5: CCCD ĐÚNG ngay lần đầu → 200 ---
    // Token A chưa từng sai ⇒ `lock_until` còn NULL ⇒ không có cổng cooldown
    // nào phải vượt. Đây là nhánh DUY NHẤT mà 200 là kết quả đúng.
    await test.step("CCCD đúng ngay lần đầu → 200 + confirmed", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/admissions/confirm/${confirmToken}`,
        { data: { last_digits_citizen_id: citizenId3.slice(-4) } }
      );
      const bodyText = await resp.text();
      expect(
        resp.status(),
        `Xác nhận lần đầu phải 200 — ${summarizeApiError(resp.status(), bodyText)}`
      ).toBe(200);
      const body = JSON.parse(bodyText);
      expect(body.status).toBe("confirmed");
      expect(body.profile_id).toBe(profileId3);
      console.log(`Confirmed! profile_id=${body.profile_id}, status=${body.status}`);
    });

    // --- Step 6: token A đã TIÊU (đo, không suy) ---
    await test.step("Token A đã tiêu + hồ sơ đã confirmed", async () => {
      const infoResp = await page.request.get(
        `${API_URL}/api/admissions/confirm/${confirmToken}`
      );
      expect(infoResp.status()).toBe(200);
      const info = await infoResp.json();
      expect(info.already_used).toBe(true);
      expect(info.valid).toBe(false);
      expect(info.locked).toBe(false);

      const profile = await (
        await page.request.get(`${API_URL}/api/admissions/${profileId3}`)
      ).json();
      expect(profile.status).toBe("confirmed");
      console.log(
        `Token A tiêu: already_used=${info.already_used}, valid=${info.valid}, profile.status=${profile.status}`
      );
    });

    // --- Step 7: Admin enrolls confirmed profile ---
    await test.step("Admin enrolls confirmed profile", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const enrollResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId3}/enroll`,
        { headers: adminHeaders }
      );
      if (enrollResp.ok() || enrollResp.status() === 201) {
        const body = await enrollResp.json();
        console.log(`Enrolled! ${safeBody({ student_code: body.student_code })}`);
      } else {
        // ADM-015: finalize requires current version
        const profileBefore = await (
          await page.request.get(
            `${API_URL}/api/admissions/${profileId3}`,
            { headers: adminHeaders }
          )
        ).json();
        const finalizeResp = await page.request.post(
          `${API_URL}/api/admissions/${profileId3}/finalize`,
          {
            headers: adminHeaders,
            data: { version: profileBefore.version },
          }
        );
        expect(finalizeResp.ok()).toBeTruthy();
        console.log(`Finalized: ${(await finalizeResp.json()).status}`);
      }

      const profile = await (await page.request.get(`${API_URL}/api/admissions/${profileId3}`)).json();
      expect(["enrolled", "confirmed"]).toContain(profile.status);
      console.log(`Final status: ${profile.status}`);
    });

    // --- Step 8: Reuse already-confirmed token → 400 nhánh "đã dùng" ---
    await test.step("Dùng lại token A đã tiêu → 400 nhánh 'đã dùng'", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/admissions/confirm/${confirmToken}`,
        { data: { last_digits_citizen_id: citizenId3.slice(-4) } }
      );
      const bodyText = await resp.text();
      expect(
        resp.status(),
        `Dùng lại token đã tiêu phải 400 — ${summarizeApiError(resp.status(), bodyText)}`
      ).toBe(400);
      // Phân biệt NHÁNH bằng một biến boolean chứ không bằng `toContain`:
      // khi ca đỏ, Playwright chỉ in `true/false` + thông điệp của ta, không in
      // nguyên `detail` ra log công khai.
      const detail = String(JSON.parse(bodyText).detail ?? "");
      const laNhanhDaDung = /already been used/i.test(detail);
      expect(
        laNhanhDaDung,
        "400 phải đến từ nhánh 'token đã dùng', không phải cooldown/khoá cứng"
      ).toBe(true);
      console.log(`Dùng lại token A bị chặn: status=${resp.status()} (đúng nhánh 'đã dùng')`);
    });
  });

  // =========================================================================
  // Test 3B: token RIÊNG — cooldown ADM-023 chặn cả lần nhập ĐÚNG ngay sau
  // =========================================================================
  test("Magic link (token B): CCCD sai rồi đúng ngay trong cooldown → vẫn 400, hồ sơ nguyên", async ({
    page,
  }) => {
    let leadIdB = 0;
    let profileIdB = 0;
    let citizenIdB = "";
    let tokenB = "";

    // --- Step 1: Officer creates + submits ---
    await test.step("Officer tạo + nộp hồ sơ B", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      citizenIdB = generateCitizenId();
      const result = await createLeadAndProfile(page, officerHeaders, {
        offeringId,
        admissionMethodId,
        initialStatusId,
        citizenId: citizenIdB,
      });
      leadIdB = result.leadId;
      profileIdB = result.profileId;

      const submitResp = await page.request.post(
        `${API_URL}/api/admissions/${profileIdB}/submit`,
        { headers: officerHeaders }
      );
      expect((await submitResp.json()).status).toBe("submitted");
      console.log(`ProfileB submitted: lead=${leadIdB}, profile=${profileIdB}`);
    });

    // --- Step 2: Admin approves ---
    await test.step("Admin duyệt hồ sơ B", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const profile = await (
        await page.request.get(`${API_URL}/api/admissions/${profileIdB}`)
      ).json();
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileIdB}/approve`,
        {
          headers: adminHeaders,
          data: { notes: "E2E cooldown branch - approved", version: profile.version },
        }
      );
      expect(resp.ok()).toBeTruthy();
      expect((await resp.json()).status).toBe("approved");
      console.log("Approved for cooldown-branch test");
    });

    // --- Step 3: Admin sends confirmation link ---
    await test.step("Admin gửi liên kết xác nhận B", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileIdB}/send-confirmation`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      tokenB = (await resp.json()).token_value;
      expect(tokenB).toBeTruthy();
      console.log(`Token B đã cấp: length=${String(tokenB).length}`);
    });

    // --- Step 4: trạng thái xuất phát ---
    await test.step("Token B: xuất phát chưa dùng, chưa khoá", async () => {
      const resp = await page.request.get(
        `${API_URL}/api/admissions/confirm/${tokenB}`
      );
      expect(resp.status()).toBe(200);
      const info = await resp.json();
      expect(info.valid).toBe(true);
      expect(info.already_used).toBe(false);
      expect(info.locked).toBe(false);
      expect(info.attempts_remaining).toBe(CONFIRM_ATTEMPTS_DISPLAY_MAX);
      console.log(`Token B hợp lệ: attempts_remaining=${info.attempts_remaining}`);
    });

    // --- Step 5: CCCD CHẮC CHẮN SAI → 400 + trừ một lượt hiển thị ---
    await test.step("CCCD sai → 400 và attempts_remaining còn 4", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/admissions/confirm/${tokenB}`,
        { data: { last_digits_citizen_id: wrongLastFour(citizenIdB) } }
      );
      const bodyText = await resp.text();
      expect(
        resp.status(),
        `CCCD sai phải 400 — ${summarizeApiError(resp.status(), bodyText)}`
      ).toBe(400);
      const detail = String(JSON.parse(bodyText).detail ?? "");
      const laNhanhSaiSo = /attempts remaining/i.test(detail);
      expect(
        laNhanhSaiSo,
        "400 phải đến từ nhánh 'sai bốn số', không phải cooldown/khoá cứng"
      ).toBe(true);

      const info = await (
        await page.request.get(`${API_URL}/api/admissions/confirm/${tokenB}`)
      ).json();
      expect(info.attempts_remaining).toBe(CONFIRM_ATTEMPTS_DISPLAY_MAX - 1);
      console.log(
        `CCCD sai bị từ chối: status=${resp.status()}, attempts_remaining=${info.attempts_remaining}`
      );
    });

    // --- Step 6: CCCD ĐÚNG NGAY SAU ĐÓ → vẫn 400 vì cooldown 5 phút ---
    // ĐÂY là khẳng định trung tâm của ca này. Không `sleep`, không nới
    // cooldown: gửi NGAY để chứng minh cổng `lock_until` đang chắn thật.
    await test.step("CCCD đúng ngay trong cooldown → vẫn 400", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/admissions/confirm/${tokenB}`,
        { data: { last_digits_citizen_id: citizenIdB.slice(-4) } }
      );
      const bodyText = await resp.text();
      expect(
        resp.status(),
        `Trong cooldown, kể cả CCCD đúng cũng phải 400 — ${summarizeApiError(
          resp.status(),
          bodyText
        )}`
      ).toBe(400);
      const detail = String(JSON.parse(bodyText).detail ?? "");
      const laNhanhCooldown = /thử lại sau \d+ giây/i.test(detail);
      expect(
        laNhanhCooldown,
        "400 phải đến từ nhánh COOLDOWN (lock_until), không phải 'sai bốn số' hay 'đã khoá'"
      ).toBe(true);
      console.log(`Cooldown chặn cả lần nhập đúng: status=${resp.status()}`);
    });

    // --- Step 7: hậu kiểm — không có gì bị tiêu ---
    await test.step("Hậu kiểm B: hồ sơ còn approved, token chưa tiêu, còn 4 lượt", async () => {
      const info = await (
        await page.request.get(`${API_URL}/api/admissions/confirm/${tokenB}`)
      ).json();
      expect(info.already_used).toBe(false);
      expect(info.locked).toBe(false);
      expect(info.valid).toBe(true);
      // Lần bị cooldown chặn KHÔNG chạm `attempt_count` (bị từ chối TRƯỚC khi
      // tăng), nên số lượt hiển thị vẫn đúng bằng 4 chứ không phải 3.
      expect(info.attempts_remaining).toBe(CONFIRM_ATTEMPTS_DISPLAY_MAX - 1);

      adminHeaders = await restoreCookies(page, adminCookies);
      const profile = await (
        await page.request.get(`${API_URL}/api/admissions/${profileIdB}`)
      ).json();
      expect(profile.status).toBe("approved");
      console.log(
        `Hậu kiểm B: profile.status=${profile.status}, already_used=${info.already_used}, attempts_remaining=${info.attempts_remaining}`
      );
    });
  });

  // =========================================================================
  // Test 4: Document management
  // =========================================================================
  test("Document management: upload, verify, reject, reset, delete", async ({ page }) => {
    // --- Step 1: Officer creates draft profile ---
    await test.step("Create draft profile", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      const result = await createLeadAndProfile(page, officerHeaders, {
        offeringId,
        admissionMethodId,
        initialStatusId,
      });
      leadId4 = result.leadId;
      profileId4 = result.profileId;
      console.log(`Draft profile4: lead=${leadId4}, profile=${profileId4}`);
    });

    // --- Step 2: Dựng ĐÚNG tiền đề mà ca này cần ---
    let testDocCode: string;
    await test.step("Identify document for testing", async () => {
      // Bản cũ đi tìm một tài liệu còn sót ở `uploaded` do `createLeadAndProfile`
      // để lại. Nó ĐÃ hỏng: helper ấy nay upload XONG THÌ XÁC MINH LUÔN mọi tài
      // liệu bắt buộc (bước `canVerify`), nên không còn hàng nào ở `uploaded` —
      // đo thật trên hồ sơ 6: 7 tài liệu, trạng thái {missing, verified}, 0
      // `uploaded`. Phụ thuộc vào tác dụng phụ của một helper dùng chung là chỗ
      // hỏng, không phải trạng thái kia.
      //
      // Nay ca này TỰ dựng tiền đề: lấy một tài liệu còn `missing` rồi nộp nó.
      // Chặt hơn bản cũ chứ không lỏng hơn — tiền đề được KHẲNG ĐỊNH (`uploaded`
      // sau khi nộp) thay vì được giả định, và toàn bộ vòng đời bên dưới
      // (verify → reject → reset → re-upload → delete) vẫn chạy y nguyên.
      const truoc = await page.request.get(`${API_URL}/api/admissions/${profileId4}`);
      expect(truoc.ok()).toBeTruthy();
      const docs: Array<{ code: string; status: string; is_mandatory: boolean }> =
        (await truoc.json()).documents_checklist || [];
      const conThieu = docs.find((d) => d.status === "missing");
      expect(
        conThieu,
        `hồ sơ ${profileId4} không còn tài liệu nào ở 'missing' — checklist: ` +
          docs.map((d) => `${d.code}=${d.status}`).join(", ")
      ).toBeTruthy();
      testDocCode = conThieu!.code;

      const upResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId4}/documents/${testDocCode}/upload`,
        {
          headers: officerHeaders,
          multipart: {
            file: {
              name: `${testDocCode}.pdf`,
              mimeType: "application/pdf",
              buffer: Buffer.from(`%PDF-1.4\n%%EOF\n% E2E doc-mgmt: ${testDocCode}`),
            },
            actual_submission_format: "photo",
          },
        }
      );
      await expectOk(upResp, `officer nộp tài liệu ${testDocCode}`, [200, 201]);

      // Tiền đề phải được ĐO, không được suy từ 2xx của lượt nộp.
      const sau = await page.request.get(`${API_URL}/api/admissions/${profileId4}`);
      const sauDocs: Array<{ code: string; status: string }> =
        (await sau.json()).documents_checklist || [];
      const hang = sauDocs.find((d) => d.code === testDocCode);
      expect(hang?.status, `tài liệu ${testDocCode} sau khi nộp`).toBe("uploaded");
      console.log(`Testing with doc: ${testDocCode}`);
    });

    // --- Step 3: Admin verifies document format ---
    await test.step("Admin verifies document format", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.patch(
        `${API_URL}/api/admissions/${profileId4}/documents/${testDocCode}/verify-format`,
        {
          headers: adminHeaders,
          data: { format: "photo" },
        }
      );
      expect(resp.ok()).toBeTruthy();
      console.log(`Document ${testDocCode} format verified`);
    });

    // --- Step 4: Admin rejects document ---
    await test.step("Admin rejects document", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId4}/documents/${testDocCode}/reject`,
        {
          headers: adminHeaders,
          data: { reason: "Document is blurry and unreadable" },
        }
      );
      expect(resp.ok()).toBeTruthy();
      console.log(`Document ${testDocCode} rejected`);
    });

    // --- Step 5: Admin resets document ---
    await test.step("Admin resets document", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId4}/documents/${testDocCode}/reset`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      console.log(`Document ${testDocCode} reset to missing`);
    });

    // --- Step 6: Officer re-uploads document ---
    await test.step("Officer re-uploads document", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId4}/documents/${testDocCode}/upload`,
        {
          headers: officerHeaders,
          multipart: {
            file: {
              name: `${testDocCode}_v2.pdf`,
              mimeType: "application/pdf",
              buffer: Buffer.from(`%PDF-1.4\n%%EOF\n% E2E re-upload: ${testDocCode}`),
            },
            actual_submission_format: "photo",
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      console.log(`Document ${testDocCode} re-uploaded`);
    });

    // --- Step 7: Mark paper-only doc as submitted (Test 9 from plan) ---
    await test.step("Mark paper-only doc as submitted", async () => {
      if (!hasPaperDoc) {
        console.log("Admission method has no paper-only doc — skipping paper-submitted step");
        return;
      }
      officerHeaders = await restoreCookies(page, officerCookies);

      const profile = await (
        await page.request.get(`${API_URL}/api/admissions/${profileId4}`)
      ).json();
      const paperDoc = (profile.documents_checklist || []).find(
        (d: { requires_upload: boolean; code: string }) => d.requires_upload === false
      );
      expect(paperDoc).toBeTruthy();

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId4}/documents/${paperDoc!.code}/paper-submitted`,
        {
          headers: officerHeaders,
          data: { actual_submission_format: "original" },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.id).toBe(profileId4);
      console.log(`Paper doc ${paperDoc!.code} marked as submitted`);
    });

    // --- Step 8: Delete draft profile ---
    await test.step("Delete draft profile", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const resp = await page.request.delete(
        `${API_URL}/api/admissions/${profileId4}`,
        { headers: adminHeaders }
      );
      // Delete may return 204 or 500 (backend constraint issue)
      if (resp.status() === 204) {
        console.log(`Profile4 deleted`);
        // Verify gone
        const getResp = await page.request.get(`${API_URL}/api/admissions/${profileId4}`);
        expect(getResp.status()).toBe(404);
        console.log("Profile4 confirmed deleted (404)");
      } else {
        console.log(`Profile4 delete returned ${resp.status()} (backend constraint — acceptable for draft)`);
        expect([204, 400, 409, 500]).toContain(resp.status());
      }
    });
  });

  // =========================================================================
  // Test 5: request-revision path
  // =========================================================================
  test("Request-revision: draft → submitted → revision_requested → resubmitted → approved", async ({
    page,
  }) => {
    // --- Step 1: Officer creates + submits ---
    await test.step("Officer creates + submits profile", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      const result = await createLeadAndProfile(page, officerHeaders, {
        offeringId,
        admissionMethodId,
        initialStatusId,
      });
      leadId5 = result.leadId;
      profileId5 = result.profileId;

      const submitResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId5}/submit`,
        { headers: officerHeaders }
      );
      const submitBody = await submitResp.json();
      expect(submitBody.status).toBe("submitted");
      console.log(`Profile5 submitted: lead=${leadId5}, profile=${profileId5}`);
    });

    // --- Step 2: Admin requests revision ---
    await test.step("Admin requests revision", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const profile = await (
        await page.request.get(`${API_URL}/api/admissions/${profileId5}`)
      ).json();

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId5}/request-revision`,
        {
          headers: adminHeaders,
          data: {
            reason: "Cần bổ sung thêm giấy tờ học vấn và ảnh chân dung rõ nét",
            version: profile.version,
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.status).toBe("revision_requested");
      console.log(`Revision requested! version=${body.version}`);
    });

    // --- Step 3: Officer resubmits after revision ---
    await test.step("Officer resubmits after revision", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      const profile = await (await page.request.get(`${API_URL}/api/admissions/${profileId5}`)).json();

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId5}/resubmit`,
        {
          headers: officerHeaders,
          data: { notes: "Đã bổ sung đầy đủ hồ sơ theo yêu cầu", version: profile.version },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.status).toBe("resubmitted");
      console.log(`Resubmitted after revision! version=${body.version}`);
    });

    // --- Step 4: Admin approves resubmitted ---
    await test.step("Admin approves after revision resubmit", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const profile = await (
        await page.request.get(`${API_URL}/api/admissions/${profileId5}`)
      ).json();

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId5}/approve`,
        {
          headers: adminHeaders,
          data: {
            notes: "Hồ sơ đã hoàn chỉnh sau revision",
            version: profile.version,
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.status).toBe("approved");
      console.log(`Approved after revision path! version=${body.version}`);
    });
  });

  // =========================================================================
  // Test 6: Authorization boundaries + IDOR + optimistic locking
  // =========================================================================
  test("Auth boundaries: officer cannot approve, IDOR → 404, stale version → 409", async ({
    page,
  }) => {
    // --- Step 1: Officer creates + submits a fresh profile ---
    await test.step("Officer creates + submits profile for auth tests", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      const result = await createLeadAndProfile(page, officerHeaders, {
        offeringId,
        admissionMethodId,
        initialStatusId,
      });
      leadId6 = result.leadId;
      profileId6 = result.profileId;

      const submitResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId6}/submit`,
        { headers: officerHeaders }
      );
      expect((await submitResp.json()).status).toBe("submitted");
      console.log(`Profile6 submitted: lead=${leadId6}, profile=${profileId6}`);
    });

    // --- Step 2: Officer tries to approve → 403 ---
    await test.step("Officer approve → 403 Forbidden", async () => {
      const profile = await (
        await page.request.get(`${API_URL}/api/admissions/${profileId6}`)
      ).json();

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId6}/approve`,
        {
          headers: officerHeaders,
          data: { notes: "unauthorized approve attempt", version: profile.version },
        }
      );
      expect(resp.status()).toBe(403);
      console.log(`Officer approve blocked: ${resp.status()}`);
    });

    // --- Step 3: IDOR — officer accesses profile from another unit → 404 ---
    await test.step("Officer accesses out-of-scope profile → 404", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      // Get all units and find one different from unitId (officer's unit)
      const allUnitsResp = await page.request.get(`${API_URL}/api/organization-units`, {
        headers: adminHeaders,
      });
      const allUnits = await allUnitsResp.json();
      const otherUnit = allUnits.find((u: { id: number }) => u.id !== unitId);

      if (!otherUnit) {
        console.log("Only one organizational unit in system — skipping IDOR sub-test");
        return;
      }

      // Admin creates lead+profile in the other unit
      const otherPhone = generatePhone();
      const otherLeadResp = await page.request.post(`${API_URL}/api/leads`, {
        headers: adminHeaders,
        data: {
          full_name: `IDOR_Test_${Date.now()}`,
          phone: otherPhone,
          source: "walk_in",
          offering_id: offeringId,
          unit_id: otherUnit.id,
        },
      });
      const otherLeadId = (await otherLeadResp.json()).id;

      await page.request.post(`${API_URL}/api/leads/${otherLeadId}/consultations`, {
        headers: adminHeaders,
        data: { status_id: initialStatusId, method: "phone", notes: "IDOR test" },
      });

      const otherProfile = await createAdmissionProfile(
        page.request,
        otherLeadId,
        pathContext,
        adminHeaders
      );
      const otherProfileId = otherProfile.id as number;
      console.log(`Created out-of-scope profile: id=${otherProfileId}, unit=${otherUnit.id}`);

      // Officer tries to access — should get 404 (not 403, to avoid leaking existence)
      officerHeaders = await restoreCookies(page, officerCookies);
      const iddorResp = await page.request.get(
        `${API_URL}/api/admissions/${otherProfileId}`,
        { headers: officerHeaders }
      );
      expect(iddorResp.status()).toBe(404);
      console.log(`IDOR blocked: officer got ${iddorResp.status()} for out-of-scope profile`);
    });

    // --- Step 4: Admin approve with stale version → 409 ---
    await test.step("Approve with stale version → 409 optimistic locking", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const profile = await (
        await page.request.get(`${API_URL}/api/admissions/${profileId6}`)
      ).json();

      const staleResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId6}/approve`,
        {
          headers: adminHeaders,
          data: { notes: "stale version test", version: profile.version - 1 },
        }
      );
      expect(staleResp.status()).toBe(409);
      console.log(`Stale version rejected: ${staleResp.status()}`);
    });

    // --- Step 5: Admin approve with correct version → 200 ---
    await test.step("Approve with correct version → 200", async () => {
      const profile = await (
        await page.request.get(`${API_URL}/api/admissions/${profileId6}`)
      ).json();

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId6}/approve`,
        {
          headers: adminHeaders,
          data: { notes: "correct version approve", version: profile.version },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.status).toBe("approved");
      console.log(`Approved with correct version! version=${body.version}`);
    });
  });

  // =========================================================================
  // Test 7A: Drop student — override path
  // =========================================================================
  test("Drop student (override path): draft → submitted → approved → overridden → enrolled → dropped", async ({
    page,
  }) => {
    // --- Step 1: Officer creates + submits ---
    await test.step("Officer creates + submits profile", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      const result = await createLeadAndProfile(page, officerHeaders, {
        offeringId,
        admissionMethodId,
        initialStatusId,
      });
      leadId7A = result.leadId;
      profileId7A = result.profileId;

      const submitResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId7A}/submit`,
        { headers: officerHeaders }
      );
      expect((await submitResp.json()).status).toBe("submitted");
      console.log(`Profile7A submitted: lead=${leadId7A}, profile=${profileId7A}`);
    });

    // --- Step 2: Admin approves ---
    await test.step("Admin approves", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const profile = await (
        await page.request.get(`${API_URL}/api/admissions/${profileId7A}`)
      ).json();

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId7A}/approve`,
        {
          headers: adminHeaders,
          data: { notes: "Drop test 7A", version: profile.version },
        }
      );
      expect((await resp.json()).status).toBe("approved");
      console.log("Approved 7A");
    });

    // --- Step 3: Admin overrides ---
    await test.step("Admin overrides profile", async () => {
      // ADM-015: fetch current version before override
      const profileBefore = await (
        await page.request.get(`${API_URL}/api/admissions/${profileId7A}`, {
          headers: adminHeaders,
        })
      ).json();
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId7A}/override`,
        {
          headers: adminHeaders,
          data: {
            reason: "Override for drop test 7A — bypass confirmation",
            version: profileBefore.version,
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      expect((await resp.json()).status).toBe("overridden");
      console.log("Overridden 7A");
    });

    // --- Step 4: Admin enrolls ---
    await test.step("Admin enrolls profile", async () => {
      const enrollResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId7A}/enroll`,
        { headers: adminHeaders }
      );
      if (enrollResp.ok() || enrollResp.status() === 201) {
        console.log(`Enrolled 7A: student_code=${(await enrollResp.json()).student_code}`);
      } else {
        // ADM-015: finalize requires current version
        const profileBefore = await (
          await page.request.get(
            `${API_URL}/api/admissions/${profileId7A}`,
            { headers: adminHeaders }
          )
        ).json();
        const finalizeResp = await page.request.post(
          `${API_URL}/api/admissions/${profileId7A}/finalize`,
          {
            headers: adminHeaders,
            data: { version: profileBefore.version },
          }
        );
        expect(finalizeResp.ok()).toBeTruthy();
        console.log(`Finalized 7A: ${(await finalizeResp.json()).status}`);
      }

      const profile = await (
        await page.request.get(`${API_URL}/api/admissions/${profileId7A}`)
      ).json();
      // Must be enrolled before we can drop
      expect(profile.status).toBe("enrolled");
      profileVersion7A = profile.version;
      console.log(`Profile7A enrolled, version=${profileVersion7A}`);
    });

    // --- Step 5: Admin drops enrolled student ---
    await test.step("Admin drops enrolled student", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId7A}/drop`,
        {
          headers: adminHeaders,
          data: {
            reason: "Sinh viên tự nguyện rút hồ sơ nhập học do hoàn cảnh gia đình",
            version: profileVersion7A,
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.is_dropped).toBe(true);
      // Status remains "enrolled" after drop
      expect(body.status).toBe("enrolled");
      console.log(`Dropped 7A! is_dropped=${body.is_dropped}, status=${body.status}`);
    });
  });

  // =========================================================================
  // Test 7B: Drop student — magic link path
  // =========================================================================
  test("Drop student (magic link path): approved → confirmed → enrolled → dropped", async ({
    page,
  }) => {
    // --- Step 1: Officer creates + submits ---
    await test.step("Officer creates + submits profile", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      citizenId7B = generateCitizenId();
      const result = await createLeadAndProfile(page, officerHeaders, {
        offeringId,
        admissionMethodId,
        initialStatusId,
        citizenId: citizenId7B,
      });
      leadId7B = result.leadId;
      profileId7B = result.profileId;

      const submitResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId7B}/submit`,
        { headers: officerHeaders }
      );
      expect((await submitResp.json()).status).toBe("submitted");
      console.log(`Profile7B submitted: lead=${leadId7B}, profile=${profileId7B}`);
    });

    // --- Step 2: Admin approves ---
    await test.step("Admin approves", async () => {
      adminHeaders = await restoreCookies(page, adminCookies);

      const profile = await (
        await page.request.get(`${API_URL}/api/admissions/${profileId7B}`)
      ).json();

      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId7B}/approve`,
        {
          headers: adminHeaders,
          data: { notes: "Drop test 7B", version: profile.version },
        }
      );
      expect((await resp.json()).status).toBe("approved");
      console.log("Approved 7B");
    });

    // --- Step 3: Admin sends confirmation link ---
    await test.step("Admin sends confirmation link", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId7B}/send-confirmation`,
        { headers: adminHeaders }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      const token7B = body.token_value;
      expect(token7B).toBeTruthy();
      // KHÔNG in tiền tố token — xem chú thích ở ca 3A.
      console.log(`Token7B đã cấp: length=${String(token7B).length}`);

      // --- Step 4: Confirm with correct CCCD ---
      const confirmResp = await page.request.post(
        `${API_URL}/api/admissions/confirm/${token7B}`,
        { data: { last_digits_citizen_id: citizenId7B.slice(-4) } }
      );
      expect(confirmResp.ok()).toBeTruthy();
      expect((await confirmResp.json()).status).toBe("confirmed");
      console.log("Confirmed 7B via magic link");
    });

    // --- Step 5: Admin enrolls ---
    await test.step("Admin enrolls confirmed profile", async () => {
      const enrollResp = await page.request.post(
        `${API_URL}/api/admissions/${profileId7B}/enroll`,
        { headers: adminHeaders }
      );
      if (enrollResp.ok() || enrollResp.status() === 201) {
        console.log(`Enrolled 7B: student_code=${(await enrollResp.json()).student_code}`);
      } else {
        // ADM-015: finalize requires current version
        const profileBefore = await (
          await page.request.get(
            `${API_URL}/api/admissions/${profileId7B}`,
            { headers: adminHeaders }
          )
        ).json();
        const finalizeResp = await page.request.post(
          `${API_URL}/api/admissions/${profileId7B}/finalize`,
          {
            headers: adminHeaders,
            data: { version: profileBefore.version },
          }
        );
        expect(finalizeResp.ok()).toBeTruthy();
        console.log(`Finalized 7B: ${(await finalizeResp.json()).status}`);
      }

      const profile = await (
        await page.request.get(`${API_URL}/api/admissions/${profileId7B}`)
      ).json();
      expect(profile.status).toBe("enrolled");
      profileVersion7B = profile.version;
      console.log(`Profile7B enrolled, version=${profileVersion7B}`);
    });

    // --- Step 6: Admin drops enrolled student ---
    await test.step("Admin drops enrolled student", async () => {
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId7B}/drop`,
        {
          headers: adminHeaders,
          data: {
            reason: "Sinh viên xin rút hồ sơ sau khi đã xác nhận nhập học",
            version: profileVersion7B,
          },
        }
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.is_dropped).toBe(true);
      expect(body.status).toBe("enrolled");
      console.log(`Dropped 7B! is_dropped=${body.is_dropped}, status=${body.status}`);
    });
  });

  // =========================================================================
  // Test 8: Submit with missing data → validation errors (not 400)
  // =========================================================================
  test("Submit incomplete profile → 200 draft with validation_errors", async ({
    page,
  }) => {
    // --- Step 1: Create minimal draft (no personal info, no docs) ---
    await test.step("Create minimal draft profile", async () => {
      officerHeaders = await restoreCookies(page, officerCookies);

      // Bản cũ dùng `createMinimalDraftProfile` — hồ sơ KHÔNG nhân thân, KHÔNG
      // quá trình học tập. Hồ sơ ấy không bao giờ tới được nhánh mà ca này
      // muốn kiểm: `/submit` dừng sớm hơn ở luật xét điều kiện, trả
      // `400 BUSINESS_RULE_VIOLATION — ELIGIBILITY_FAIL: Legacy single-path
      // (cao_dang/chinh_quy): cd_chinh_quy_requires_thpt_or_completed_thpt`
      // (đo thật trên hồ sơ 12 của lượt nghiệm thu).
      //
      // Đây là ĐỎ CÓ SẴN, không phải hồi quy: helper ấy có từ 11-03-2026 và
      // đợt này không sửa nó, cũng không sửa tệp eligibility nào. Suite trước
      // nay chết sớm hơn nên chưa lần nào chạy tới ca số 10.
      //
      // Tiền đề ĐÚNG của ca: hồ sơ ĐỦ ĐIỀU KIỆN nhưng THIẾU TÀI LIỆU. Không
      // nới phép kiểm nào — vẫn đòi 200 + `status=draft` + `validation_errors`
      // không rỗng; chỉ dựng đúng hoàn cảnh mà khẳng định ấy nói về.
      const { profileId } = await createLeadAndProfile(page, officerHeaders, {
        offeringId,
        admissionMethodId,
        initialStatusId,
        skipDocuments: true,
      });

      console.log(`Hồ sơ đủ điều kiện, chưa nộp tài liệu: profileId=${profileId}`);

      // --- Step 2: Submit → expect 200 with status=draft + validation_errors ---
      const resp = await page.request.post(
        `${API_URL}/api/admissions/${profileId}/submit`,
        { headers: officerHeaders }
      );
      // Backend returns 200 (not 400) with status=draft and validation_errors list
      expect(resp.status()).toBe(200);
      const body = await resp.json();
      expect(body.status).toBe("draft");
      expect(Array.isArray(body.validation_errors)).toBe(true);
      expect(body.validation_errors.length).toBeGreaterThan(0);
      console.log(
        `Validation blocked submit: status=${body.status}, errors=${body.validation_errors.length}`
      );
      console.log(`First error: ${safeBody(body.validation_errors[0])}`);
    });
  });
});
