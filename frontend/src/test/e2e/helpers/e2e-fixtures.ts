/**
 * Helper DÙNG CHUNG cho các suite E2E nightly (regression + smoke).
 *
 * Ba việc, mỗi việc ra đời từ một ca đỏ ĐÃ ĐO trên nightly regression
 * run 34678745325 (head 6d25bf3b) và đã được đo lại trên stack cục bộ
 * `nfrb` dựng đúng theo `.github/workflows/nightly-regression.yml`:
 *
 * 1. TÁCH PRINCIPAL (`loginPrincipal`)
 *    `app/core/deps.py:164-171` đọc cookie `access_token` TRƯỚC, chỉ khi
 *    KHÔNG có cookie mới đọc `Authorization: Bearer`. Docstring gọi cookie
 *    là "RECOMMENDED" và header là "fallback" ⇒ cookie THẮNG Bearer là
 *    HỢP ĐỒNG, không phải bug.
 *    Đo thật (jar dùng chung: admin login trước, officer login sau, DELETE
 *    gửi Bearer admin):
 *        DELETE /api/leads/{id} → 403
 *        {"detail":"You do not have permission for this action.",
 *         "error_code":"PERMISSION_DENIED"}
 *    Cùng request ấy với principal admin ĐỘC LẬP (jar riêng) → 204.
 *    ⇒ Mỗi principal PHẢI có `APIRequestContext` riêng. Không có jar chung.
 *
 * 2. NGUỒN CHUẨN CHO HỒ SƠ TUYỂN SINH (`resolveAdmissionContext`)
 *    `app/schemas/admission.py:459-492` bắt buộc `admission_round_id` và
 *    `academic_year` ("Round contract hardening (plan v4 Section A,
 *    2026-05-25)"), đã GỠ fallback "first published OfferingAcademicInfo"
 *    và `current_intake_year`.
 *    Đo thật với payload 2 trường:
 *        POST /api/admissions → 422 VALIDATION_ERROR
 *        missing: body.admission_round_id · body.academic_year
 *    Helper này lấy ba giá trị từ ĐÚNG nguồn mà UI dùng —
 *    `GET /api/admission-config/paths/for-offering/{offering_id}` —
 *    mirror thuật toán của `frontend/src/app/(dashboard)/admissions/
 *    create/page.tsx:180-283`. KHÔNG hard-code round/method/năm.
 *
 * 3. CHỌN OFFICER HỢP LỆ (`pickOfficerForUnit`)
 *    `app/services/lead_service.py:2411-2423` `_assert_officer_in_lead_unit`
 *    ném `BusinessRuleViolation` (HTTP 400) khi officer khác đơn vị lead.
 *    Đo thật khi test lấy `users[0]` rời rạc với đơn vị của lead:
 *        POST /api/leads/{id}/assign → 400
 *        {"detail":"Không thể phân công: officer thuộc đơn vị #4, khác đơn
 *          vị của lead #1. Chỉ phân công officer cùng đơn vị.",
 *         "error_code":"BUSINESS_RULE_VIOLATION"}
 *    Helper này chọn officer THEO đơn vị của chính lead, và ném lỗi chẩn
 *    đoán được khi không có ứng viên nào thay vì để assert mù.
 *
 * QUY TẮC IN LOG: chỉ status, error_code, tên trường validation. TUYỆT ĐỐI
 * không in token, cookie, mật khẩu, TOTP, số điện thoại hay PII khác.
 */

import { expect, type APIRequestContext, type Cookie, type Page } from "@playwright/test";
import { duongState, voiMaTotp } from "./totp-coordinator";

export const API_URL = process.env.E2E_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Chẩn đoán — KHÔNG rò secret/PII
// ---------------------------------------------------------------------------

/**
 * Rút gọn một phản hồi lỗi thành chuỗi ĐỌC ĐƯỢC mà không rò dữ liệu.
 * Giữ đúng ba thứ có giá trị chẩn đoán: `error_code`, `detail`, và danh
 * sách trường validation (`loc` + `type`). Cố tình BỎ `input` — nó chứa
 * nguyên văn payload (có thể mang số điện thoại / CCCD).
 */
