// src/lib/api/refresh-coordination/storage.ts
/**
 * Kho lưu nhật ký refresh — IndexedDB, hoặc `localStorage` khi IDB không dùng
 * được.
 *
 * Nguyên tắc xuyên suốt: **phát hiện bằng cách THỬ THẬT, không hỏi sự tồn tại
 * của API**. Safari ở chế độ riêng tư vẫn phơi `window.indexedDB` nhưng
 * `open()` lỗi; Firefox chặn cookie thì đọc `localStorage` ném ngay ở lần chạm
 * đầu tiên. Một guard kiểu `"indexedDB" in window` sẽ báo "có" rồi hỏng lúc
 * chạy — đúng thời điểm tệ nhất, khi ta đang quyết định có được POST hay không.
 */
import type { JournalRecord, JournalStore } from "./types";

const DB_NAME = "qlts-refresh-coordination";
const DB_VERSION = 1;
const STORE_NAME = "journal";
/** Một bản ghi duy nhất — cả ứng dụng chỉ có một luồng refresh tại một thời điểm. */
const RECORD_KEY = "current";
const LOCAL_STORAGE_KEY = "qlts_refresh_journal";

/** Mở IDB quá lâu = coi như không dùng được, đừng treo luồng quyết định. */
const OPEN_TIMEOUT_MS = 3_000;

/**
 * Có dữ liệu ở kho nhưng KHÔNG đọc hiểu được.
 *
 * Khác hẳn "không có bản ghi": không có nghĩa là chưa ai thử refresh, còn đọc
 * không hiểu nghĩa là **có thể** đã có một attempt đang bay mà ta không biết
 * trạng thái. Coi hai thứ như nhau là mở đường POST đè lên một rotation có thể
 * đã xảy ra — nên ca này phải fail-closed, không được im lặng trả `null`.
 */
export class CorruptJournalError extends Error {
  constructor(reason: string) {
    super(`Nhật ký refresh không đọc được: ${reason}`);
    this.name = "CorruptJournalError";
  }
}

const PHASES = new Set(["acquired", "in-flight"]);
const RESULT_KINDS = new Set([
  "success",
  "terminal",
  "safe-retryable",
  "nonterminal-stop",
  "ambiguous",
]);

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

/**
 * Kiểm bản ghi theo allowlist, không theo "có đủ trường hay không".
 *
 * Một `phase` lạ hay `resultKind` lạ nguy hiểm hơn thiếu trường: mã ở
 * `inspect()` phân xử bằng cách so khớp chuỗi, nên một giá trị ngoài danh sách
 * sẽ lặng lẽ rơi xuống nhánh "cho phép thử lại".
 */
function validateRecord(value: unknown): JournalRecord {
  if (!value || typeof value !== "object") {
    throw new CorruptJournalError("không phải object");
  }
  const r = value as Partial<JournalRecord>;

  if (!nonEmptyString(r.attemptId)) throw new CorruptJournalError("attemptId");
  if (!nonEmptyString(r.owner)) throw new CorruptJournalError("owner");
  if (typeof r.phase !== "string" || !PHASES.has(r.phase)) {
    throw new CorruptJournalError(`phase=${String(r.phase)}`);
  }
  if (r.generationBefore !== null && typeof r.generationBefore !== "string") {
    throw new CorruptJournalError("generationBefore");
  }
  if (!isFiniteNumber(r.until) || r.until < 0) {
    throw new CorruptJournalError("until");
  }
  if (!isFiniteNumber(r.updatedAt) || r.updatedAt < 0) {
    throw new CorruptJournalError("updatedAt");
  }
  if (r.status !== undefined && !isFiniteNumber(r.status)) {
    throw new CorruptJournalError("status");
  }
  if (r.retryAt !== undefined && (!isFiniteNumber(r.retryAt) || r.retryAt < 0)) {
    throw new CorruptJournalError("retryAt");
  }
  if (r.errorCode !== undefined && typeof r.errorCode !== "string") {
    throw new CorruptJournalError("errorCode");
  }

  if (r.resultKind !== undefined) {
    if (typeof r.resultKind !== "string" || !RESULT_KINDS.has(r.resultKind)) {
      throw new CorruptJournalError(`resultKind=${String(r.resultKind)}`);
    }
    // Có kết quả thì attempt phải đã chạm mạng. Một bản ghi `acquired` mà kèm
    // `resultKind` là thứ không thể sinh ra hợp lệ, nên nó hoặc bị sửa tay hoặc
    // là tàn dư của một phiên bản khác — cả hai đều không đáng tin.
    if (r.phase !== "in-flight") {
      throw new CorruptJournalError(
        `resultKind=${r.resultKind} nhưng phase=${r.phase}`,
      );
    }

    // `safe-retryable` là trạng thái DUY NHẤT cấp lại quyền POST, nên nó phải
    // chịu kiểm chặt nhất — kể cả quan hệ chéo giữa các trường.
    //
    // Cơ sở để coi nó an toàn rất hẹp: slowapi chặn ở decorator, TRƯỚC khi thân
    // hàm chạy, nên `429 RATE_LIMITED` chắc chắn chưa chạm rotation. Một `5xx`
    // hay một mã 429 khác KHÔNG có bảo đảm đó. Chỉ cần chấp nhận
    // `resultKind: "safe-retryable"` kèm `status: 500` là ta tự cấp phép POST
    // lại sau một lần thử có thể đã rotate xong.
    if (r.resultKind === "safe-retryable") {
      if (!isFiniteNumber(r.retryAt)) {
        throw new CorruptJournalError("safe-retryable thiếu retryAt hữu hạn");
      }
      if (r.status !== 429) {
        throw new CorruptJournalError(`safe-retryable status=${String(r.status)}`);
      }
      if (r.errorCode !== "RATE_LIMITED") {
        throw new CorruptJournalError(
          `safe-retryable errorCode=${String(r.errorCode)}`,
        );
      }
    }
  }

  return r as JournalRecord;
}

