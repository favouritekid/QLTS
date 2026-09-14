/**
 * E2E Test: Admission UI Smoke
 *
 * Coverage:
 *   - List page renders the profile this suite created (KHÔNG chấp nhận empty state)
 *   - List page renders a usable empty state khi lọc sang một năm chắc chắn rỗng
 *   - Detail page: mọi bước điều hướng được đều mở mà không crash
 *   - Unsaved-changes dialog khi đổi bước sau khi sửa
 *
 * Project: chromium only (officer storageState từ project `setup`)
 * Data: seed lead + consultation + profile qua API trong `beforeAll`
 *
 * ⚠️ HỢP ĐỒNG CỦA TỆP NÀY — ba luật ra đời từ nightly run 34678745325:
 *
 *  1. `beforeAll` FAIL-CLOSED. Bản cũ gọi bốn endpoint mà KHÔNG kiểm một
 *     response nào, nên `POST /api/admissions` trả 422 (thiếu
 *     `admission_round_id` + `academic_year` — hardening có chủ đích ở
 *     `app/schemas/admission.py:443`) mà hook vẫn "thành công" và in
 *     `UI smoke profile created: id=undefined`. Mọi request setup nay đi qua
 *     `apiJson()`; hỏng là NÉM NGAY kèm status + error_code + tên trường
 *     thiếu (KHÔNG in body thô — body 422 echo lại `input` của người dùng).
 *
 *  2. `storageState` truyền TƯỜNG MINH cho `browser.newContext()`.
 *     ĐO THẬT (Playwright 1.56, `node_modules/playwright/lib/index.js:277`):
 *     hook `runBeforeCreateBrowserContext` BƠM NGƯỢC `_combinedContextOptions`
 *     — `storageState` trong đó — vào mọi `browser.newContext(options)` chưa
 *     khai khoá ấy. Nghĩa là bản cũ VẪN có phiên officer; giả thuyết "context
 *     trắng" là SAI (kiểm ngược M0: gỡ đối số vẫn cho `user_id=10 role=officer`).
 *     Nhưng đó là hành vi NGẦM của một hook nội bộ, đúng-nhờ-may: nó không
 *     xuất hiện trong chữ ký `browser.newContext()`, và `beforeAll` là hook
 *     phạm vi worker nên không có gì trong hợp đồng công khai bảo đảm nó chạy.
 *     Khai tường minh để phiên mà setup dùng là thứ ĐỌC ĐƯỢC từ mã nguồn.
 *
 *  3. Ca "List page" phải chứng minh ĐÚNG hồ sơ vừa tạo hiện ra. Bản cũ chỉ
 *     đòi `h1` + `table` nên một DB rỗng (hệ quả của luật 1) làm nó đỏ ở đúng
 *     chỗ vô nghĩa nhất. Nới assertion để nhận empty state là che setup fail —
 *     CẤM. Ca empty-state tách riêng, lọc sang một năm không thể có hồ sơ.
 *
 * Chạy:
 *   npx playwright test admission-ui-smoke --project=chromium --reporter=list
 */

import {
  test,
  expect,
  type APIRequestContext,
  type APIResponse,
  type Page,
} from "@playwright/test";
import path from "path";
import {
  API_URL,
  resolveAdmissionContext,
  summarizeApiError,
} from "./helpers/e2e-fixtures";


/**
 * storageState do project `chromium` khai trong `playwright.config.ts`
 * (`use.storageState = src/test/.auth/user.json`, sinh bởi `auth.setup.ts`).
 * Đường dẫn phải khớp `auth.setup.ts:14` — xem luật 2 ở đầu tệp về việc vì sao
 * truyền tường minh thay vì dựa vào hook bơm ngược của Playwright.
 */
const AUTH_STATE_FILE = path.join(__dirname, "..", ".auth", "user.json");

// ---------------------------------------------------------------------------
// Shared state
// ---------------------------------------------------------------------------

interface SmokeSeed {
  leadId: number;
  leadName: string;
  profileId: number;
  academicYear: number;
  admissionRoundId: number;
  admissionMethodId: number;
  offeringId: number;
}

let seed: SmokeSeed;

/** Mọi hồ sơ suite này tạo ra (beforeAll chạy lại ở mỗi lượt retry). */
const createdProfileIds: number[] = [];

// ---------------------------------------------------------------------------
// Helpers — chẩn đoán fail-closed, không rò PII
// ---------------------------------------------------------------------------