// Lọc log nằm ở `log-redaction.ts` — module THUẦN, không import Playwright,
// để canary `src/test/log-redaction.test.ts` chạy được dưới vitest (vitest.config
// loại trừ `src/test/e2e/**`, nên một canary đặt trong này sẽ không bao giờ chạy).
export { summarizeApiError, safeBody, correlationHash } from "./log-redaction";
import { summarizeApiError, safeBody } from "./log-redaction";
void safeBody;

interface MinimalResponse {
  status(): number;
  ok(): boolean;
  text(): Promise<string>;
}

/**
 * Assert HTTP thành công KÈM chẩn đoán. Thay cho `expect(resp.ok())
 * .toBeTruthy()` — assertion ấy in đúng "Received: false" và không nói
 * status hay lý do, đúng thứ đã làm lead-workflow:517 mù suốt một lượt
 * nightly.
 */
export async function expectOk(
  resp: MinimalResponse,
  label: string,
  accept: number[] = [200, 201, 204]
): Promise<void> {
  if (accept.includes(resp.status())) return;
  const body = await resp.text();
  expect(
    resp.status(),
    `${label} — ${summarizeApiError(resp.status(), body)}`
  ).toBe(accept[0]);
}

// ---------------------------------------------------------------------------
// TOTP — MỘT điều phối viên cho MỌI consumer `/verify-mfa`
// ---------------------------------------------------------------------------
//
// Phần cài đặt nằm ở `./totp-coordinator` (JavaScript thuần, không phụ thuộc
// `otpauth`) — xem docstring ở đầu tệp ấy để biết vì sao. Ở đây chỉ có lớp mỏng
// nối nó với `APIRequestContext`/`Page.request` của Playwright.
//
// ⛔ KHÔNG tệp nào dưới `frontend/src/test/e2e/**` — kể cả tệp này — được sinh
// mã TOTP theo đường khác: không `import "otpauth"`, không `generateTOTP` cục
// bộ, không `new OTPAuth.TOTP`. Bất biến ấy được
// `Backend_FastAPI/tests/unit/test_totp_coordinator_inventory.py` kiểm kê, và
// ca kiểm ngược của nó dựng lại đúng một bản sao cục bộ để chứng minh guard ĐỎ.

export { voiMaTotp } from "./totp-coordinator";
export type { MaTotp } from "./totp-coordinator";

/**
 * Đúng phần chữ ký `APIResponse` mà lớp MFA cần — không kéo cả kiểu.
 *
 * `headersArray()` có mặt vì consumer lấy `Set-Cookie` từ CHÍNH phản hồi
 * verify-mfa (`extractAndAddCookies`). Thiếu nó thì `R` bị suy về đúng ràng
 * buộc này ở những chỗ Playwright chưa nạp kiểu, và lời gọi sau đó đỏ ở một
 * chỗ không liên quan gì tới MFA.
 */
export interface PhanHoiMfa {
  status(): number;
  ok(): boolean;
  text(): Promise<string>;
  headersArray(): Array<{ name: string; value: string }>;
}

/**
 * ĐƯỜNG DUY NHẤT hoàn tất một challenge MFA trong toàn bộ `src/test/e2e/**`.
 *
 * Người gọi chỉ cung cấp cách GỬI (`page.request.post`, `ctx.post`, …); mã và
 * counter do điều phối viên cấp, và khoá tài khoản được giữ xuyên suốt lượt
 * gửi ấy — xem ca (B) trong `totp-coordinator.js`.
 *
 * ⛔ **KHÔNG RETRY.** Bản cũ ở sáu suite bắt `!ok()` rồi `sleep(31s); continue`.
 * Ba lý do nó phải biến mất:
 *   1. Nó che nguyên nhân: một mật khẩu sai, một tài khoản bị khoá, một hợp
 *      đồng MFA hỏng đều biến thành "thử lại rồi hết lượt" sau 93 giây.
 *   2. Nó đốt hạn mức đăng nhập ⇒ 429 ⇒ `ACCOUNT_LOCKOUT_MAX_ATTEMPTS`.
 *   3. Ca DUY NHẤT mà chờ-rồi-thử-lại chữa được là va counter, và đó chính là
 *      thứ điều phối viên đã đóng TRƯỚC khi gửi. Giữ lại retry cho ca ấy là
 *      giữ một lối thoát cho chính cái bug ta vừa vá — nó sẽ im lặng che
 *      mọi lần điều phối viên hỏng.
 *
 * Hỏng ⇒ NÉM NGAY, kèm chẩn đoán đã khử bí mật: status, `error_code`,
 * `detail`, counter đã tiêu, và đường dẫn state để đọc tiếp. KHÔNG in mã TOTP
 * (còn hiệu lực tới hết cửa sổ 30 giây) và KHÔNG in secret.
 */
