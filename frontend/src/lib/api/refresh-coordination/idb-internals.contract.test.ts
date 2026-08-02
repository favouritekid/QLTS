// src/lib/api/refresh-coordination/idb-internals.contract.test.ts
/**
 * Hai đường hỏng của IndexedDB mà `fake-indexeddb` không dựng lại được, nên
 * phải tự làm một IDB giả.
 *
 * Cả hai đều hỏng theo kiểu nguy hiểm nhất: **báo thành công trong khi dữ liệu
 * chưa bền**. Một `read()` trả `null` vì giao dịch abort sẽ bị tầng trên hiểu
 * là "chưa ai thử refresh" và cấp phép POST.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import { selectJournalStore } from "./storage";
import { removeWebLocks } from "./test-harness";

type AnyRequest = {
  result?: unknown;
  error?: unknown;
  onsuccess?: () => void;
  onerror?: () => void;
  onupgradeneeded?: () => void;
  onblocked?: () => void;
};

function defineIdb(value: unknown) {
  Object.defineProperty(globalThis, "indexedDB", {
    configurable: true,
    writable: true,
    value,
  });
}

beforeEach(() => {
  removeWebLocks();
  window.localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("giao dịch abort SAU khi request đã success", () => {
  it("không được báo thành công — phải fail-closed", async () => {
    // Giao dịch phát `onsuccess` cho lệnh `get` (đọc xong), rồi mới `onabort`
    // (quota, lỗi ghi, tab bị đóng). Nếu chốt kết quả ở `request.onsuccess`
    // thì ta trả về "không có bản ghi" cho một giao dịch chưa từng hoàn tất.
    const db = {
      objectStoreNames: { contains: () => true },
      close: () => {},
      transaction: () => {
        const tx: Record<string, unknown> = {};
        const store = {
          get: () => {
            // Khai báo SẴN `onsuccess`: `runTransaction` nhận diện một request
            // bằng `"onsuccess" in out`, nên một object rỗng sẽ không bao giờ
            // được gắn handler — và test sẽ xanh nhờ `onabort` chứ không nhờ
            // contract đang kiểm.
            const request: AnyRequest = { onsuccess: undefined };
            queueMicrotask(() => {
              request.result = undefined;
              request.onsuccess?.();
              // Giao dịch chết NGAY SAU khi lệnh đọc báo xong.
              queueMicrotask(() => {
                (tx.onabort as (() => void) | undefined)?.();
              });
            });
            return request;
          },
        };
        tx.objectStore = () => store;
        return tx;
      },
    };

    defineIdb({
      open: () => {
        const request: AnyRequest = {};
        queueMicrotask(() => {
          request.result = db;
          request.onsuccess?.();
        });
        return request;
      },
    });

    // `selectJournalStore` chạm thật một lần bằng `read()`; giao dịch abort nên
    // lần chạm đó phải hỏng, và kho phải bị coi là không dùng được.
    const store = await selectJournalStore();

    // Không Web Locks + IDB hỏng ⇒ fail-closed, KHÔNG tụt xuống localStorage.
    expect(store).toBeNull();
  });
});

describe("`open()` timeout rồi callback tới muộn", () => {
  it("vẫn hỏng, và kết nối đến muộn được đóng đúng một lần", async () => {
    const close = vi.fn();

    defineIdb({
      open: () => {
        const request: AnyRequest = {};
        // Chậm hơn hạn chờ `open()` trong storage.ts (3s), nhưng không quá xa
        // để test còn kịp quan sát trong hạn của nó.
        setTimeout(() => {
          request.result = { close, objectStoreNames: { contains: () => true } };
          request.onsuccess?.();
        }, 3_200);
        return request;
      },
    });

    const store = await selectJournalStore();

    // Đã bỏ cuộc: không kho ⇒ không được POST.
    expect(store).toBeNull();

    // Kết nối tới muộn không ai cầm nữa. Để nguyên thì nó giữ database và chặn
    // `versionchange` của tab khác — phải đóng, và đúng một lần.
    await new Promise((resolve) => setTimeout(resolve, 800));
    expect(close).toHaveBeenCalledTimes(1);
  }, 9_000);
});
