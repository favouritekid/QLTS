// src/lib/api/refresh.ts
/**
 * Nơi DUY NHẤT quyết định mọi chuyện về làm mới phiên.
 *
 * Ba việc gộp ở đây vì tách ra là chúng sẽ lệch nhau:
 *  1. phối hợp giữa các tab (chỉ một tab được POST cho mỗi lần làm mới);
 *  2. phân loại kết quả (lỗi nào là phiên chết, lỗi nào chỉ tạm thời);
 *  3. quyết định có được xoá cookie hay không.
 *
 * Module CHỈ import axios + env + endpoints + lớp phối hợp (KHÔNG import `api`
 * từ client.ts) để tránh circular import.
 */
import axios from "axios";

import { env } from "@/lib/config/env";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { getCSRFToken } from "@/lib/api/csrf";
import {
  acquireRefreshLock,
  HEARTBEAT_MS,
  type LockHandle,
} from "./refresh-coordination/lock";
import {
  supersedeIfGenerationChanged,
  clearJournalAfter,
  type ClearTrigger,
} from "./refresh-coordination/lifecycle";
import { selectJournalStore } from "./refresh-coordination/storage";
import type { JournalRecord, ResultKind } from "./refresh-coordination/types";

/** `error_code` của 429 do rate limit hạ tầng (slowapi). */
const TRANSIENT_RATE_LIMIT_CODE = "RATE_LIMITED";
/** Mã lỗi chứng minh phiên đã chết phía server. Mở rộng phải rất dè dặt. */
const TERMINAL_ERROR_CODES = new Set(["REFRESH_ABUSE_LOCKED"]);

const DEFAULT_COOLDOWN_MS = 60_000;
const MAX_COOLDOWN_MS = 5 * 60_000;
/** Chờ tab khác bao lâu trước khi bỏ cuộc (KHÔNG phải trước khi thử lại). */
const FOLLOWER_WAIT_MS = 15_000;
const FOLLOWER_POLL_MS = 250;
/** Chờ trình duyệt persist cookie mới trước khi caller retry. */
const COOKIE_PERSIST_MS = 100;

/**
 * Một bản ghi bao lâu tuổi thì còn được coi là bằng chứng "token mới còn hạn".
 *
 * Phải BAO ĐƯỢC một cuộc đua giữa các tab (vài giây, và lease sống 20 giây)
 * nhưng NHỎ HƠN NHIỀU chu kỳ proactive 13 phút — nếu không, nhật ký của chu kỳ
 * trước sẽ biến chu kỳ sau thành no-op và access token chết trong khoảng trống.
 */
const FRESH_PROOF_WINDOW_MS = 30_000;

// ---------------------------------------------------------------------------
// Kết quả — có cấu trúc, để caller không phải đoán lại
// ---------------------------------------------------------------------------

export type RefreshOutcome =
  | { kind: "success" }
  | { kind: "terminal"; status?: number; errorCode?: string }
  | { kind: "safe-retryable"; retryAt: number }
  | { kind: "nonterminal-stop"; status?: number; errorCode?: string }
  | {
      kind: "ambiguous";
      reason:
        | "no-store"
        | "write-failed"
        | "network"
        | "server"
        | "no-proof"
        | "stale-attempt"
        | "wait-timeout";
    };

/**
 * Lỗi mang theo kết quả đã phân loại.
 *
 * Cố ý KHÔNG dựng một `AxiosError` giả để caller tự phân loại lại: hai nơi
 * cùng đoán từ `status` là hai nơi sẽ lệch nhau, và đó đúng là lỗi đã xảy ra ở
 * bootstrap (nó từng giữ một bản sao classifier).
 */
/**
 * Nhãn nhận dạng dùng chung giữa mọi bản module.
 *
 * `Symbol.for` lấy từ registry symbol dùng chung giữa các **bản module/bundle
 * trong cùng một JavaScript agent**, nên hai bản `refresh.ts` (HMR nạp lại,
 * hai bundle, hoặc một package bị nhân bản trong node_modules) vẫn ra CÙNG một
 * symbol — điều `instanceof` không làm được vì nó so danh tính class.
 *
 * Không mở rộng ra worker hay tab khác: chúng là agent riêng, registry riêng.
 * Không sao — `RefreshFailure` không bao giờ đi qua ranh giới đó; thứ dùng
 * chung giữa các tab là NHẬT KÝ, và nó được validate riêng ở `storage.ts`.
 *
 * Và khác một chuỗi `name`, symbol này không thể bị một object bịa ra vô tình
 * mang theo: muốn có nó thì phải chủ động tra registry.
 */