export async function xacThucMfa<R extends PhanHoiMfa>(
  taiKhoan: string,
  secret: string,
  mfaToken: string,
  gui: (payload: { mfa_token: string; code: string }) => Promise<R>
): Promise<R> {
  return voiMaTotp(taiKhoan, secret, async ({ code, counter }) => {
    const resp = await gui({ mfa_token: mfaToken, code });
    if (resp.ok()) return resp;
    const detail = summarizeApiError(resp.status(), await resp.text());
    throw new Error(
      `verify-mfa THẤT BẠI cho ${taiKhoan}: HTTP ${resp.status()} ` +
        `totp_counter=${counter} — ${detail}. ` +
        `Nếu log backend có action=mfa.replay_rejected với đúng counter này ` +
        `thì điều phối viên TOTP đã hỏng: đọc ${duongState(taiKhoan)} ` +
        `(chỉ chứa một số nguyên). Mọi nguyên nhân khác — mã sai, phiên MFA ` +
        `hết hạn, MFA bị tắt — KHÔNG được thử lại ở đây.`
    );
  });
}

// ---------------------------------------------------------------------------
// Principal — MỖI principal MỘT APIRequestContext, jar KHÔNG dùng chung
// ---------------------------------------------------------------------------

export interface PrincipalUser {
  id: number;
  username: string;
  role: string;
  unit_id: number | null;
  full_name: string | null;
}

export interface Principal {
  label: string;
  username: string;
  /** Jar RIÊNG. Mọi request của principal này phải đi qua đây. */
  ctx: APIRequestContext;
  /** `X-CSRF-Token` của chính jar này. */
  headers: Record<string, string>;
  user: PrincipalUser;
  /** Cookie của jar này — dùng khi cần nạp vào một `Page` cho bước UI. */
  cookies(): Promise<Cookie[]>;
  dispose(): Promise<void>;
}

/** Chỉ cần đúng chữ ký này của fixture `playwright` — không kéo cả kiểu. */
export interface RequestContextFactory {
  newContext(options?: { baseURL?: string }): Promise<APIRequestContext>;
}

async function csrfOf(ctx: APIRequestContext): Promise<string> {
  const state = await ctx.storageState();
  const hit = state.cookies.find((c) => c.name === "csrf_token");
  return hit?.value ?? "";
}

/**
 * Đăng nhập MỘT principal vào MỘT `APIRequestContext` mới.
 *
 * Không có `clearCookies` toàn cục, không có "khôi phục cookie" — context
 * này sinh ra rỗng và chỉ chứa phiên của chính principal này suốt vòng đời
 * của nó. Đây là điều kiện để hợp đồng cookie-first ở `deps.py:164-171`
 * KHÔNG thể làm một request chạy nhầm danh tính.
 */
