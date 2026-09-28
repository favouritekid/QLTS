// src/lib/api/refresh.cross-tab.test.ts
/**
 * Khoá liên-tab: hai tab cùng làm mới phiên ⇒ **đúng một** POST.
 *
 * ⚠️ Phải dùng HAI module context (`vi.resetModules()`), không phải hai lời
 * gọi trong cùng module. `refresh.ts` có `inflight` gộp các lời gọi đồng thời
 * **trong một tab**; gọi hai lần cùng module thì `inflight` một mình đã cho ra
 * một POST, và test sẽ xanh kể cả khi khoá liên-tab hỏng hoàn toàn.
 *
 * Hai instance dùng chung mọi thứ mà hai tab thật dùng chung — cookie,
 * IndexedDB, Web Locks, và cùng một spy `axios.post` — chỉ khác nhau ở state
 * nội module.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import {
  installFakeIdb,
  installWebLocks,
  removeWebLocks,
} from "./refresh-coordination/test-harness";

const post = vi.hoisted(() => vi.fn());

vi.mock("axios", async (importActual) => {
  const actual = await importActual<typeof import("axios")>();
  return {
    ...actual,
    default: {
      ...actual.default,
      post,
      isAxiosError: actual.default.isAxiosError,
    },
  };
});

function setCsrf(value: string | null) {
  if (value === null) {
    document.cookie = "csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
    return;
  }
  document.cookie = `csrf_token=${value}; path=/`;
}

/**
 * Hai bản `refresh.ts` độc lập — mô phỏng hai tab.
 *
 * `resetModules()` giữa hai lần import là điểm mấu chốt: không có nó thì
 * `import` thứ hai trả lại đúng instance cũ, và cả bài test mất ý nghĩa.
 */
async function loadTwoTabs() {
  vi.resetModules();
  const tabA = await import("./refresh");
  vi.resetModules();
  const tabB = await import("./refresh");
  // Nếu hai lần import trả cùng một object thì `inflight` dùng chung, và test
  // dưới đây sẽ xanh vì lý do sai.
  expect(tabA).not.toBe(tabB);
  return { tabA, tabB };
}