function generatePhone(): string {
  const prefixes = ["091", "093", "097", "098", "035"];
  const prefix = prefixes[Math.floor(Math.random() * prefixes.length)];
  const suffix = Math.floor(Math.random() * 10_000_000)
    .toString()
    .padStart(7, "0");
  return prefix + suffix;
}

/**
 * Mô tả một response hỏng bằng ĐÚNG thứ cần để chẩn đoán: status, `error_code`,
 * và danh sách `loc:type` của từng lỗi validation.
 *
 * CỐ Ý không in body thô: body 422 của FastAPI mang khoá `input` echo lại
 * nguyên payload gửi lên (họ tên, điện thoại, email của lead) và log nightly
 * là artifact công khai trong repo. `detail` là chuỗi do backend soạn nên giữ
 * lại, cắt 200 ký tự.
 */
async function describeFailure(resp: APIResponse): Promise<string> {
  // Uỷ quyền cho `summarizeApiError` của helper dùng chung: một nguồn chuẩn
  // duy nhất cho việc rút gọn lỗi, và cũng là một chỗ duy nhất phải giữ luật
  // "không in `errors[].input`" (trường ấy echo nguyên văn payload).
  return summarizeApiError(resp.status(), await resp.text());
}

type HttpMethod = "get" | "post" | "patch" | "delete";

/**
 * Gọi API và NÉM nếu không 2xx. Đây là cái chặn duy nhất giữa "setup hỏng" và
 * "ca test đỏ ở một dòng không liên quan".
 */
async function apiJson(
  api: APIRequestContext,
  label: string,
  method: HttpMethod,
  url: string,
  data?: unknown,
): Promise<unknown> {
  const resp = await api[method](url, data === undefined ? undefined : { data });
  if (!resp.ok()) {
    throw new Error(
      `[SETUP FAIL] ${label}: ${method.toUpperCase()} ${url} → ${await describeFailure(resp)}`,
    );
  }
  return resp.json();
}

function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`[SETUP FAIL] ${label}: response không phải object JSON`);
  }
  return value as Record<string, unknown>;
}

function asArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`[SETUP FAIL] ${label}: response không phải mảng JSON`);
  }
  return value;
}

/**
 * Rút `id` số nguyên. Đúng cái bản cũ thiếu: `(await resp.json()).id` trên body
 * lỗi cho `undefined` rồi đi tiếp im lặng.
 */
function requireId(value: unknown, label: string): number {
  const id = asRecord(value, label).id;
  if (typeof id !== "number" || !Number.isInteger(id)) {
    throw new Error(`[SETUP FAIL] ${label}: response thiếu \`id\` số nguyên (nhận ${typeof id})`);
  }
  return id;
}

/** Ngày hôm nay theo giờ VN — backend chốt round bằng `today_vn()` (UTC+7). */
/**
 * Trạng thái tư vấn hợp lệ để `check_lead_level_admission_eligibility` cho qua:
 * KHÔNG `is_universal` (chỉ ghi nhận hoạt động) và KHÔNG `is_final` ở phase
 * consultation (lead đã đóng). Bản cũ lấy thẳng `statuses[0]` — đúng hay sai
 * tuỳ thứ tự seed, và vì không kiểm response nên sai cũng không ai biết.
 */
function pickConsultationStatusId(statuses: unknown[]): string {
  const candidates = statuses
    .map((s) => asRecord(s, "consultation status"))
    .filter(
      (s) =>
        typeof s.id === "string" &&
        s.is_universal !== true &&
        !(s.is_final === true && s.phase === "consultation"),
    )
    .sort(
      (a, b) =>
        (typeof a.display_order === "number" ? a.display_order : 0) -
        (typeof b.display_order === "number" ? b.display_order : 0),
    );
  if (candidates.length === 0) {
    throw new Error(
      `[SETUP FAIL] không có ConsultationStatus nào vừa không-universal vừa không-final ` +
        `(tổng ${statuses.length} status)`,
    );
  }
  return candidates[0].id as string;
}

// ---------------------------------------------------------------------------
// beforeAll / afterAll
// ---------------------------------------------------------------------------