const REFRESH_FAILURE_BRAND = Symbol.for("qlts.refresh-failure");

export class RefreshFailure extends Error {
  readonly [REFRESH_FAILURE_BRAND] = true;

  constructor(readonly outcome: Exclude<RefreshOutcome, { kind: "success" }>) {
    super(`Làm mới phiên không thành công: ${outcome.kind}`);
    this.name = "RefreshFailure";
  }
}

const FAILURE_KINDS = new Set([
  "terminal",
  "safe-retryable",
  "nonterminal-stop",
  "ambiguous",
]);

const AMBIGUOUS_REASONS = new Set([
  "no-store",
  "write-failed",
  "network",
  "server",
  "no-proof",
  "stale-attempt",
  "wait-timeout",
]);

function isValidOutcome(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const outcome = value as { kind?: unknown; [k: string]: unknown };

  // `success` cố ý KHÔNG nằm trong danh sách: `RefreshFailure` chỉ mang thất
  // bại. Một `outcome.kind === "success"` là dấu hiệu dữ liệu bịa hoặc lỗi
  // dựng, không phải trạng thái hợp lệ.
  if (typeof outcome.kind !== "string" || !FAILURE_KINDS.has(outcome.kind)) {
    return false;
  }

  if (outcome.kind === "safe-retryable") {
    return typeof outcome.retryAt === "number" && Number.isFinite(outcome.retryAt);
  }

  if (outcome.kind === "ambiguous") {
    return typeof outcome.reason === "string" && AMBIGUOUS_REASONS.has(outcome.reason);
  }

  // terminal / nonterminal-stop: hai trường tuỳ chọn, nhưng nếu có thì phải
  // đúng kiểu — `status` sai kiểu sẽ làm caller so sánh sai ở nhánh dưới.
  const statusOk =
    outcome.status === undefined ||
    (typeof outcome.status === "number" && Number.isFinite(outcome.status));
  const codeOk =
    outcome.errorCode === undefined || typeof outcome.errorCode === "string";
  return statusOk && codeOk;
}

/**
 * Nhận diện bằng BRAND + validator, không dùng `instanceof` và cũng không tin
 * mỗi cái tên.
 *
 * Hàm này gác cửa `shouldClearAuthCookies`, tức gác quyết định XOÁ cookie phiên
 * 30 ngày. Nhận diện lỏng ở đây nghĩa là bất kỳ object nào tình cờ mang
 * `name: "RefreshFailure"` — một lỗi từ thư viện khác, một payload dựng lại từ
 * JSON — cũng đủ để xoá phiên của người dùng.
 */
export function isRefreshFailure(error: unknown): error is RefreshFailure {
  if (!error || typeof error !== "object") return false;
  if ((error as Record<symbol, unknown>)[REFRESH_FAILURE_BRAND] !== true) {
    return false;
  }
  return isValidOutcome((error as { outcome?: unknown }).outcome);
}

/**
 * Có được XOÁ cookie phiên sau lỗi này không?
 *
 * Classifier DUY NHẤT của toàn bộ ứng dụng — interceptor 401, CSRF-recovery và
 * bootstrap đều hỏi hàm này.
 *
 * Nguyên tắc **fail-preserve**: chỉ xoá khi có bằng chứng dương rằng phiên đã
 * chết. Một `403` từ WAF, một `404` vì sai `NEXT_PUBLIC_API_URL`, một `422` do
 * validation mới thêm — không cái nào chứng minh refresh token hết hiệu lực,
 * mà xoá cookie thì mất luôn phiên 30 ngày của người dùng.
 */
export function shouldClearAuthCookies(error: unknown): boolean {
  if (isRefreshFailure(error)) return error.outcome.kind === "terminal";

  const response = axios.isAxiosError(error) ? error.response : undefined;
  if (!response) return false;

  const code = (response.data as { error_code?: string } | undefined)?.error_code;
  if (code && TERMINAL_ERROR_CODES.has(code)) return true;
  return response.status === 401;
}

/** Cờ để `useAuth` biết interceptor đã CỐ Ý giữ phiên sau một lỗi tạm thời. */
const SESSION_KEPT_ALIVE = "__qltsSessionKeptAlive";

export function markSessionKeptAlive<T>(error: T): T {
  if (error && typeof error === "object") {
    (error as Record<string, unknown>)[SESSION_KEPT_ALIVE] = true;
  }
  return error;
}