export async function loginPrincipal(
  factory: RequestContextFactory,
  opts: {
    label: string;
    username: string;
    password: string;
    totpSecret?: string;
    /** Số lần thử lại khi 429 / TOTP trùng cửa sổ. */
    attempts?: number;
  }
): Promise<Principal> {
  const attempts = opts.attempts ?? 3;
  let lastDiag = "";

  for (let i = 0; i < attempts; i++) {
    const ctx = await factory.newContext({ baseURL: API_URL });
    const loginResp = await ctx.post(`${API_URL}/api/auth/login`, {
      form: { username: opts.username, password: opts.password },
    });

    if (loginResp.status() === 429) {
      lastDiag = `429 rate-limited`;
      await ctx.dispose();
      // 429 là hạn mức thật của backend; chờ qua cửa sổ rồi thử lại.
      await new Promise((r) => setTimeout(r, 65_000));
      continue;
    }
    if (!loginResp.ok()) {
      const body = await loginResp.text();
      await ctx.dispose();
      throw new Error(
        `Đăng nhập ${opts.label} THẤT BẠI — ${summarizeApiError(loginResp.status(), body)}`
      );
    }

    const loginBody = await loginResp.json();
    if (loginBody.mfa_required) {
      if (!opts.totpSecret) {
        await ctx.dispose();
        throw new Error(
          `${opts.label} bị yêu cầu MFA nhưng không có TOTP secret ` +
            `(kiểm biến môi trường E2E_*_TOTP_SECRET — KHÔNG in giá trị).`
        );
      }
      // Không còn nhánh `catch → sleep(31s) → continue`. Va counter được đóng
      // TRƯỚC khi gửi bởi điều phối viên; mọi lỗi còn lại là hợp đồng hỏng và
      // phải dừng ngay. `xacThucMfa` ném với chẩn đoán đã khử bí mật.
      try {
        await xacThucMfa(opts.username, opts.totpSecret, loginBody.mfa_token, (payload) =>
          ctx.post(`${API_URL}/api/auth/verify-mfa`, { data: payload })
        );
      } catch (e) {
        await ctx.dispose();
        throw new Error(`${opts.label}: ${(e as Error).message}`);
      }
    }

    // Danh tính phải ĐỌC RA từ phiên, không suy từ tên đăng nhập.
    const meResp = await ctx.get(`${API_URL}/api/users/me`);
    if (!meResp.ok()) {
      const body = await meResp.text();
      await ctx.dispose();
      throw new Error(
        `${opts.label}: /api/users/me sau đăng nhập — ${summarizeApiError(meResp.status(), body)}`
      );
    }
    const me = (await meResp.json()) as PrincipalUser;
    const headers: Record<string, string> = {};
    const csrf = await csrfOf(ctx);
    if (csrf) headers["X-CSRF-Token"] = csrf;

    return {
      label: opts.label,
      username: opts.username,
      ctx,
      headers,
      user: me,
      cookies: async () => (await ctx.storageState()).cookies as Cookie[],
      dispose: () => ctx.dispose(),
    };
  }
  throw new Error(
    `Đăng nhập ${opts.label} THẤT BẠI sau ${attempts} lượt (lần cuối: ${lastDiag}).`
  );
}

/**
 * Chứng minh một principal vẫn đúng danh tính TẠI THỜI ĐIỂM gọi.
 * Dùng như một cổng trước khi chạy bước nhạy cảm quyền (xoá, phân công).
 */
export async function assertPrincipal(p: Principal): Promise<void> {
  const resp = await p.ctx.get(`${API_URL}/api/users/me`);
  await expectOk(resp, `assertPrincipal(${p.label}) /api/users/me`, [200]);
  const me = (await resp.json()) as PrincipalUser;
  expect(
    me.id,
    `principal "${p.label}" LỆCH: phiên đang là user #${me.id} (${me.role}), ` +
      `cần #${p.user.id} (${p.user.role}). Jar đã bị dùng chung?`
  ).toBe(p.user.id);
  expect(me.role, `principal "${p.label}" đổi role giữa chừng`).toBe(p.user.role);
}

/**
 * Nạp cookie của một principal vào một `Page` (chỉ cho bước UI cần
 * `page.goto`), RỒI CHỨNG MINH trang đang chạy đúng danh tính đó.
 *
 * Đây là biến thể fail-closed của `restoreCookies` cũ: bản cũ đổi jar rồi
 * tin là xong, nên một lượt đổi sót đi thẳng vào request kế tiếp dưới
 * danh tính cũ mà không ai thấy.
 */
export async function usePrincipalOnPage(
  page: Page,
  p: Principal
): Promise<Record<string, string>> {
  await page.context().clearCookies();
  const cookies = await p.cookies();
  if (cookies.length > 0) await page.context().addCookies(cookies);

  const resp = await page.request.get(`${API_URL}/api/users/me`);
  await expectOk(resp, `usePrincipalOnPage(${p.label}) /api/users/me`, [200]);
  const me = (await resp.json()) as PrincipalUser;
  expect(
    me.id,
    `Page đang chạy dưới user #${me.id} (${me.role}) chứ không phải ` +
      `"${p.label}" #${p.user.id} (${p.user.role}).`
  ).toBe(p.user.id);

  const jar = await page.context().cookies();
  const csrf = jar.find((c) => c.name === "csrf_token")?.value;
  return csrf ? { "X-CSRF-Token": csrf } : {};
}