beforeEach(() => {
  post.mockReset();
  window.localStorage.clear();
  installFakeIdb();
  setCsrf("gen-old");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe.each([
  ["nhánh lease-IDB (không Web Locks)", () => removeWebLocks()],
  ["nhánh Web Locks", () => installWebLocks()],
])("%s", (_label, setupLocks) => {
  beforeEach(() => setupLocks());

  it("hai tab cùng làm mới ⇒ ĐÚNG MỘT POST", async () => {
    post.mockImplementation(async () => {
      // Server rotate xong: cookie mang thế hệ mới. Đây là bằng chứng mà tab
      // còn lại sẽ đọc được thay vì tự POST.
      setCsrf("gen-new");
      return { status: 200, data: {} };
    });

    const { tabA, tabB } = await loadTwoTabs();

    const results = await Promise.allSettled([
      tabA.refreshAccessToken(),
      tabB.refreshAccessToken(),
    ]);

    expect(post).toHaveBeenCalledTimes(1);
    // Tab thua cuộc cũng phải coi là thành công — token mới đã có rồi.
    expect(results.map((r) => r.status)).toEqual(["fulfilled", "fulfilled"]);
  }, 9_000);

  it("tab gọi SAU khi tab kia đã xong ⇒ không POST thêm", async () => {
    post.mockImplementation(async () => {
      setCsrf("gen-new");
      return { status: 200, data: {} };
    });

    const { tabA, tabB } = await loadTwoTabs();

    await tabA.refreshAccessToken();
    expect(post).toHaveBeenCalledTimes(1);

    await expect(tabB.refreshAccessToken()).resolves.toBeUndefined();
    expect(post).toHaveBeenCalledTimes(1);
  }, 9_000);
});

describe("kết quả terminal lan sang tab kia mà không cần POST lại", () => {
  beforeEach(() => removeWebLocks());

  it("leader nhận 401 ⇒ follower cũng terminal, chỉ một POST", async () => {
    const axios = (await import("axios")).default;
    post.mockImplementation(async () => {
      const error = new Error("unauthorized") as Error & {
        isAxiosError: true;
        response: { status: number; data: unknown; headers: Record<string, string> };
      };
      error.isAxiosError = true;
      error.response = { status: 401, data: {}, headers: {} };
      throw error;
    });
    expect(typeof axios.isAxiosError).toBe("function");

    const { tabA, tabB } = await loadTwoTabs();

    const [a, b] = await Promise.allSettled([
      tabA.refreshAccessToken(),
      tabB.refreshAccessToken(),
    ]);

    expect(post).toHaveBeenCalledTimes(1);
    expect(a.status).toBe("rejected");
    expect(b.status).toBe("rejected");

    // Cả hai tab phải đi tới cùng một kết luận, và kết luận đó đến từ bản ghi
    // dùng chung chứ không phải từ việc mỗi tab tự đoán lại.
    for (const result of [a, b]) {
      if (result.status !== "rejected") continue;
      expect(tabA.shouldClearAuthCookies(result.reason)).toBe(true);
    }
  }, 9_000);
});


/**
 * `503 AUTH_STATE_UNAVAILABLE` giữa nhiều tab: nhật ký dùng chung là thứ DUY
 * NHẤT cho phép tab khác biết "chưa được thử lại trước `retryAt`".
 *
 * Chỉ giả lập `Date` (không giả `setTimeout`): IndexedDB giả và vòng chờ của
 * tab theo sau cần vòng lặp sự kiện thật — xem `refresh.proof-freshness.test.ts`.
 */
describe.each([
  ["nhánh lease-IDB (không Web Locks)", () => removeWebLocks()],
  ["nhánh Web Locks", () => installWebLocks()],
])("503 AUTH_STATE_UNAVAILABLE — %s", (_label, setupLocks) => {
  const T0 = 1_800_000_000_000;
  const RETRY_AFTER_S = 30;

  function stateUnavailable() {
    const error = new Error("service unavailable") as Error & {
      isAxiosError: true;
      response: { status: number; data: unknown; headers: Record<string, string> };
    };
    error.isAxiosError = true;
    error.response = {
      status: 503,
      data: { detail: "x", error_code: "AUTH_STATE_UNAVAILABLE" },
      headers: { "retry-after": String(RETRY_AFTER_S) },
    };
    return error;
  }

  beforeEach(() => {
    setupLocks();
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(T0);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("tab khác KHÔNG POST trước retryAt; sau retryAt đúng MỘT POST; không tab nào bị xoá phiên", async () => {
    post.mockRejectedValue(stateUnavailable());
    const { tabA, tabB } = await loadTwoTabs();

    // 1. Tab A là leader, nhận 503 + mã.
    const a0 = await tabA.refreshAccessToken().catch((e) => e);
    expect(post).toHaveBeenCalledTimes(1);
    expect(a0.outcome).toMatchObject({ kind: "safe-retryable", retryAt: T0 + 30_000 });

    const { selectJournalStore } = await import("./refresh-coordination/storage");
    const record = await (await selectJournalStore())!.read();
    expect(record).toMatchObject({
      resultKind: "safe-retryable",
      status: 503,
      errorCode: "AUTH_STATE_UNAVAILABLE",
      retryAt: T0 + 30_000,
    });

    // 2. Ngay lúc đó (lease còn hạn) và sau khi lease hết nhưng chưa tới
    //    retryAt: cả hai tab đọc nhật ký, KHÔNG POST.
    for (const at of [T0, T0 + 25_000, T0 + 29_999]) {
      vi.setSystemTime(at);
      const [a, b] = await Promise.all([
        tabA.refreshAccessToken().catch((e) => e),
        tabB.refreshAccessToken().catch((e) => e),
      ]);
      for (const failure of [a, b]) {
        expect(failure.outcome).toMatchObject({ kind: "safe-retryable", retryAt: T0 + 30_000 });
        expect(tabA.shouldClearAuthCookies(failure)).toBe(false);
      }
      expect(post).toHaveBeenCalledTimes(1);
    }
    // Cookie phiên còn nguyên suốt quãng chờ.
    expect(document.cookie).toContain("csrf_token=gen-old");

    // 3. Tới retryAt: Redis đã hồi, server rotate xong. Hai tab cùng thử ⇒
    //    ĐÚNG MỘT POST mới.
    vi.setSystemTime(T0 + 30_000);
    post.mockReset();
    post.mockImplementation(async () => {
      setCsrf("gen-new");
      return { status: 200, data: {} };
    });
    const results = await Promise.allSettled([
      tabA.refreshAccessToken(),
      tabB.refreshAccessToken(),
    ]);

    expect(post).toHaveBeenCalledTimes(1);
    // Ít nhất leader thành công; tab kia hoặc thấy bằng chứng mới, hoặc đọc
    // trúng bản ghi cũ và dừng ở safe-retryable — KHÔNG BAO GIỜ terminal hay
    // tự POST thêm.
    expect(results.some((r) => r.status === "fulfilled")).toBe(true);
    for (const r of results) {
      if (r.status === "rejected") {
        expect(r.reason.outcome.kind).toBe("safe-retryable");
      }
    }

    // 4. Gọi lại ngay sau đó: token mới vừa có ⇒ không POST nữa.
    await expect(tabB.refreshAccessToken()).resolves.toBeUndefined();
    expect(post).toHaveBeenCalledTimes(1);
  }, 15_000);

  it("503 KHÔNG mã ⇒ ambiguous; không tab nào POST lại, kể cả 10 phút sau", async () => {
    const noCode = stateUnavailable();
    noCode.response.data = "<html>503 Service Temporarily Unavailable</html>";
    post.mockRejectedValue(noCode);
    const { tabA, tabB } = await loadTwoTabs();

    const a0 = await tabA.refreshAccessToken().catch((e) => e);
    expect(a0.outcome).toEqual({ kind: "ambiguous", reason: "server" });

    for (const at of [T0 + 31_000, T0 + 10 * 60_000]) {
      vi.setSystemTime(at);
      const [a, b] = await Promise.all([
        tabA.refreshAccessToken().catch((e) => e),
        tabB.refreshAccessToken().catch((e) => e),
      ]);
      for (const failure of [a, b]) {
        expect(failure.outcome.kind).toBe("ambiguous");
        expect(tabA.shouldClearAuthCookies(failure)).toBe(false);
      }
    }
    expect(post).toHaveBeenCalledTimes(1);
  }, 15_000);
});