export function isSessionKeptAliveError(error: unknown): boolean {
  return (
    !!error &&
    typeof error === "object" &&
    (error as Record<string, unknown>)[SESSION_KEPT_ALIVE] === true
  );
}

// ---------------------------------------------------------------------------
// Bằng chứng "đã có token mới"
// ---------------------------------------------------------------------------

/**
 * Dấu vân tay của thế hệ phiên hiện tại.
 *
 * Backend sinh `csrf_token` MỚI ở mỗi lần login/refresh thành công
 * (`middleware/csrf.py`), nên giá trị này đổi là bằng chứng có token mới.
 * `null` nghĩa là không đọc được — "không biết", không phải "chưa đổi".
 */
function currentGeneration(): string | null {
  const token = getCSRFToken();
  return token ? token.slice(0, 16) : null;
}

function cooldownFromError(error: unknown): number {
  const headers = axios.isAxiosError(error) ? error.response?.headers : undefined;
  const retryAfter = headers?.["retry-after"] ?? headers?.["Retry-After"];
  const seconds = Number(retryAfter);
  if (Number.isFinite(seconds) && seconds > 0) {
    return Math.min(seconds * 1000, MAX_COOLDOWN_MS);
  }
  return DEFAULT_COOLDOWN_MS;
}

/**
 * Phân loại một lần POST đã hoàn tất.
 *
 * Câu hỏi xuyên suốt: *lần thử này có thể đã chạm rotation ở server chưa?*
 * Chạm rồi mà thử lại nghĩa là trình lại một token server có thể đã vô hiệu
 * hoá — đúng hành vi bị tính là reuse.
 */
function classify(
  error: unknown,
  now: number,
): Exclude<RefreshOutcome, { kind: "success" }> {
  if (!axios.isAxiosError(error)) {
    return { kind: "ambiguous", reason: "network" };
  }

  const response = error.response;
  // Không có response: mạng đứt, timeout, CORS. Request CÓ THỂ đã tới server
  // và rotate xong rồi mất đường về — không được coi là an toàn để thử lại.
  if (!response) return { kind: "ambiguous", reason: "network" };

  const status = response.status;
  const errorCode = (response.data as { error_code?: string } | undefined)
    ?.error_code;

  if (status === 401 || (errorCode && TERMINAL_ERROR_CODES.has(errorCode))) {
    return { kind: "terminal", status, errorCode };
  }

  // Chỉ 429 RATE_LIMITED mới an toàn để thử lại: slowapi chặn ở decorator,
  // TRƯỚC khi thân hàm chạy, nên chắc chắn chưa chạm rotation. Một 429 của
  // cổng chống lạm dụng M4 thì ngược lại — phiên đã bị thu hồi.
  if (status === 429 && errorCode === TRANSIENT_RATE_LIMIT_CODE) {
    return { kind: "safe-retryable", retryAt: now + cooldownFromError(error) };
  }

  // 5xx: server hỏng giữa chừng. Có thể đã commit rotation rồi mới lỗi.
  if (status >= 500) return { kind: "ambiguous", reason: "server" };

  // Phần còn lại (400, 403 mã lạ, 404, 422, 429 mã lạ): không tự phục hồi
  // được, nhưng cũng KHÔNG chứng minh phiên đã chết ⇒ giữ cookie.
  return { kind: "nonterminal-stop", status, errorCode };
}

/** Bản ghi của tab khác nói gì? Đọc thẳng, không đoán lại từ status. */
function outcomeFromRecord(
  record: JournalRecord,
  now: number,
): Exclude<RefreshOutcome, { kind: "success" }> | { kind: "success" } | null {
  const kind: ResultKind | undefined = record.resultKind;
  if (!kind) return null;

  switch (kind) {
    case "success":
      return { kind: "success" };
    case "terminal":
      return { kind: "terminal", status: record.status, errorCode: record.errorCode };
    case "safe-retryable":
      return { kind: "safe-retryable", retryAt: record.retryAt ?? now };
    case "nonterminal-stop":
      return {
        kind: "nonterminal-stop",
        status: record.status,
        errorCode: record.errorCode,
      };
    case "ambiguous":
      return { kind: "ambiguous", reason: "stale-attempt" };
  }
}

// ---------------------------------------------------------------------------
// Luồng chính
// ---------------------------------------------------------------------------

/** Gộp các lời gọi ĐỒNG THỜI trong CÙNG một tab. Liên-tab do lớp khoá lo. */
let inflight: Promise<void> | null = null;

function fail(outcome: Exclude<RefreshOutcome, { kind: "success" }>): never {
  throw new RefreshFailure(outcome);
}

