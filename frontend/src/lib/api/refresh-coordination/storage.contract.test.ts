// src/lib/api/refresh-coordination/storage.contract.test.ts
/**
 * Contract của lớp kho: **mọi đường thất bại đều phải fail-closed**.
 *
 * Lớp này chỉ có một việc — trả lời "đã có ai đang thử refresh chưa". Trả lời
 * sai theo hướng "chưa có ai" là cấp phép POST, và một POST thừa lên
 * `/auth/refresh` có thể làm server tính thêm một lần hỏng, tiến gần tới ngưỡng
 * thu hồi toàn bộ phiên. Nên ở đây "không biết" phải luôn quy về "đừng POST",
 * không bao giờ về "cứ POST".
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import { acquireRefreshLock, LEASE_TTL_MS } from "./lock";
import { selectJournalStore, CorruptJournalError } from "./storage";
import {
  installFakeIdb,
  removeIdb,
  installWebLocks,
  removeWebLocks,
} from "./test-harness";

const T0 = 1_800_000_000_000;
const LOCAL_KEY = "qlts_refresh_journal";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(T0);
  window.localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
});

function validRecord(overrides: Record<string, unknown> = {}) {
  return {
    attemptId: "a-1",
    owner: "o-1",
    phase: "in-flight",
    generationBefore: "gen-1",
    until: T0 + LEASE_TTL_MS,
    updatedAt: T0,
    ...overrides,
  };
}

describe("ma trận storage — bốn ô", () => {
  it("Web Locks + IndexedDB ⇒ dùng IndexedDB", async () => {
    installWebLocks();
    installFakeIdb();

    const store = await selectJournalStore();

    expect(store?.kind).toBe("idb");
  });

  it("Web Locks, KHÔNG IndexedDB ⇒ dùng localStorage", async () => {
    installWebLocks();
    removeIdb();

    const store = await selectJournalStore();

    expect(store?.kind).toBe("localStorage");
  });

  it("KHÔNG Web Locks, có IndexedDB ⇒ dùng IndexedDB (lease nằm trong giao dịch)", async () => {
    removeWebLocks();
    installFakeIdb();

    const store = await selectJournalStore();

    expect(store?.kind).toBe("idb");
  });

  it("KHÔNG cả hai ⇒ fail-closed, không có kho", async () => {
    removeWebLocks();
    removeIdb();

    expect(await selectJournalStore()).toBeNull();

    // Và hệ quả phải thấy được ở tầng trên: không kho ⇒ không được POST.
    expect((await acquireRefreshLock("gen-1", T0)).status).toBe("unavailable");
  });
});

describe("đổi kho không được làm mất trí nhớ", () => {
  it("IndexedDB hỏng ⇒ KHÔNG tụt xuống localStorage trống", async () => {
    installWebLocks();
    // `localStorage` sẵn sàng và TRỐNG — nếu có fallback thì lần đọc kế tiếp
    // sẽ thấy "chưa ai thử" và cấp phép POST.
    window.localStorage.removeItem(LOCAL_KEY);

    // IndexedDB có mặt nhưng `open()` luôn lỗi.
    Object.defineProperty(globalThis, "indexedDB", {
      configurable: true,
      writable: true,
      value: {
        open: () => {
          const request: Record<string, unknown> = { error: new Error("nope") };
          setTimeout(() => {
            (request.onerror as (() => void) | undefined)?.();
          }, 0);
          return request;
        },
      },
    });

    const store = await selectJournalStore();

    // Nhật ký thật có thể đang nằm trong IDB — kể cả một bản ghi cấm mọi tab
    // POST. Nhìn sang kho khác đang trống là xoá lệnh cấm đó.
    expect(store).toBeNull();
    expect((await acquireRefreshLock("gen-1", T0)).status).toBe("unavailable");
  });

  it("bản ghi trong IndexedDB hỏng ⇒ fail-closed, không coi như trống", async () => {
    installWebLocks();
    installFakeIdb();

    // Ghi thẳng một bản ghi rác vào đúng chỗ nhật ký.
    const idbStore = await selectJournalStore();
    expect(idbStore?.kind).toBe("idb");
    await idbStore!.write({ phase: "không-hợp-lệ" } as never);

    // Lần chọn kho kế tiếp phải phát hiện và từ chối, chứ không im lặng dùng
    // `localStorage` hay coi bản ghi rác như "chưa có gì".
    const again = await selectJournalStore();
    expect(again).toBeNull();
    expect((await acquireRefreshLock("gen-1", T0)).status).toBe("unavailable");
  });
});

describe("validator — dữ liệu tồn tại mà không hợp lệ phải fail-closed", () => {
  beforeEach(() => {
    installWebLocks();
    removeIdb(); // ép dùng localStorage để bơm dữ liệu xấu dễ dàng
  });

  async function readWith(raw: string) {
    window.localStorage.setItem(LOCAL_KEY, raw);
    const store = await selectJournalStore();
    return store!.read();
  }

  it("JSON hỏng ⇒ ném, KHÔNG trả null", async () => {
    await expect(readWith("{ không phải json")).rejects.toBeInstanceOf(
      CorruptJournalError,
    );
  });

  it.each([
    ["phase ngoài allowlist", validRecord({ phase: "đang-bay" })],
    ["resultKind ngoài allowlist", validRecord({ resultKind: "có-lẽ-ổn" })],
    ["attemptId rỗng", validRecord({ attemptId: "" })],
    ["owner rỗng", validRecord({ owner: "" })],
    ["until không hữu hạn", validRecord({ until: Number.POSITIVE_INFINITY })],
    ["updatedAt không phải số", validRecord({ updatedAt: "hôm qua" })],
    ["generationBefore sai kiểu", validRecord({ generationBefore: 42 })],
    [
      "safe-retryable thiếu retryAt",
      validRecord({ resultKind: "safe-retryable" }),
    ],
    [
      "safe-retryable retryAt vô hạn",
      validRecord({ resultKind: "safe-retryable", retryAt: Number.NaN }),
    ],
  ])("%s ⇒ ném", async (_label, record) => {
    await expect(readWith(JSON.stringify(record))).rejects.toBeInstanceOf(
      CorruptJournalError,
    );
  });

  // `safe-retryable` là trạng thái DUY NHẤT cấp lại quyền POST, nên nó chịu
  // kiểm chặt nhất — kể cả quan hệ giữa các trường. Cơ sở để coi nó an toàn
  // rất hẹp: slowapi chặn ở decorator nên `429 RATE_LIMITED` chắc chắn chưa
  // chạm rotation. Một `5xx` hay mã 429 khác KHÔNG có bảo đảm đó.
  it.each([
    ["safe-retryable kèm status 500", { status: 500, errorCode: "RATE_LIMITED" }],
    ["safe-retryable thiếu status", { errorCode: "RATE_LIMITED" }],
    ["safe-retryable mã lạ", { status: 429, errorCode: "REFRESH_ABUSE_LOCKED" }],
    ["safe-retryable thiếu errorCode", { status: 429 }],
  ])("%s ⇒ ném", async (_label, extra) => {
    const record = validRecord({
      resultKind: "safe-retryable",
      retryAt: T0 + 60_000,
      ...extra,
    });

    await expect(readWith(JSON.stringify(record))).rejects.toBeInstanceOf(
      CorruptJournalError,
    );
  });

  it("có resultKind nhưng phase=`acquired` ⇒ ném (không thể sinh ra hợp lệ)", async () => {
    const record = validRecord({ phase: "acquired", resultKind: "terminal" });

    await expect(readWith(JSON.stringify(record))).rejects.toBeInstanceOf(
      CorruptJournalError,
    );
  });

  it.each([
    ["until âm", validRecord({ until: -1 })],
    ["updatedAt âm", validRecord({ updatedAt: -5 })],
    [
      "retryAt âm",
      validRecord({
        resultKind: "safe-retryable",
        retryAt: -1,
        status: 429,
        errorCode: "RATE_LIMITED",
      }),
    ],
  ])("%s ⇒ ném", async (_label, record) => {
    await expect(readWith(JSON.stringify(record))).rejects.toBeInstanceOf(
      CorruptJournalError,
    );
  });

  it("không có khoá ⇒ trả null (khác hẳn dữ liệu hỏng)", async () => {
    window.localStorage.removeItem(LOCAL_KEY);
    const store = await selectJournalStore();

    await expect(store!.read()).resolves.toBeNull();
  });

  it("bản ghi hợp lệ đầy đủ ⇒ đọc được", async () => {
    const record = validRecord({
      resultKind: "safe-retryable",
      retryAt: T0 + 60_000,
      status: 429,
      errorCode: "RATE_LIMITED",
    });

    await expect(readWith(JSON.stringify(record))).resolves.toMatchObject({
      attemptId: "a-1",
      resultKind: "safe-retryable",
    });
  });
});

describe("localStorage ghi hỏng sau khi probe qua được", () => {
  it("quota nổ lúc ghi nhật ký ⇒ unavailable, và Web Lock được nhả", async () => {
    const locks = installWebLocks();
    removeIdb();

    // Probe (`setItem` khoá thăm dò) qua được, nhưng đúng lần ghi nhật ký thì
    // ném — chế độ riêng tư và quota gần đầy hành xử y hệt vậy.
    const original = window.localStorage.setItem.bind(window.localStorage);
    const spy = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation((key: string, value: string) => {
        if (key === LOCAL_KEY) throw new DOMException("quota", "QuotaExceededError");
        original(key, value);
      });

    const outcome = await acquireRefreshLock("gen-1", T0);

    expect(outcome.status).toBe("unavailable");
    // Không nhả khoá ở đây thì mọi tab sau đều thấy "bận" vĩnh viễn.
    expect(locks.held()).toBe(0);

    spy.mockRestore();
  });
});

describe("hai tab tranh nhau", () => {
  it("nhánh lease-IDB: hai lời gọi song song ⇒ ĐÚNG MỘT giành được", async () => {
    removeWebLocks();
    installFakeIdb();

    const [a, b] = await Promise.all([
      acquireRefreshLock("gen-1", T0),
      acquireRefreshLock("gen-1", T0),
    ]);

    const acquired = [a, b].filter((o) => o.status === "acquired");
    expect(acquired).toHaveLength(1);
  });

  it("nhánh Web Locks: hai lời gọi song song ⇒ ĐÚNG MỘT giành được", async () => {
    installWebLocks();
    installFakeIdb();

    const [a, b] = await Promise.all([
      acquireRefreshLock("gen-1", T0),
      acquireRefreshLock("gen-1", T0),
    ]);

    const acquired = [a, b].filter((o) => o.status === "acquired");
    expect(acquired).toHaveLength(1);
  });
});