// ---------------------------------------------------------------------------
// Chọn officer HỢP LỆ theo quan hệ đơn vị của dữ liệu seed
// ---------------------------------------------------------------------------

export interface OfficerPick {
  id: number;
  username: string;
  full_name: string | null;
  unit_id: number;
  max_capacity: number | null;
}

/**
 * Danh sách officer ĐANG HOẠT ĐỘNG kèm `unit_id`.
 *
 * ⚠️ KHÔNG dùng `/api/admin/roles/officer/users`: nó trả về một OBJECT
 * `{role, user_count, users}` chứ không phải mảng (nên `users.length` là
 * `undefined`), và nó lọc grouping policy theo `group[1] == "officer"`
 * trong khi seed ghi `v1 = "role:officer"` — đo thật trên stack nightly:
 * `user_count = 0`. Hai lỗi ấy làm mọi lời gọi rơi âm thầm xuống fallback.
 */
export async function listActiveOfficers(
  ctx: APIRequestContext
): Promise<OfficerPick[]> {
  const resp = await ctx.get(
    `${API_URL}/api/admin/users?role=officer&status=active&page_size=200`
  );
  await expectOk(resp, "listActiveOfficers GET /api/admin/users", [200]);
  const body = (await resp.json()) as {
    users?: Array<{
      id: number;
      username: string;
      full_name?: string | null;
      role: string;
      status: string;
      unit_id?: number | null;
      max_capacity?: number | null;
    }>;
  };
  return (body.users ?? [])
    .filter((u) => u.role === "officer" && u.status === "active" && u.unit_id != null)
    .map((u) => ({
      id: u.id,
      username: u.username,
      full_name: u.full_name ?? null,
      unit_id: u.unit_id as number,
      max_capacity: u.max_capacity ?? null,
    }));
}

/**
 * Officer HỢP LỆ để phân công một lead thuộc `unitId`.
 *
 * Bất biến backend (`lead_service.assign_lead_manually`, dòng 2454-2472):
 *   officer tồn tại · role == officer · status == active · CÙNG unit lead.
 * Không có ứng viên ⇒ ném lỗi nêu rõ đơn vị và các đơn vị CÓ officer,
 * thay vì để `expect(resp.ok())` báo "Received: false".
 */
export async function pickOfficerForUnit(
  ctx: APIRequestContext,
  unitId: number,
  opts?: { exclude?: number[] }
): Promise<OfficerPick> {
  const all = await listActiveOfficers(ctx);
  const exclude = new Set(opts?.exclude ?? []);
  const hit = all.filter((o) => o.unit_id === unitId && !exclude.has(o.id));
  if (hit.length === 0) {
    const byUnit = new Map<number, number>();
    for (const o of all) byUnit.set(o.unit_id, (byUnit.get(o.unit_id) ?? 0) + 1);
    throw new Error(
      `Không có officer active nào thuộc đơn vị #${unitId} ` +
        `(loại trừ: ${[...exclude].join(",") || "không"}). ` +
        `Phân bố officer theo đơn vị: ` +
        `${[...byUnit.entries()].map(([u, n]) => `#${u}:${n}`).join(" ")}. ` +
        `Backend chặn phân công khác đơn vị tại ` +
        `lead_service._assert_officer_in_lead_unit (400 BUSINESS_RULE_VIOLATION).`
    );
  }
  return hit[0];
}

/**
 * Officer bất kỳ đang hoạt động VÀ có đơn vị — dùng khi test được quyền
 * CHỌN đơn vị của lead (tạo lead với `unit_id` của chính officer ấy).
 * Đây là cách duy nhất tránh cặp (`units[0]`, `users[0]`) rời rạc.
 */