/** `undefined`/`null` ⇒ chưa có bản ghi. Mọi thứ khác phải hợp lệ. */
function parseStored(value: unknown): JournalRecord | null {
  if (value === undefined || value === null) return null;
  return validateRecord(value);
}

// ---------------------------------------------------------------------------
// IndexedDB
// ---------------------------------------------------------------------------

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      fn();
    };

    let request: IDBOpenDBRequest;
    try {
      request = indexedDB.open(DB_NAME, DB_VERSION);
    } catch (error) {
      reject(error);
      return;
    }

    // `open()` có thể KHÔNG BAO GIỜ gọi callback nào: khi một tab khác giữ
    // kết nối cũ và chặn nâng cấp phiên bản, `blocked` bắn rồi im lặng.
    const timer = setTimeout(
      () => finish(() => reject(new Error("indexedDB.open timeout"))),
      OPEN_TIMEOUT_MS,
    );
    const done = (fn: () => void) => {
      clearTimeout(timer);
      finish(fn);
    };

    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };
    request.onsuccess = () => {
      if (settled) {
        // Đã bỏ cuộc vì timeout, giờ `open()` mới xong. Kết nối này không ai
        // cầm nữa; để nguyên thì nó giữ DB và chặn `versionchange` của tab
        // khác — đóng lại rồi thôi.
        try {
          request.result.close();
        } catch {
          // ignore
        }
        return;
      }
      done(() => resolve(request.result));
    };
    request.onerror = () =>
      done(() => reject(request.error ?? new Error("indexedDB.open failed")));
    request.onblocked = () =>
      done(() => reject(new Error("indexedDB.open blocked")));
  });
}

function runTransaction<T>(
  db: IDBDatabase,
  mode: IDBTransactionMode,
  body: (store: IDBObjectStore) => IDBRequest | { result: T } | void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    let tx: IDBTransaction;
    try {
      tx = db.transaction(STORE_NAME, mode);
    } catch (error) {
      reject(error);
      return;
    }

    let value: T | undefined;
    const store = tx.objectStore(STORE_NAME);
    try {
      const out = body(store);
      if (out && "onsuccess" in out) {
        (out as IDBRequest).onsuccess = () => {
          value = (out as IDBRequest).result as T;
        };
      } else if (out && "result" in out) {
        value = out.result;
      }
    } catch (error) {
      reject(error);
      return;
    }

    // Chốt ở `oncomplete`, KHÔNG ở `request.onsuccess`: một request thành công
    // trong giao dịch sau đó vẫn có thể bị abort (quota, lỗi ghi). Chỉ khi
    // giao dịch complete thì dữ liệu mới thật sự bền — mà tính bền chính là
    // thứ ta đang mua ở đây.
    tx.oncomplete = () => resolve(value as T);
    tx.onerror = () => reject(tx.error ?? new Error("IDB transaction failed"));
    tx.onabort = () => reject(tx.error ?? new Error("IDB transaction aborted"));
  });
}

