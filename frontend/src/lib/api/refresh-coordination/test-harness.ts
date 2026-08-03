// src/lib/api/refresh-coordination/test-harness.ts
/**
 * Bộ đồ nghề cho test lớp phối hợp refresh.
 *
 * Cố ý KHÔNG dùng `fake-indexeddb/auto` ở setup toàn cục: nó gắn IndexedDB vào
 * mọi test, và như thế ô "không có IndexedDB" của ma trận storage trở thành
 * không kiểm được — đúng ô dẫn tới fail-closed, tức ô quan trọng nhất. Mỗi
 * suite tự dựng `IDBFactory` riêng để các ca không dùng chung dữ liệu.
 *
 * Vitest bật `mockReset` + `restoreMocks`, nên mọi thứ ở đây phải được cài lại
 * trong `beforeEach`, không cài một lần ở đầu tệp.
 */
import { IDBFactory } from "fake-indexeddb";

type Nav = Navigator & { locks?: LockManager };

/** Gắn một IndexedDB SẠCH. Gọi trong `beforeEach`. */
export function installFakeIdb(): void {
  Object.defineProperty(globalThis, "indexedDB", {
    configurable: true,
    writable: true,
    value: new IDBFactory(),
  });
}

/** Gỡ hẳn IndexedDB — dùng cho hai ô "IDB lỗi" của ma trận. */
export function removeIdb(): void {
  Object.defineProperty(globalThis, "indexedDB", {
    configurable: true,
    writable: true,
    value: undefined,
  });
}

/**
 * Mock Web Locks giữ ĐÚNG ngữ nghĩa cần cho cơ chế này:
 *
 * - `ifAvailable: true` mà khoá đang bị giữ ⇒ gọi callback với `null` (không
 *   chờ). Đây là đường mà một tab thứ hai đi qua.
 * - khoá được giữ SUỐT thời gian promise của callback chưa settle — nếu mock
 *   nhả ngay khi callback trả về thì test sẽ xanh trong khi mã thật hỏng.
 */
export function installWebLocks(): { held: () => number } {
  const heldLocks = new Set<string>();

  const request = (async (
    name: string,
    optionsOrCallback: LockOptions | ((lock: Lock | null) => Promise<unknown>),
    maybeCallback?: (lock: Lock | null) => Promise<unknown>,
  ) => {
    const options: LockOptions =
      typeof optionsOrCallback === "function" ? {} : optionsOrCallback;
    const callback =
      typeof optionsOrCallback === "function" ? optionsOrCallback : maybeCallback!;

    if (heldLocks.has(name)) {
      if (options.ifAvailable) return callback(null);
      // Không `ifAvailable` thì phải chờ tới lượt.
      while (heldLocks.has(name)) await new Promise((r) => setTimeout(r, 1));
    }

    heldLocks.add(name);
    try {
      return await callback({ name, mode: options.mode ?? "exclusive" } as Lock);
    } finally {
      heldLocks.delete(name);
    }
  }) as LockManager["request"];

  Object.defineProperty(navigator as Nav, "locks", {
    configurable: true,
    writable: true,
    value: { request } as LockManager,
  });

  return { held: () => heldLocks.size };
}

/** Gỡ Web Locks — dùng cho hai ô "không Web Locks" của ma trận. */
export function removeWebLocks(): void {
  Object.defineProperty(navigator as Nav, "locks", {
    configurable: true,
    writable: true,
    value: undefined,
  });
}

/** Cài Web Locks mà `request()` luôn ném — API có mặt nhưng hỏng. */
export function installBrokenWebLocks(): void {
  Object.defineProperty(navigator as Nav, "locks", {
    configurable: true,
    writable: true,
    value: {
      request: () => {
        throw new Error("locks unavailable");
      },
    } as unknown as LockManager,
  });
}