export async function pickAssignableOfficer(
  ctx: APIRequestContext,
  opts?: { exclude?: number[] }
): Promise<OfficerPick> {
  const all = await listActiveOfficers(ctx);
  const exclude = new Set(opts?.exclude ?? []);
  const hit = all.filter((o) => !exclude.has(o.id));
  if (hit.length === 0) {
    throw new Error(
      `Seed không có officer active nào có unit_id (tổng officer đọc được: ${all.length}).`
    );
  }
  return hit[0];
}

// ---------------------------------------------------------------------------
// Nguồn chuẩn cho hồ sơ tuyển sinh — mirror UI create page
// ---------------------------------------------------------------------------

/** Hôm nay theo giờ VN, dạng YYYY-MM-DD. So chuỗi, KHÔNG `new Date(...)`. */
export function todayVN(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Ho_Chi_Minh" });
}

export interface AdmissionPathContext {
  offeringId: number;
  pathId: number;
  admissionMethodId: number;
  admissionRoundId: number;
  academicYear: number;
  roundCode: string | null;
  /** Hôm nay nằm trong [start, end] theo giờ VN. */
  roundIsOpen: boolean;
}

interface RawPath {
  id: number;
  status: string;
  admission_method_id: number;
  admission_round_id: number;
  round_code?: string | null;
  round_is_active?: boolean | null;
  round_archived_at?: string | null;
  round_start_date?: string | null;
  round_end_date?: string | null;
  academic_info?: { academic_year?: number } | null;
}

/**
 * Ứng viên path dùng được của một offering, theo ĐÚNG bộ lọc của UI
 * (`admissions/create/page.tsx:186-225`):
 *   path.status == "active" · round KHÔNG archived · round KHÔNG inactive ·
 *   có `academic_info.academic_year`.
 * Sắp xếp: round đang MỞ lên trước (mirror `openRounds` của UI).
 */
export async function resolvePathsForOffering(
  ctx: APIRequestContext,
  offeringId: number
): Promise<AdmissionPathContext[]> {
  const resp = await ctx.get(
    `${API_URL}/api/admission-config/paths/for-offering/${offeringId}`
  );
  await expectOk(
    resp,
    `resolvePathsForOffering(${offeringId}) GET /api/admission-config/paths/for-offering`,
    [200]
  );
  const body = (await resp.json()) as { total?: number; items?: RawPath[] };
  const today = todayVN();

  const out: AdmissionPathContext[] = [];
  for (const p of body.items ?? []) {
    if (p.status !== "active") continue;
    if (p.round_archived_at != null) continue;
    if (p.round_is_active === false) continue;
    const year = p.academic_info?.academic_year;
    if (typeof year !== "number") continue;
    const start = p.round_start_date ?? null;
    const end = p.round_end_date ?? null;
    // `assert_round_open` (app/utils/admission_round_guards.py:61) chỉ chặn
    // khi end_date < hôm nay. end_date NULL = mở vô hạn ⇒ KHÔNG loại.
    if (end != null && end < today) continue;
    out.push({
      offeringId,
      pathId: p.id,
      admissionMethodId: p.admission_method_id,
      admissionRoundId: p.admission_round_id,
      academicYear: year,
      roundCode: p.round_code ?? null,
      roundIsOpen:
        start != null && end != null ? start <= today && today <= end : end == null,
    });
  }
  out.sort((a, b) => (a.roundIsOpen === b.roundIsOpen ? 0 : a.roundIsOpen ? -1 : 1));
  return out;
}

/**
 * Chọn (offering, path, round, năm, phương thức) TƯƠNG THÍCH VỚI NHAU.
 *
 * Vì sao không nhận `offerings[0]`: `GET /api/program-offerings` sắp xếp
 * theo `offering_type` — KHÔNG duy nhất — nên Postgres phá hoà tuỳ ý.
 * Đo thật cùng một CSDL: `limit=5` cho phần tử đầu là offering #1, còn
 * `limit=20` cho offering #28; và offering #5 có 0 path dùng được. Lấy
 * phần tử đầu là rút thăm.
 *
 * Thứ tự ưu tiên: `preferOfferingIds` → offering có path (id tăng dần).
 */
