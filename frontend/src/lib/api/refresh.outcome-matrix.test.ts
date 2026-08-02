// src/lib/api/refresh.outcome-matrix.test.ts
/**
 * Toàn bộ ma trận kết quả của một lần POST, và dọn dẹp trên MỌI lối ra.
 *
 * Câu hỏi phân loại luôn là một: *lần thử này có thể đã chạm rotation ở server
 * chưa?* Chỉ `429 RATE_LIMITED` là chắc chắn chưa (slowapi chặn ở decorator,
 * trước khi thân hàm chạy), nên nó là loại DUY NHẤT được thử lại.
 *
 * Phần dọn dẹp quan trọng ngang phần phân loại: một nhịp tim còn chạy hoặc một
 * Web Lock chưa nhả sẽ khiến tab kế tiếp thấy "bận" vĩnh viễn — hỏng theo kiểu
 * im lặng, không lỗi nào nổ ra.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import {
  installFakeIdb,
  installWebLocks,
  removeWebLocks,
} from "./refresh-coordination/test-harness";
import { selectJournalStore } from "./refresh-coordination/storage";

const post = vi.hoisted(() => vi.fn());

vi.mock("axios", async (importActual) => {
  const actual = await importActual<typeof import("axios")>();
  return {
    ...actual,
    default: { ...actual.default, post, isAxiosError: actual.default.isAxiosError },
  };
});

function setCsrf(value: string | null) {
  if (value === null) {
    document.cookie = "csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
    return;
  }
  document.cookie = `csrf_token=${value}; path=/`;
}

function axiosError(status: number, data: unknown = {}, headers: Record<string, string> = {}) {
  const error = new Error(`HTTP ${status}`) as Error & {
    isAxiosError: true;
    response: { status: number; data: unknown; headers: Record<string, string> };
  };
  error.isAxiosError = true;
  error.response = { status, data, headers };
  return error;
}

/** Lỗi mạng: KHÔNG có `response` — request có thể đã tới server rồi mất đường về. */
function networkError() {
  const error = new Error("Network Error") as Error & { isAxiosError: true };
  error.isAxiosError = true;
  return error;
}

async function loadFresh() {
  vi.resetModules();
  return import("./refresh");
}

async function readJournal() {
  const store = await selectJournalStore();
  return store!.read();
}