test.beforeAll(async ({ browser }) => {
  const context = await browser.newContext({ storageState: AUTH_STATE_FILE });
  try {
    const api = context.request;

    // Bằng chứng phiên officer thật sự nạp được — nếu storageState trắng thì
    // đây là request đầu tiên đỏ, và thông điệp nói đúng nguyên nhân.
    const me = asRecord(await apiJson(api, "GET /api/profile (phiên officer)", "get", `${API_URL}/api/profile`), "profile");
    console.log(`[setup] phiên officer: user_id=${String(me.id)} role=${String(me.role)} unit_id=${String(me.unit_id)}`);

    const pipeline = asRecord(await apiJson(api, "GET /api/pipeline/all", "get", `${API_URL}/api/pipeline/all`), "pipeline");
    const statusId = pickConsultationStatusId(asArray(pipeline.statuses ?? [], "pipeline.statuses"));

    // Nguồn chuẩn DÙNG CHUNG với năm suite regression — xem
    // `helpers/e2e-fixtures.ts`. Ưu tiên năm hiện tại vì bộ lọc mặc định của
    // trang `/admissions` là `CURRENT_ADMISSIONS_YEAR = new Date().getFullYear()`.
    const fixture = await resolveAdmissionContext(api, {
      preferAcademicYears: [new Date().getFullYear()],
    });
    console.log(
      `[setup] fixture: offering=${fixture.offeringId} path=${fixture.pathId} ` +
        `round=${fixture.admissionRoundId} method=${fixture.admissionMethodId} năm=${fixture.academicYear}`,
    );

    const leadName = `E2E_UISmoke_${Date.now()}`;
    const leadId = requireId(
      await apiJson(api, "POST /api/leads", "post", `${API_URL}/api/leads`, {
        full_name: leadName,
        phone: generatePhone(),
        source: "walk_in",
        offering_id: fixture.offeringId,
      }),
      "POST /api/leads",
    );

    await apiJson(
      api,
      `POST /api/leads/${leadId}/consultations`,
      "post",
      `${API_URL}/api/leads/${leadId}/consultations`,
      { status_id: statusId, method: "phone", notes: "UI smoke test" },
    );

    // Bốn trường, KHÔNG phải hai. `admission_round_id` + `academic_year` là
    // Field(...) bắt buộc từ "Round contract hardening (plan v4 Section A)".
    const profileId = requireId(
      await apiJson(api, "POST /api/admissions", "post", `${API_URL}/api/admissions`, {
        lead_id: leadId,
        admission_method_id: fixture.admissionMethodId,
        admission_round_id: fixture.admissionRoundId,
        academic_year: fixture.academicYear,
      }),
      "POST /api/admissions",
    );
    createdProfileIds.push(profileId);

    // Đọc lại qua đúng endpoint mà trang danh sách dùng: tạo được chưa đủ,
    // hồ sơ phải THẬT SỰ nằm trong phạm vi mà officer này đọc được — nếu không
    // ca UI sẽ đỏ vì scope chứ không vì render.
    const listLabel = `GET /api/admissions?academic_year=${fixture.academicYear}`;
    const list = asRecord(
      await apiJson(api, listLabel, "get", `${API_URL}/api/admissions?academic_year=${fixture.academicYear}&page_size=100`),
      listLabel,
    );
    // Khoá của `AdmissionProfileListResponse` là `profiles` (không phải `items`
    // như `AdmissionPathListResponse`) — đã đo trên chính response thật.
    const items = asArray(list.profiles ?? [], listLabel);
    const found = items.some((it) => asRecord(it, listLabel).id === profileId);
    if (!found) {
      throw new Error(
        `[SETUP FAIL] hồ sơ ${profileId} vừa tạo KHÔNG có trong ${listLabel} ` +
          `(${items.length} hàng trả về) — phạm vi đọc của officer không chứa nó`,
      );
    }

    seed = {
      leadId,
      leadName,
      profileId,
      academicYear: fixture.academicYear,
      admissionRoundId: fixture.admissionRoundId,
      admissionMethodId: fixture.admissionMethodId,
      offeringId: fixture.offeringId,
    };
    console.log(`[setup] hồ sơ smoke: id=${profileId} lead=${leadId} năm=${fixture.academicYear}`);
  } finally {
    await context.close();
  }
});