export async function resolveAdmissionContext(
  ctx: APIRequestContext,
  opts?: {
    offeringId?: number;
    preferOfferingIds?: number[];
    preferMethodIds?: number[];
    /**
     * Ưu tiên path thuộc các năm này, theo thứ tự. Chỉ là ƯU TIÊN: hết năm ưu
     * tiên thì vẫn nhận path năm khác, vì bộ lọc năm là chuyện của lời gọi chứ
     * không phải điều kiện hợp lệ của path.
     *
     * Suite smoke cần nó vì bộ lọc mặc định của trang `/admissions` là
     * `CURRENT_ADMISSIONS_YEAR = new Date().getFullYear()`
     * (`hooks/admissions/filterDefaults.ts`). Bỏ trống ⇒ hành vi KHÔNG đổi.
     */
    preferAcademicYears?: number[];
  }
): Promise<AdmissionPathContext> {
  const pickByMethod = (cands: AdmissionPathContext[]): AdmissionPathContext => {
    const prefer = opts?.preferMethodIds ?? [];
    for (const m of prefer) {
      const hit = cands.find((c) => c.admissionMethodId === m);
      if (hit) return hit;
    }
    return cands[0];
  };

  // Năm ưu tiên lọc TRƯỚC, phương thức chọn TRONG tập đã lọc. Danh sách rỗng
  // ⇒ rơi thẳng về `pickByMethod`, nên lời gọi cũ giữ nguyên kết quả.
  const pick = (cands: AdmissionPathContext[]): AdmissionPathContext => {
    for (const y of opts?.preferAcademicYears ?? []) {
      const sub = cands.filter((c) => c.academicYear === y);
      if (sub.length > 0) return pickByMethod(sub);
    }
    return pickByMethod(cands);
  };

  if (opts?.offeringId != null) {
    const cands = await resolvePathsForOffering(ctx, opts.offeringId);
    if (cands.length === 0) {
      throw new Error(
        `Offering #${opts.offeringId} KHÔNG có admission path dùng được ` +
          `(active + round chưa archived/inactive/hết hạn). ` +
          `POST /api/admissions sẽ 400 vì không tìm thấy path cho ` +
          `(round, offering, method).`
      );
    }
    return pick(cands);
  }

  const listResp = await ctx.get(
    `${API_URL}/api/program-offerings?is_active=true&limit=200`
  );
  await expectOk(listResp, "resolveAdmissionContext GET /api/program-offerings", [200]);
  const offerings = (await listResp.json()) as Array<{ id: number }>;
  if (offerings.length === 0) {
    throw new Error("Seed không có program offering nào đang hoạt động.");
  }

  const ordered = [
    ...(opts?.preferOfferingIds ?? []),
    ...offerings.map((o) => o.id).sort((a, b) => a - b),
  ].filter((id, i, arr) => arr.indexOf(id) === i);

  const tried: string[] = [];
  for (const id of ordered) {
    if (!offerings.some((o) => o.id === id)) continue;
    const cands = await resolvePathsForOffering(ctx, id);
    tried.push(`#${id}:${cands.length}`);
    if (cands.length > 0) return pick(cands);
  }
  throw new Error(
    `Không offering nào có admission path dùng được. Đã thử (offering:số path): ` +
      `${tried.join(" ")}`
  );
}

/**
 * Payload ĐỦ TRƯỜNG cho `POST /api/admissions`.
 * Bốn trường này là toàn bộ `AdmissionProfileCreate`
 * (`app/schemas/admission.py:443-494`) — cả bốn đều `Field(...)` bắt buộc.
 */
export function buildProfilePayload(
  leadId: number,
  pc: AdmissionPathContext
): {
  lead_id: number;
  admission_method_id: number;
  admission_round_id: number;
  academic_year: number;
} {
  return {
    lead_id: leadId,
    admission_method_id: pc.admissionMethodId,
    admission_round_id: pc.admissionRoundId,
    academic_year: pc.academicYear,
  };
}

/**
 * Tạo hồ sơ tuyển sinh và FAIL NGAY, có chẩn đoán, nếu không được.
 *
 * Sự cố gốc: `beforeAll` của suite smoke tạo hồ sơ THẤT BẠI IM LẶNG (422),
 * nên CSDL 0 hồ sơ, rồi `/admissions` render đúng nhưng rỗng và assertion
 * UI đỏ ở một chỗ CHẲNG LIÊN QUAN. Hàm này ném lỗi tại đúng request hỏng.
 */
