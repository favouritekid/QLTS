/**
 * Lọc dữ liệu trước khi ghi ra log của lượt E2E.
 *
 * VÌ SAO TỒN TẠI: kho này **PUBLIC**, nên log GitHub Actions của mọi lượt
 * nightly đọc được công khai. Nightly seed CSDL bằng `scripts/seed_from_xlsx`,
 * nên bất kỳ `console.log(JSON.stringify(body))` nào của một lead / hồ sơ /
 * phiếu thu đều in **nội dung bản ghi** ra một trang ai cũng xem được.
 *
 * VÌ SAO KHÔNG DÙNG `slice(0, N)`: cắt ngắn không phải lọc. `…slice(0, 300)`
 * vẫn in trọn 300 ký tự đầu, mà 300 ký tự đầu của một hồ sơ là đúng phần có
 * họ tên, điện thoại, CCCD. Và `detail` của backend là **văn xuôi tiếng Việt**
 * có nhúng tên phường/xã, tên trường THPT — không regex nào tách được một tên
 * phường khỏi một từ thường, nên cách duy nhất đúng là KHÔNG in nội dung nó.
 *
 * NGUYÊN TẮC: danh sách khoá ĐƯỢC PHÉP, không phải danh sách khoá bị cấm.
 * Khoá lạ mặc định bị che. Thêm một trường mới vào API sẽ tự động bị che chứ
 * không tự động lọt ra — đó là fail-closed, và là điểm khác biệt duy nhất có
 * ý nghĩa giữa hai cách làm.
 *
 * Khoá được phép chỉ gồm thứ KHÔNG nhận dạng được cá nhân: mã trạng thái,
 * mã lỗi, số đếm, cờ, và **khoá ngoại dạng số**. ID không phải PII trong ngữ
 * cảnh này (log đã có sẵn ID ở URL), còn tên/điện thoại/CCCD/email/địa chỉ
 * thì có.
 */

/** Khoá được ghi NGUYÊN VĂN khi giá trị là số / chuỗi ngắn / boolean. */
export const SAFE_KEYS: ReadonlySet<string> = new Set([
  // định danh + phân trang
  "id", "ids", "total", "count", "page", "page_size", "limit", "offset",
  "successful", "failed", "skipped", "created", "updated", "deleted",
  "version", "schema_version",
  // khoá ngoại
  "lead_id", "profile_id", "application_id", "unit_id", "officer_id",
  "actor_id", "user_id", "fee_id", "invoice_id", "payment_id",
  "offering_id", "path_id", "admission_round_id", "admission_method_id",
  "academic_year", "assigned_officer_id", "consultation_status_id",
  "status_id", "stage_id", "current_status_id",
  // phân loại / cờ — giá trị là enum do lập trình viên đặt
  "status", "error_code", "code", "type", "outcome_type", "phase",
  "is_final", "is_active", "is_universal", "enabled", "ok", "success",
  "role", "method", "channel", "resolver_type", "rule_applied",
  "round_is_active", "round_code", "selectable_mode",
]);

/** Khoá LUÔN bị che kể cả khi trùng tên với khoá an toàn ở hệ khác. */
const ALWAYS_MASK: ReadonlySet<string> = new Set([
  "access_token", "refresh_token", "token", "csrf_token", "password",
  "secret", "otp", "totp", "authorization", "cookie", "set-cookie",
  "input", "detail", "msg", "message",
]);

const MAX_KEYS = 14;
const MAX_ITEMS = 3;

/**
 * Băm tương quan 32-bit (FNV-1a). KHÔNG phải phép băm mật mã và không nhằm
 * giấu bí mật — nó chỉ để hai lượt chạy khác nhau nhận ra "vẫn đúng thông điệp
 * lỗi ấy", và để người sửa lỗi tái hiện cục bộ rồi đối chiếu. Nội dung thật
 * không bao giờ rời khỏi máy chạy test.
 */
export function correlationHash(s: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}

function maskedScalar(v: unknown): string {
  if (typeof v === "string") return `<str:${v.length} h=${correlationHash(v)}>`;
  if (typeof v === "number" || typeof v === "boolean") return `<${typeof v}>`;
  if (v === null) return "<null>";
  if (Array.isArray(v)) return `<arr:${v.length}>`;
  if (typeof v === "object") return `<obj:${Object.keys(v as object).length}>`;
  return `<${typeof v}>`;
}

function safeScalar(v: unknown): string {
  if (v === null) return "null";
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (typeof v === "string") {
    // Ngay cả dưới khoá an toàn, một chuỗi DÀI là dấu hiệu nó không phải enum.
    // Enum của kho này dài nhất khoảng 40 ký tự.
    return v.length <= 40 ? JSON.stringify(v) : maskedScalar(v);
  }
  return maskedScalar(v);
}