beforeEach(() => {
  post.mockReset();
  window.localStorage.clear();
  installFakeIdb();
  removeWebLocks();
  setCsrf("gen-old");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ma trận kết quả", () => {
  it("200 + CSRF ĐỔI ⇒ success", async () => {
    post.mockImplementation(async () => {
      setCsrf("gen-new");
      return { status: 200, data: {} };
    });
    const { refreshAccessToken } = await loadFresh();

    await expect(refreshAccessToken()).resolves.toBeUndefined();
    expect((await readJournal())?.resultKind).toBe("success");
  });

  it("200 nhưng CSRF KHÔNG đổi ⇒ ambiguous/no-proof", async () => {
    // Một proxy hoặc service worker có thể trả 200 mà chẳng có cookie mới nào.
    post.mockResolvedValue({ status: 200, data: {} });
    const { refreshAccessToken, isRefreshFailure } = await loadFresh();

    const error = await refreshAccessToken().catch((e) => e);

    expect(isRefreshFailure(error)).toBe(true);
    expect(error.outcome).toEqual({ kind: "ambiguous", reason: "no-proof" });
  });

  it("200 nhưng KHÔNG đọc được CSRF ⇒ ambiguous/no-proof", async () => {
    post.mockImplementation(async () => {
      setCsrf(null); // không biết gì cả — không phải bằng chứng
      return { status: 200, data: {} };
    });
    const { refreshAccessToken, isRefreshFailure } = await loadFresh();

    const error = await refreshAccessToken().catch((e) => e);

    expect(isRefreshFailure(error)).toBe(true);
    expect(error.outcome.kind).toBe("ambiguous");
  });

  it("401 ⇒ terminal, và ĐƯỢC phép xoá cookie", async () => {
    post.mockRejectedValue(axiosError(401));
    const { refreshAccessToken, shouldClearAuthCookies } = await loadFresh();

    const error = await refreshAccessToken().catch((e) => e);

    expect(error.outcome.kind).toBe("terminal");
    expect(shouldClearAuthCookies(error)).toBe(true);
  });

  it("429 REFRESH_ABUSE_LOCKED ⇒ terminal (phiên đã bị thu hồi phía server)", async () => {
    post.mockRejectedValue(
      axiosError(429, { error_code: "REFRESH_ABUSE_LOCKED" }),
    );
    const { refreshAccessToken, shouldClearAuthCookies } = await loadFresh();

    const error = await refreshAccessToken().catch((e) => e);

    expect(error.outcome.kind).toBe("terminal");
    expect(shouldClearAuthCookies(error)).toBe(true);
  });

  it("429 RATE_LIMITED ⇒ safe-retryable kèm retryAt, và GIỮ cookie", async () => {
    post.mockRejectedValue(
      axiosError(429, { error_code: "RATE_LIMITED" }, { "retry-after": "30" }),
    );
    const { refreshAccessToken, shouldClearAuthCookies } = await loadFresh();

    const before = Date.now();
    const error = await refreshAccessToken().catch((e) => e);

    expect(error.outcome.kind).toBe("safe-retryable");
    expect(error.outcome.retryAt).toBeGreaterThanOrEqual(before + 30_000);
    expect(shouldClearAuthCookies(error)).toBe(false);

    // Nhật ký phải ghi đủ để tab khác áp đúng cooldown mà không đoán lại.
    const record = await readJournal();
    expect(record?.resultKind).toBe("safe-retryable");
    expect(record?.status).toBe(429);
    expect(record?.errorCode).toBe("RATE_LIMITED");
    // So THẲNG với outcome, không chỉ "tồn tại và hữu hạn": một hồi quy ghi
    // `retryAt: 0` vẫn qua được phép kiểm lỏng, mà `0` nghĩa là tab khác được
    // POST lại ngay lập tức — đúng thứ cooldown sinh ra để chặn.
    expect(record?.retryAt).toBe(error.outcome.retryAt);
    expect(record?.retryAt).toBeGreaterThanOrEqual(before + 30_000);
  });

  it.each([
    ["400", 400, {}],
    ["403 mã lạ", 403, { error_code: "WAF_BLOCKED" }],
    ["404", 404, {}],
    ["422", 422, {}],
    ["429 mã lạ", 429, { error_code: "SOMETHING_ELSE" }],
  ])("%s ⇒ nonterminal-stop, GIỮ cookie", async (_label, status, data) => {
    post.mockRejectedValue(axiosError(status, data));
    const { refreshAccessToken, shouldClearAuthCookies } = await loadFresh();

    const error = await refreshAccessToken().catch((e) => e);

    expect(error.outcome.kind).toBe("nonterminal-stop");
    // Sai `NEXT_PUBLIC_API_URL` hay một WAF chặn KHÔNG chứng minh phiên chết.
    expect(shouldClearAuthCookies(error)).toBe(false);
  });

  it.each([500, 502, 503])("%i ⇒ ambiguous/server", async (status) => {
    post.mockRejectedValue(axiosError(status));
    const { refreshAccessToken, shouldClearAuthCookies } = await loadFresh();

    const error = await refreshAccessToken().catch((e) => e);

    expect(error.outcome).toEqual({ kind: "ambiguous", reason: "server" });
    expect(shouldClearAuthCookies(error)).toBe(false);
  });

  it("mạng đứt (không có response) ⇒ ambiguous/network", async () => {
    post.mockRejectedValue(networkError());
    const { refreshAccessToken } = await loadFresh();

    const error = await refreshAccessToken().catch((e) => e);

    expect(error.outcome).toEqual({ kind: "ambiguous", reason: "network" });
  });
});