export async function createAdmissionProfile(
  ctx: APIRequestContext,
  leadId: number,
  pc: AdmissionPathContext,
  headers: Record<string, string>
): Promise<Record<string, unknown>> {
  const payload = buildProfilePayload(leadId, pc);
  const resp = await ctx.post(`${API_URL}/api/admissions`, {
    headers,
    data: payload,
  });
  if (resp.status() !== 200 && resp.status() !== 201) {
    const body = await resp.text();
    throw new Error(
      `Tạo hồ sơ THẤT BẠI cho lead #${leadId} — ` +
        `${summarizeApiError(resp.status(), body)} · ` +
        `gửi lên: method=${pc.admissionMethodId} round=${pc.admissionRoundId} ` +
        `year=${pc.academicYear} (path #${pc.pathId}, offering #${pc.offeringId})`
    );
  }
  return (await resp.json()) as Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Fixture danh mục KV — xã / trường do `scripts/seeds/seed_e2e_catalog_fixture`
// seed. KHÔNG hard-code `school_id`: id là số tự tăng, phụ thuộc thứ tự seed.
// ---------------------------------------------------------------------------

/** Xã thường trú của fixture — `22045` map sang **KV1** trong `vn_commune_area_map`. */
export const FIXTURE_TINH = "Tỉnh Đắk Lắk";
export const FIXTURE_XA = "Phường Bình Kiến";
export const FIXTURE_MA_XA = "22045";

/**
 * Trường THPT của fixture dùng cho `academic_history[].school_id`.
 *
 * CỐ Ý chọn `904` — trường ấy được seed ở KV3 trong khi xã thường trú `22045`
 * là KV1. Nhờ độ lệch ấy, một khẳng định trên `kv_resolved` phân biệt được
 * engine đã đi ngã TRƯỜNG (`LICH_SU_THPT` → KV3) hay ngã THƯỜNG TRÚ
 * (`THUONG_TRU` → KV1). Hai KV bằng nhau thì phép kiểm không nói lên điều gì.
 *
 * `province=066` là ĐÚNG quy ước mà `GET /api/v2/vn-school/search` đòi
 * (`Query(min_length=3, max_length=3)`); mã hai ký tự không bao giờ khớp.
 */
export async function resolveFixtureSchoolId(
  ctx: { get(url: string): Promise<MinimalResponse & { json(): Promise<unknown> }> }
): Promise<number> {
  const resp = await ctx.get(
    `${API_URL}/api/v2/vn-school/search?q=E2E&level=THPT&province=066`
  );
  await expectOk(resp, "GET /api/v2/vn-school/search (fixture trường THPT)", [200]);
  const tho = (await resp.json()) as unknown;
  const ds = (Array.isArray(tho) ? tho : (tho as { items?: unknown[] })?.items ?? []) as Array<{
    id?: number;
    moet_school_code?: string;
    moet_province_code?: string;
  }>;
  const hit = ds.find(
    (s) => s.moet_school_code === "904" && s.moet_province_code === "066"
  );
  expect(
    hit?.id,
    `Fixture danh mục chưa được seed: không tìm thấy trường moet_school_code=904 ` +
      `province=066 trong ${ds.length} kết quả. Chạy ` +
      `\`python -m scripts.seeds.seed_e2e_catalog_fixture --apply\` trước E2E.`
  ).toBeTruthy();
  return hit!.id as number;
}

/** Mục `academic_history` ĐỦ TRƯỜNG cho nhánh `LICH_SU_THPT`. */
export function fixtureAcademicHistory(schoolId: number, yearFrom = 2019, yearTo = 2022) {
  return [
    {
      school_name: "THPT E2E Tuy Hòa (KV3)",
      school_id: schoolId,
      // `priority_service.py:652-672` chỉ nhận {THPT, THCS_THPT, GDTX}; thiếu
      // `level` thì không mục nào đủ điều kiện và engine trả
      // `no_qualifying_thpt_history_entries`.
      level: "THPT",
      grade_to: 12,
      year_from: yearFrom,
      year_to: yearTo,
      gpa: 8.5,
      graduation_type: "THPT",
    },
  ];
}