class IdbJournalStore implements JournalStore {
  readonly kind = "idb" as const;

  constructor(private readonly db: IDBDatabase) {}

  async read(): Promise<JournalRecord | null> {
    const raw = await runTransaction<unknown>(this.db, "readonly", (store) =>
      store.get(RECORD_KEY),
    );
    return parseStored(raw);
  }

  async write(record: JournalRecord): Promise<void> {
    await runTransaction<void>(this.db, "readwrite", (store) => {
      store.put(record, RECORD_KEY);
    });
  }

  async clear(): Promise<void> {
    await runTransaction<void>(this.db, "readwrite", (store) => {
      store.delete(RECORD_KEY);
    });
  }

  /**
   * Đọc-sửa-ghi trong MỘT giao dịch `readwrite`.
   *
   * Đây là thứ khiến IndexedDB làm được mutex mà `localStorage` không: hai tab
   * cùng gọi `mutate` thì IDB tuần tự hoá hai giao dịch, nên tab thứ hai đọc
   * được đúng thứ tab thứ nhất vừa ghi. Tách thành `read()` rồi `write()` sẽ
   * mở lại đúng cửa sổ đua mà cả lớp này sinh ra để đóng.
   */
  async mutate(
    fn: (current: JournalRecord | null) => JournalRecord | null,
  ): Promise<JournalRecord | null> {
    return new Promise((resolve, reject) => {
      let tx: IDBTransaction;
      try {
        tx = this.db.transaction(STORE_NAME, "readwrite");
      } catch (error) {
        reject(error);
        return;
      }

      const store = tx.objectStore(STORE_NAME);
      let next: JournalRecord | null = null;
      const getRequest = store.get(RECORD_KEY);

      getRequest.onsuccess = () => {
        try {
          const current = parseStored(getRequest.result);
          next = fn(current);
          if (next === null) store.delete(RECORD_KEY);
          else store.put(next, RECORD_KEY);
        } catch (error) {
          try {
            tx.abort();
          } catch {
            // abort có thể ném nếu giao dịch đã kết thúc — lỗi gốc mới đáng báo.
          }
          reject(error);
        }
      };

      tx.oncomplete = () => resolve(next);
      tx.onerror = () => reject(tx.error ?? new Error("IDB mutate failed"));
      tx.onabort = () => reject(tx.error ?? new Error("IDB mutate aborted"));
    });
  }
}

// ---------------------------------------------------------------------------
// localStorage
// ---------------------------------------------------------------------------

/**
 * Chỉ dùng KÈM Web Locks. Không có giao dịch nên `mutate` ở đây là đọc-rồi-ghi
 * — an toàn duy nhất khi đã có mutex bên ngoài đảm bảo mỗi lúc chỉ một tab
 * chạy tới đây.
 */
class LocalStorageJournalStore implements JournalStore {
  readonly kind = "localStorage" as const;

  async read(): Promise<JournalRecord | null> {
    const raw = window.localStorage.getItem(LOCAL_STORAGE_KEY);
    if (raw === null) return null;

    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      // JSON hỏng ⇒ CÓ dữ liệu mà đọc không hiểu. Không được coi như trống:
      // bản ghi đó có thể là một attempt `in-flight`, và trả `null` ở đây sẽ
      // mở đường cho một POST đè lên rotation có thể đã xảy ra.
      throw new CorruptJournalError("JSON không phân tích được");
    }
    return parseStored(parsed);
  }

  async write(record: JournalRecord): Promise<void> {
    // Cố ý KHÔNG nuốt lỗi: `setItem` ném khi hết quota hoặc bị chặn ghi, và
    // lúc đó ta MẤT khả năng ghi bền. Người gọi phải thấy để fail-closed, chứ
    // không được lặng lẽ POST như thể đã ghi xong.
    window.localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(record));
  }

  async clear(): Promise<void> {
    window.localStorage.removeItem(LOCAL_STORAGE_KEY);
  }

  async mutate(
    fn: (current: JournalRecord | null) => JournalRecord | null,
  ): Promise<JournalRecord | null> {
    const next = fn(await this.read());
    if (next === null) await this.clear();
    else await this.write(next);
    return next;
  }
}

// ---------------------------------------------------------------------------
// Phát hiện khả dụng
// ---------------------------------------------------------------------------

/** Web Locks có dùng được không. Có thì nó làm mutex, khỏi cần lease. */
export function hasWebLocks(): boolean {
  return (
    typeof navigator !== "undefined" &&
    typeof (navigator as Navigator & { locks?: LockManager }).locks?.request ===
      "function"
  );
}