/**
 * Rút gọn một thân phản hồi đã parse thành chuỗi AN TOÀN để ghi log.
 * Chỉ khoá trong {@link SAFE_KEYS} được ghi giá trị; mọi khoá khác chỉ lộ
 * KIỂU và ĐỘ DÀI.
 */
export function safeBody(value: unknown, depth = 0): string {
  if (value === null || value === undefined) return "null";
  if (typeof value !== "object") return maskedScalar(value);

  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    const head = value
      .slice(0, MAX_ITEMS)
      .map((v) => (depth >= 2 ? maskedScalar(v) : safeBody(v, depth + 1)));
    const more = value.length > MAX_ITEMS ? `, …+${value.length - MAX_ITEMS}` : "";
    return `[${head.join(", ")}${more}] (n=${value.length})`;
  }

  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj);
  const shown = keys.slice(0, MAX_KEYS);
  const parts = shown.map((k) => {
    const lower = k.toLowerCase();
    const v = obj[k];
    if (ALWAYS_MASK.has(lower)) return `${k}=${maskedScalar(v)}`;

    // RANH GIỚI, đã ĐO chứ không giả định: mọi cột nhân thân của hệ này đều
    // kiểu chuỗi — `lead.full_name/email/phone` là `Column(String(...))`
    // (`app/models/lead.py:95-97`), `admission.citizen_id/full_name/email/
    // phone/permanent_ward/permanent_street_address` là `Mapped[str]`
    // (`app/models/admission.py:171-222`). Số và boolean ở đây là ID, số đếm,
    // version, cờ — không nhận dạng được cá nhân, và ID thì log đã có sẵn
    // trong URL. Vì vậy chỉ CHUỖI mới cần danh sách cho phép.
    //
    // Nới rộng hơn thế là sai: một chuỗi lạ có thể là họ tên, tên phường,
    // tên trường — thứ không regex nào tách được khỏi từ thường.
    if (typeof v === "boolean" || typeof v === "number") return `${k}=${v}`;

    if (v !== null && typeof v === "object" && depth < 2) {
      return `${k}=${safeBody(v, depth + 1)}`;
    }
    if (!SAFE_KEYS.has(lower)) return `${k}=${maskedScalar(v)}`;
    return `${k}=${safeScalar(v)}`;
  });
  const more = keys.length > MAX_KEYS ? `, …+${keys.length - MAX_KEYS} khoá` : "";
  return `{${parts.join(", ")}${more}}`;
}

/**
 * Rút gọn một phản hồi LỖI thành chuỗi chẩn đoán được mà không rò dữ liệu.
 *
 * Ghi nguyên văn: `status`, `error_code`, và danh sách **TÊN TRƯỜNG** không
 * hợp lệ (`loc` + `type`). Tên trường là hằng của lược đồ, không phải dữ liệu
 * người dùng.
 *
 * KHÔNG ghi: `detail`, `errors[].msg`, `errors[].input`, và thân phi-JSON —
 * cả bốn đều có thể mang PII. Chúng chỉ lộ độ dài + băm tương quan.
 */
export function summarizeApiError(status: number, bodyText: string): string {
  const bits: string[] = [`status=${status}`];

  let parsed: unknown;
  try {
    parsed = JSON.parse(bodyText);
  } catch {
    bits.push(`body=<non-JSON:${bodyText.length}B h=${correlationHash(bodyText)}>`);
    return bits.join(" ");
  }
  if (parsed === null || typeof parsed !== "object") {
    bits.push(`body=${maskedScalar(parsed)}`);
    return bits.join(" ");
  }

  const body = parsed as {
    detail?: unknown;
    error_code?: unknown;
    errors?: unknown;
  };

  if (typeof body.error_code === "string" && body.error_code.length <= 64) {
    bits.push(`error_code=${body.error_code}`);
  }

  if (Array.isArray(body.errors) && body.errors.length > 0) {
    const fields = body.errors
      .slice(0, 12)
      .map((e) => {
        const item = (e ?? {}) as { loc?: unknown; type?: unknown };
        const loc = Array.isArray(item.loc)
          ? item.loc.map((x) => String(x)).join(".")
          : "?";
        return `${loc}[${item.type == null ? "?" : String(item.type)}]`;
      })
      .join(", ");
    bits.push(`invalid_fields=${fields}`);
  }

  // `detail` là văn xuôi do backend dựng, có chỗ nhúng tên phường/xã và tên
  // trường THPT. Chỉ lộ độ dài + băm để đối chiếu giữa các lượt.
  if (typeof body.detail === "string") {
    bits.push(`detail=<str:${body.detail.length} h=${correlationHash(body.detail)}>`);
  } else if (body.detail != null) {
    bits.push(`detail=${maskedScalar(body.detail)}`);
  }

  return bits.join(" ");
}