test.afterAll(async ({ browser }) => {
  if (createdProfileIds.length === 0) return;
  const ids = createdProfileIds.splice(0, createdProfileIds.length);
  const context = await browser.newContext({ storageState: AUTH_STATE_FILE });
  const unexpected: string[] = [];
  try {
    for (const id of ids) {
      const resp = await context.request.delete(`${API_URL}/api/admissions/${id}`);
      const status = resp.status();
      if (status === 204 || status === 200) {
        console.log(`[cleanup] hồ sơ ${id}: ĐÃ XOÁ (HTTP ${status})`);
      } else if (status === 401 || status === 403) {
        // Đã đo trên `policy_templates.py`: OFFICER_TEMPLATE (dòng 111-332) và
        // MANAGER_TEMPLATE đều KHÔNG có rule nào cho `DELETE /api/admissions/{id}`;
        // chỉ ADMIN_TEMPLATE (`/*` + `.*`) có. Nên 403 ở đây là HỢP ĐỒNG, không
        // phải lỗi — nhưng nó KHÔNG được in ra thành chữ "deleted".
        console.log(
          `[cleanup] hồ sơ ${id}: KHÔNG xoá được — ${await describeFailure(resp)} ` +
            `(officer không có quyền DELETE /api/admissions/{id}; hồ sơ draft còn lại trong DB)`,
        );
      } else {
        unexpected.push(`hồ sơ ${id}: ${await describeFailure(resp)}`);
      }
    }
  } finally {
    await context.close();
  }
  if (unexpected.length > 0) {
    throw new Error(`[CLEANUP FAIL] DELETE trả status ngoài dự kiến:\n  ${unexpected.join("\n  ")}`);
  }
});

// ---------------------------------------------------------------------------
// Helpers cho phần UI
// ---------------------------------------------------------------------------

/**
 * Bắt mọi exception chưa bắt của trang. "Không crash" mà không nghe `pageerror`
 * thì chỉ là "không có locator nào timeout" — bản cũ đúng nghĩa đó.
 */
function watchPageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message.slice(0, 200)));
  return errors;
}

/** Error boundary của route hồ sơ: `admissions/[id]/error.tsx` + `error.tsx` gốc. */
function errorBoundary(page: Page) {
  return page.getByRole("heading", { name: /Đã xảy ra lỗi|Đã có lỗi xảy ra|Something went wrong/i });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test("List page hiện đúng hồ sơ vừa tạo", async ({ page }) => {
  const pageErrors = watchPageErrors(page);

  // `year` là khoá URL mà CẢ SSR (`parseAdmissionsSearchParamsToApiParams`) lẫn
  // client (`useAdmissionsFilter.parseSearchParams`) đọc. Ghim tường minh để ca
  // này không phụ thuộc việc năm học seed có trùng năm dương lịch hay không.
  await page.goto(`/admissions?year=${seed.academicYear}`);

  // Khung trang: breadcrumb + tablist lọc trạng thái. KHÔNG dùng riêng `h1` —
  // `h1` hiện ra cả khi danh sách rỗng lẫn khi API lỗi.
  await expect(page.getByRole("tablist", { name: "Lọc nhanh theo trạng thái" })).toBeVisible({
    timeout: 15_000,
  });

  // BẰNG CHỨNG CHÍNH: đúng hàng của hồ sơ suite này tạo ra.
  // Hợp đồng accessible có sẵn trong `AdmissionsClient.tsx` — mỗi hàng roster là
  // `role="link"` với `aria-label={`Hồ sơ ${lead.full_name}`}` (bản desktop dòng
  // 529, bản mobile dòng 693; bản kia luôn `display:none` theo breakpoint nên
  // không lọt vào cây accessibility).
  const row = page.getByRole("link", { name: `Hồ sơ ${seed.leadName}` });
  await expect(row).toBeVisible({ timeout: 15_000 });

  // Empty state PHẢI vắng mặt. Đây là câu chặn "nới assertion để nhận DB rỗng":
  // nếu setup lại thất bại im lặng thì dòng này đỏ với thông điệp đúng nguyên nhân.
  await expect(
    page.getByRole("heading", { name: "Chưa có hồ sơ nào" }),
    "danh sách rơi về empty state dù beforeAll đã tạo hồ sơ",
  ).toHaveCount(0);

  expect(pageErrors, `uncaught JS errors trên /admissions: ${pageErrors.join(" | ")}`).toHaveLength(0);
});

test("List page hiện empty state khi lọc sang năm chắc chắn rỗng", async ({ page }) => {
  // Tách hẳn khỏi ca trên theo yêu cầu: empty state là một HÀNH VI được canh,
  // không phải một lối thoát cho setup hỏng. Năm 2000 là cận dưới của
  // `AdmissionProfileCreate.academic_year` (`ge=2000`) nên không hồ sơ nào có
  // thể nằm ở đó, mà vẫn là giá trị hợp lệ để backend nhận và lọc.
  await page.goto("/admissions?year=2000");

  await expect(page.getByRole("tablist", { name: "Lọc nhanh theo trạng thái" })).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByRole("heading", { name: /Chưa có hồ sơ nào|Không tìm thấy kết quả/ })).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByRole("link", { name: `Hồ sơ ${seed.leadName}` })).toHaveCount(0);
});