async function runAsLeader(handle: LockHandle, baseline: string | null) {
  // Ghi `in-flight` NGAY TRƯỚC khi chạm mạng. Không ghi bền được thì không
  // POST: nếu tab này chết giữa lúc request bay, sẽ không ai biết đã có một
  // lần thử, và tab kế tiếp POST đè lên một rotation có thể đã xảy ra.
  try {
    await handle.update({ phase: "in-flight" });
  } catch {
    await handle.release().catch(() => undefined);
    fail({ kind: "ambiguous", reason: "write-failed" });
  }

  // Nhịp tim: mỗi lần ghi là bằng chứng tab còn sống, để tab khác không cướp
  // lease của một request đang bay bình thường.
  const heartbeat = setInterval(() => {
    void handle.update({}).catch(() => undefined);
  }, HEARTBEAT_MS);

  let outcome: RefreshOutcome;
  try {
    await axios.post(
      `${env.NEXT_PUBLIC_API_URL}${API_ENDPOINTS.AUTH.REFRESH}`,
      {},
      { withCredentials: true },
    );
    // Chờ trình duyệt áp cookie mới rồi mới đọc bằng chứng.
    await new Promise((r) => setTimeout(r, COOKIE_PERSIST_MS));

    const after = currentGeneration();
    // `200` KHÔNG đủ. Một proxy hoặc service worker có thể trả 200 mà không có
    // cookie mới; và nếu không đọc được CSRF thì ta không biết gì cả.
    outcome =
      after !== null && after !== baseline
        ? { kind: "success" }
        : { kind: "ambiguous", reason: "no-proof" };
  } catch (error) {
    outcome = classify(error, Date.now());
  }

  const record: Partial<JournalRecord> = {
    resultKind: outcome.kind,
    ...(outcome.kind === "terminal" || outcome.kind === "nonterminal-stop"
      ? { status: outcome.status, errorCode: outcome.errorCode }
      : {}),
    ...(outcome.kind === "safe-retryable"
      ? { status: 429, errorCode: TRANSIENT_RATE_LIMIT_CODE, retryAt: outcome.retryAt }
      : {}),
  };

  let writeFailed = false;
  try {
    await handle.update(record);
  } catch {
    // Đã POST rồi mà không ghi được kết quả ⇒ không ai biết chuyện gì đã xảy
    // ra. Fail-closed: coi như mơ hồ, không tab nào được thử lại.
    writeFailed = true;
  } finally {
    clearInterval(heartbeat);
    await handle.release().catch(() => undefined);
  }

  if (writeFailed) fail({ kind: "ambiguous", reason: "write-failed" });
  if (outcome.kind !== "success") fail(outcome);
}

/**
 * Chờ tab đang giữ lease ghi xong kết quả, rồi ĐỌC kết quả đó.
 *
 * Tuyệt đối không POST. Và hết giờ chờ cũng KHÔNG biến thành thử lại — hết giờ
 * nghĩa là ta không biết tab kia tới đâu, tức đúng định nghĩa của mơ hồ.
 */
async function followOtherTab(leaderGeneration: string | null): Promise<void> {
  const store = await selectJournalStore();
  if (!store) fail({ kind: "ambiguous", reason: "no-store" });

  const deadline = Date.now() + FOLLOWER_WAIT_MS;
  while (Date.now() < deadline) {
    // Bằng chứng ở COOKIE thắng bằng chứng ở nhật ký, và phải kiểm TRƯỚC khi
    // đọc nhật ký. Leader có thể rotate xong rồi bị đóng tab trước khi kịp ghi
    // `resultKind`; khi đó nhật ký im lặng nhưng `csrf_token` đã mang thế hệ
    // mới. Không nhìn cookie thì ta chờ hết 15 giây rồi báo mơ hồ cho một lần
    // refresh đã thành công.
    //
    // Mốc so sánh là `leaderGeneration` — thế hệ của bản ghi lúc ta nhận `busy`
    // — chứ KHÔNG phải `record.generationBefore` đọc lại mỗi vòng. Nếu tab khác
    // xoá nhật ký giữa chừng thì ta mất luôn mốc và lại ngồi chờ hết giờ.
    const generation = currentGeneration();
    if (generation !== null && generation !== leaderGeneration) return;

    let record: JournalRecord | null;
    try {
      record = await store.read();
    } catch {
      fail({ kind: "ambiguous", reason: "no-store" });
    }

    if (record) {
      const outcome = outcomeFromRecord(record, Date.now());
      if (outcome) {
        if (outcome.kind === "success") return;
        fail(outcome);
      }
    }
    await new Promise((r) => setTimeout(r, FOLLOWER_POLL_MS));
  }

  fail({ kind: "ambiguous", reason: "wait-timeout" });
}