describe("ghi nhật ký quanh POST", () => {
  /**
   * Chạy ở nhánh **Web Locks** có chủ đích: ở đó `acquireRefreshLock` dùng
   * `read`/`write`, nên mọi lần `mutate` đều là lần ghi quanh POST — lần 1 là
   * chuyển sang `in-flight`, lần 2 là ghi kết quả. Ở nhánh lease-IDB thì
   * `acquire` cũng dùng `mutate`, và ta sẽ đếm nhầm.
   *
   * Chặn ở tầng `IDBObjectStore.prototype.put`: `selectJournalStore()` tạo một
   * store MỚI mỗi lần gọi, nên spy lên một instance lấy sẵn sẽ không bao giờ
   * ăn (tôi đã mắc đúng lỗi này).
   */
  async function failPutFrom(nth: number) {
    // `fake-indexeddb` KHÔNG gán các class IDB vào global (chỉ gán
    // `indexedDB`), nên phải lấy prototype từ chính package.
    //
    // `@ts-expect-error`: package có sẵn `.d.ts` cho đường dẫn này nhưng bản đồ
    // `exports` trong `package.json` của nó không phơi ra, nên TS không resolve
    // được. Chỉ ảnh hưởng tệp test.
    // prettier-ignore
    // @ts-expect-error — xem ghi chú trên
    const { default: FDBObjectStore } = await import("fake-indexeddb/lib/FDBObjectStore");
    let calls = 0;
    const realPut = FDBObjectStore.prototype.put;
    vi.spyOn(FDBObjectStore.prototype, "put").mockImplementation(function (
      this: unknown,
      ...args: unknown[]
    ) {
      calls += 1;
      if (calls >= nth) throw new Error("ghi hỏng");
      return (realPut as (...a: unknown[]) => unknown).apply(this, args);
    } as never);
  }

  it("ghi `in-flight` HỎNG trước POST ⇒ KHÔNG POST, Web Lock vẫn nhả", async () => {
    const locks = installWebLocks();
    // Lần `put` thứ nhất là của `acquire` (ghi bản ghi `acquired`) — cho qua.
    // Lần thứ hai mới là chuyển sang `in-flight`, đúng chỗ cần cho hỏng.
    await failPutFrom(2);

    const { refreshAccessToken, isRefreshFailure } = await loadFresh();
    const error = await refreshAccessToken().catch((e) => e);

    // Không ghi bền được nghĩa là nếu tab này chết giữa lúc request bay thì
    // không ai biết đã có một lần thử ⇒ thà đừng thử.
    expect(post).not.toHaveBeenCalled();
    expect(isRefreshFailure(error)).toBe(true);
    expect(error.outcome).toEqual({ kind: "ambiguous", reason: "write-failed" });
    // Lối này thoát TRƯỚC khi nhịp tim được tạo, nên nó nằm ngoài ma trận dọn
    // dẹp bên dưới — phải kiểm riêng, kẻo một Web Lock bị bỏ quên làm mọi tab
    // sau thấy "bận" vĩnh viễn.
    expect(locks.held()).toBe(0);
  });

  it("ghi kết quả HỎNG sau POST ⇒ ambiguous, Web Lock vẫn nhả", async () => {
    const locks = installWebLocks();
    post.mockImplementation(async () => {
      setCsrf("gen-new");
      return { status: 200, data: {} };
    });
    // Lần ghi đầu (`acquired`) và lần thứ hai (`in-flight`) cho qua; lần ghi
    // kết quả thì hỏng.
    await failPutFrom(3);

    const { refreshAccessToken, isRefreshFailure } = await loadFresh();
    const error = await refreshAccessToken().catch((e) => e);

    // Đã POST rồi mà không ghi được kết quả ⇒ không ai biết chuyện gì đã xảy ra.
    expect(post).toHaveBeenCalledTimes(1);
    expect(isRefreshFailure(error)).toBe(true);
    expect(error.outcome).toEqual({ kind: "ambiguous", reason: "write-failed" });
    expect(locks.held()).toBe(0);
  });
});

describe("dọn dẹp trên MỌI lối ra", () => {
  it.each([
    ["success", async () => post.mockImplementation(async () => {
      setCsrf("gen-new");
      return { status: 200, data: {} };
    })],
    ["terminal", async () => post.mockRejectedValue(axiosError(401))],
    ["ambiguous", async () => post.mockRejectedValue(axiosError(503))],
    ["nonterminal-stop", async () => post.mockRejectedValue(axiosError(404))],
    [
      "safe-retryable",
      async () =>
        post.mockRejectedValue(axiosError(429, { error_code: "RATE_LIMITED" })),
    ],
  ])("%s ⇒ nhịp tim dừng và Web Lock được nhả", async (_label, arrange) => {
    const locks = installWebLocks();
    await arrange();

    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    const clearIntervalSpy = vi.spyOn(globalThis, "clearInterval");
    const { refreshAccessToken } = await loadFresh();

    await refreshAccessToken().catch(() => undefined);

    // Nhịp tim còn chạy sẽ tiếp tục gia hạn lease của một attempt đã xong,
    // khiến tab khác thấy "bận" mãi.
    //
    // Kiểm ĐÚNG handle chứ không chỉ "đã gọi `clearInterval`": dừng nhầm một
    // timer khác cũng làm phép kiểm lỏng kia xanh, trong khi nhịp tim thật vẫn
    // đang chạy.
    expect(setIntervalSpy).toHaveBeenCalledTimes(1);
    const heartbeatHandle = setIntervalSpy.mock.results[0]?.value;
    expect(clearIntervalSpy).toHaveBeenCalledWith(heartbeatHandle);
    expect(locks.held()).toBe(0);
  });
});