test("Detail page: mọi bước mở được đều không crash", async ({ page }) => {
  const pageErrors = watchPageErrors(page);

  await page.goto(`/admissions/${seed.profileId}`);

  // Định danh, không phải "có h1": `AdmissionHeader` render tên + `#{profile.id}`.
  await expect(page.getByRole("heading", { level: 1 })).toContainText(`#${seed.profileId}`, {
    timeout: 15_000,
  });
  await expect(errorBoundary(page)).toHaveCount(0);

  // Điều hướng bước: `PipelineSidebar` render `<nav>` chứa 8 `<button>` (một
  // bản mobile `MobileStepStrip` `lg:hidden` — ở Desktop Chrome 1280px nó
  // display:none nên không vào cây accessibility). Bước bị khoá là `disabled`.
  const stepButtons = page.locator("aside nav button");
  await expect(stepButtons.first()).toBeVisible({ timeout: 15_000 });
  const total = await stepButtons.count();
  expect(total, "sidebar bước hồ sơ không render nút nào").toBeGreaterThan(0);

  let opened = 0;
  for (let i = 0; i < total; i++) {
    const button = stepButtons.nth(i);
    if (!(await button.isEnabled())) continue;
    const label = ((await button.textContent()) ?? "").trim().replace(/\s+/g, " ");
    await button.click();
    // Bước được chọn phải trở thành bước hiện tại (PipelineSidebar tô
    // `text-primary` + `font-semibold` cho `isActive`), rồi mới kiểm crash.
    await expect(button).toHaveClass(/font-semibold/, { timeout: 10_000 });
    await expect(errorBoundary(page), `bước "${label}" làm trang rơi vào error boundary`).toHaveCount(0);
    opened += 1;
    console.log(`[detail] bước "${label}" — mở OK`);
  }

  expect(opened, "không mở được bước nào (tất cả đều disabled)").toBeGreaterThan(0);
  expect(
    pageErrors,
    `uncaught JS errors trên /admissions/${seed.profileId}: ${pageErrors.join(" | ")}`,
  ).toHaveLength(0);
});

test("Đổi bước sau khi sửa thì hiện dialog 'Thay đổi chưa lưu'", async ({ page }) => {
  await page.goto(`/admissions/${seed.profileId}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(`#${seed.profileId}`, {
    timeout: 15_000,
  });

  // Bước 1 (Thông tin cá nhân) là bước mặc định; `full_name` nằm trong
  // `admissionProfileUpdateSchema` nên gõ vào đó làm react-hook-form `isDirty`.
  const nameInput = page.getByLabel("Họ và tên", { exact: true });
  await expect(nameInput).toBeVisible({ timeout: 15_000 });
  await nameInput.fill(`${seed.leadName}_DIRTY`);
  await nameInput.blur();

  const stepButtons = page.locator("aside nav button");
  const enabled: number[] = [];
  const total = await stepButtons.count();
  for (let i = 0; i < total; i++) {
    if (await stepButtons.nth(i).isEnabled()) enabled.push(i);
  }
  expect(
    enabled.length,
    "cần ít nhất 2 bước mở được để kiểm dialog đổi bước; hồ sơ draft này chỉ có " + enabled.length,
  ).toBeGreaterThanOrEqual(2);

  // Bấm sang một bước KHÁC bước đang đứng.
  await stepButtons.nth(enabled[enabled.length - 1]).click();

  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  await expect(dialog).toContainText("Thay đổi chưa lưu");

  // Ở lại: form giữ nguyên giá trị vừa gõ.
  await dialog.getByRole("button", { name: "Ở lại và lưu" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(nameInput).toHaveValue(`${seed.leadName}_DIRTY`);
});