async function doRefresh(): Promise<void> {
  const baseline = currentGeneration();

  // Nếu phiên đã sang thế hệ mới thì nhật ký cũ hết ý nghĩa. Chỉ xoá khi có
  // bằng chứng dương — `null` không phải bằng chứng (xem `lifecycle.ts`).
  const superseded = await supersedeIfGenerationChanged(baseline);
  if (superseded.status === "failed") {
    fail({ kind: "ambiguous", reason: "no-store" });
  }

  // 🔴 `cleared` mang HAI nghĩa, và gộp chúng lại là một lỗi im lặng rất đắt.
  //
  //  (a) Bản ghi VỪA được viết vài giây trước ⇒ một tab khác vừa refresh xong,
  //      token mới còn nguyên. POST thêm là trình lại một refresh token vừa bị
  //      rotate — đúng hành vi server tính là reuse, và tới lần thứ năm thì
  //      `auth.py` thu hồi toàn bộ phiên.
  //
  //  (b) Bản ghi còn sót từ chu kỳ TRƯỚC (13 phút trước, khi hook proactive
  //      chạy lần cuối) ⇒ access token của chu kỳ đó sắp hết hạn. Coi nó là
  //      bằng chứng thì lần refresh này thành no-op: hook đã ghi timestamp
  //      throttle TRƯỚC khi gọi, nên lần thử kế tiếp mãi tới phút ~26, trong
  //      khi token chết ở phút 15. Người dùng gặp lại đúng triệu chứng mà cả
  //      kế hoạch này sinh ra để chữa.
  //
  // Phân biệt bằng TUỔI: "generation đã đổi" chỉ chứng minh có token mới TẠI
  // THỜI ĐIỂM bản ghi được viết, không chứng minh token ấy còn hạn bây giờ.
  //
  // ⚠️ Và tuổi phải bị chặn ở CẢ HAI phía. `clearedAt` là `updatedAt` do TAB
  // KHÁC ghi, tức đọc từ một đồng hồ khác; người dùng cũng có thể chỉnh giờ lùi
  // giữa hai chu kỳ. Tuổi âm nghĩa là bản ghi "đến từ tương lai" — nó không nói
  // được gì về việc token nó chứng minh còn hạn hay không. Bỏ vế dưới thì mọi
  // bản ghi lệch giờ về phía tương lai đều lọt qua như bằng chứng tươi, và ta
  // rơi lại đúng ca (b): no-op, throttle đã ghi, token chết ở phút 15.
  if (superseded.status === "cleared") {
    const proofAge = Date.now() - superseded.clearedAt;
    if (proofAge >= 0 && proofAge <= FRESH_PROOF_WINDOW_MS) {
      return;
    }
  }

  const acquired = await acquireRefreshLock(baseline);

  switch (acquired.status) {
    case "acquired":
      return runAsLeader(acquired.handle, baseline);

    case "busy":
      return followOtherTab(acquired.record.generationBefore);

    case "blocked": {
      if (acquired.reason === "cooldown") {
        fail({
          kind: "safe-retryable",
          retryAt: acquired.record.retryAt ?? Date.now(),
        });
      }
      if (acquired.reason === "stale-in-flight") {
        fail({ kind: "ambiguous", reason: "stale-attempt" });
      }
      const outcome = outcomeFromRecord(acquired.record, Date.now());
      if (outcome && outcome.kind !== "success") fail(outcome);
      // `success` đã ghi ⇒ token mới có rồi, không cần làm gì thêm.
      return;
    }

    case "unavailable":
      // Không ghi bền được ⇒ không được POST. Xem ma trận trong `storage.ts`.
      fail({ kind: "ambiguous", reason: "no-store" });
  }
}

/**
 * Làm mới access token.
 *
 * Ném `RefreshFailure` mang `outcome` đã phân loại — caller đọc thẳng, không
 * đoán lại từ `status`.
 */
export function refreshAccessToken(): Promise<void> {
  if (inflight) return inflight;
  inflight = doRefresh().finally(() => {
    inflight = null;
  });
  return inflight;
}

/** Dọn nhật ký sau một lối thoát đã hoàn tất. Xem `ClearTrigger`. */
export async function noteSessionTransition(
  trigger: ClearTrigger,
): Promise<void> {
  await clearJournalAfter(trigger);
}