type IdbProbe =
  | { kind: "store"; store: JournalStore }
  /** Trình duyệt không có IndexedDB ⇒ chưa từng ghi được gì ở đó. */
  | { kind: "absent" }
  /** Có IndexedDB nhưng mở/đọc hỏng, hoặc dữ liệu trong đó không đọc hiểu được. */
  | { kind: "failed" };

async function probeIdb(): Promise<IdbProbe> {
  if (typeof indexedDB === "undefined") return { kind: "absent" };
  try {
    const db = await openDatabase();
    const store = new IdbJournalStore(db);
    // Chạm thật một lần: `open()` thành công vẫn có thể đi kèm giao dịch hỏng
    // (quota 0 ở chế độ riêng tư). Đọc rẻ, không ghi gì — và nếu dữ liệu bên
    // trong hỏng thì `read()` ném, đúng thứ ta cần biết.
    await store.read();
    return { kind: "store", store };
  } catch {
    return { kind: "failed" };
  }
}

function tryLocalStorage(): JournalStore | null {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    const probe = `${LOCAL_STORAGE_KEY}__probe`;
    window.localStorage.setItem(probe, "1");
    window.localStorage.removeItem(probe);
    return new LocalStorageJournalStore();
  } catch {
    return null;
  }
}

/**
 * Chọn kho theo ma trận của plan.
 *
 * ⚠️ Phân biệt IndexedDB **vắng mặt** với IndexedDB **hỏng** — đây là trục
 * chính của bảng, không phải "có/không":
 *
 * | Web Locks | IndexedDB | cách chạy |
 * |---|---|---|
 * | có | dùng được | Web Locks làm mutex + nhật ký IDB |
 * | có | **vắng mặt** | Web Locks làm mutex + nhật ký `localStorage` |
 * | có | **hỏng/dữ liệu không đọc hiểu** | **fail-closed** — KHÔNG đổi kho |
 * | không | dùng được | lease IDB làm mutex + nhật ký IDB |
 * | không | vắng mặt hoặc hỏng | **fail-closed** |
 *
 * Vắng mặt thì chắc chắn chưa từng có nhật ký nào ở đó, nên chuyển sang
 * `localStorage` không mất gì. Hỏng thì ngược lại: nhật ký thật có thể đang
 * nằm trong IDB — kể cả một bản ghi cấm mọi tab POST — và nhìn sang kho khác
 * đang trống chính là xoá lệnh cấm đó.
 *
 * Mọi ô fail-closed đều dựa trên cùng một lý lẽ: không ghi/đọc bền được nghĩa
 * là nếu tab này chết giữa lúc request đang bay thì không ai biết đã có một
 * lần thử. Thà bắt đăng nhập lại còn hơn để tab khác POST đè lên một rotation
 * có thể đã xảy ra.
 */
export async function selectJournalStore(): Promise<JournalStore | null> {
  const probe = await probeIdb();
  if (probe.kind === "store") return probe.store;

  // 🔴 IndexedDB CÓ mặt nhưng hỏng ⇒ TUYỆT ĐỐI không tụt xuống `localStorage`.
  //
  // Nhật ký thật có thể đang nằm trong IDB — kể cả một bản ghi `ambiguous` cấm
  // mọi tab POST. Chuyển sang một kho KHÁC đang trống thì lần đọc kế tiếp thấy
  // "chưa ai thử" và cấp phép POST ngay, tức lệnh cấm bị xoá chỉ vì ta đổi chỗ
  // nhìn. Đổi kho không được phép làm mất trí nhớ.
  if (probe.kind === "failed") return null;

  // `absent`: trình duyệt không có IndexedDB, nên chắc chắn chẳng có nhật ký
  // nào ở đó. `localStorage` chỉ đủ dùng khi Web Locks lo phần mutex.
  if (!hasWebLocks()) return null;
  return tryLocalStorage();
}

/** Chỉ dùng cho test — xoá cả hai kho để mỗi ca chạy trên nền sạch. */
export async function resetJournalStorageForTest(): Promise<void> {
  try {
    window.localStorage.removeItem(LOCAL_STORAGE_KEY);
  } catch {
    // ignore
  }
  try {
    const db = await openDatabase();
    await runTransaction<void>(db, "readwrite", (store) => {
      store.delete(RECORD_KEY);
    });
    db.close();
  } catch {
    // ignore
  }
}
