// src/lib/api/refresh-coordination/lock.ts
/**
 * Giành quyền làm mới phiên giữa các tab.
 *
 * Bản ghi nhật ký **chính là** lease — không tách "khoá" khỏi "nhật ký" thành
 * hai thứ riêng. Tách ra thì phải giữ chúng đồng bộ, và chỗ chúng lệch nhau
 * đúng là chỗ hỏng: khoá đã nhả nhưng nhật ký vẫn `in-flight`, hoặc ngược lại.
 *
 * Web Locks (khi có) chỉ đóng vai mutex NHANH cho thao tác đọc-sửa-ghi bản
 * ghi; nó không thay được bản ghi vì lock biến mất cùng tab, còn thứ ta cần
 * biết nhất — "có một request đang bay mà chủ của nó đã chết" — chỉ nằm ở dữ
 * liệu bền.
 */
import type { JournalRecord, JournalStore } from "./types";
import { hasWebLocks, selectJournalStore } from "./storage";

const WEB_LOCK_NAME = "qlts-refresh-coordination";

/** Hạn giữ khoá. Phải LỚN HƠN timeout của request refresh. */
export const LEASE_TTL_MS = 20_000;
/** Nhịp gia hạn. TTL/3 để lỡ một nhịp vẫn chưa mất khoá. */
export const HEARTBEAT_MS = Math.floor(LEASE_TTL_MS / 3);

export interface LockHandle {
  readonly attemptId: string;
  /** Ghi bản ghi mới (đổi phase, gắn kết quả…) và tự gia hạn `until`. */
  update(patch: Partial<JournalRecord>): Promise<JournalRecord>;
  /** Nhả khoá. KHÔNG xoá bản ghi — kết quả còn phải để tab khác đọc. */
  release(): Promise<void>;
}

export type AcquireOutcome =
  /** Giành được. Chỉ tab này được POST. */
  | { status: "acquired"; handle: LockHandle; store: JournalStore }
  /** Tab khác đang giữ và còn hạn. Chờ rồi đọc kết quả của họ. */
  | { status: "busy"; record: JournalRecord }
  /**
   * Có bản ghi CẤM thử lại ngay lúc này:
   * - `result` — `ambiguous`/`nonterminal-stop` (cấm tới khi đăng nhập lại),
   *   hoặc `success`/`terminal` (đã xong, thử lại là trình lại token cũ);
   * - `stale-in-flight` — chủ của attempt chết giữa lúc request đang bay;
   * - `cooldown` — `safe-retryable` nhưng chưa tới `retryAt`.
   */
  | {
      status: "blocked";
      record: JournalRecord;
      reason: "result" | "stale-in-flight" | "cooldown";
    }
  /** Không có kho ghi bền ⇒ fail-closed, không được POST. */
  | { status: "unavailable" };

function newId(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  if (c && typeof c.getRandomValues === "function") {
    const buf = new Uint8Array(16);
    c.getRandomValues(buf);
    return Array.from(buf, (b) => b.toString(16).padStart(2, "0")).join("");
  }
  // Không có crypto: định danh chỉ cần phân biệt cục bộ, không cần bí mật.
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Bản ghi này có đang chặn một attempt mới không, và vì sao.
 *
 * ⚠️ Nguyên tắc trung tâm: **hạn của lease chỉ nói ai còn quyền GIỮ khoá, nó
 * KHÔNG nói lần thử trước có kết thúc an toàn hay không.** Một attempt đã có
 * kết quả thì chính kết quả đó quyết định, dù lease hết hạn từ lâu — coi hết
 * hạn là "được thử lại" sẽ biến mọi kết quả thành giấy phép POST sau 20 giây,
 * tức xoá sạch tác dụng của cả lớp này.
 *
 * Thứ tự nhánh:
 * 1. `ambiguous`/`nonterminal-stop` ⇒ cấm, kể cả đã quá hạn. Quá hạn không làm
 *    một rotation mơ hồ trở nên an toàn.
 * 2. Còn hạn ⇒ tab khác đang làm ⇒ `busy`.
 * 3. `success`/`terminal` ⇒ đã xong. POST nữa là trình lại một token server đã
 *    vô hiệu hoá — đúng hành vi bị tính là reuse.
 * 4. `safe-retryable` ⇒ được thử lại, nhưng chỉ SAU `retryAt`.
 * 5. `in-flight` quá hạn, không kết quả ⇒ chủ chết giữa lúc request bay ⇒ cấm.
 *    Đây chính là ca Web Locks một mình bỏ sót.
 * 6. `acquired` quá hạn ⇒ chết TRƯỚC khi chạm mạng ⇒ cướp được vô điều kiện.
 */
function inspect(
  record: JournalRecord | null,
  now: number,
): { blocked: false } | { blocked: true; outcome: AcquireOutcome } {
  if (!record) return { blocked: false };

  const block = (reason: "result" | "stale-in-flight" | "cooldown") =>
    ({ blocked: true, outcome: { status: "blocked", record, reason } }) as const;

  if (
    record.resultKind === "ambiguous" ||
    record.resultKind === "nonterminal-stop"
  ) {
    return block("result");
  }

  if (record.until > now) {
    return { blocked: true, outcome: { status: "busy", record } };
  }

  if (record.resultKind === "success" || record.resultKind === "terminal") {
    return block("result");
  }

  if (record.resultKind === "safe-retryable") {
    if (typeof record.retryAt === "number" && now < record.retryAt) {
      return block("cooldown");
    }
    return { blocked: false };
  }

  if (record.phase === "in-flight") {
    return block("stale-in-flight");
  }

  return { blocked: false };
}

/**
 * Giữ Web Lock cho tới khi được bảo nhả.
 *
 * `navigator.locks.request` chỉ giữ khoá trong lúc callback chạy, nên muốn giữ
 * qua nhiều `await` ở ngoài thì phải treo callback bằng một promise và tự
 * resolve khi release.
 */
type WebLockResult =
  /** Giành được, hoặc tab khác đang giữ (`granted: false`) — API vẫn lành. */
  | { ok: true; granted: boolean; release: () => Promise<void> }
  /** Bản thân API hỏng. KHÁC HẲN "tab khác đang giữ". */
  | { ok: false };

function holdWebLock(): Promise<WebLockResult> {
  return new Promise((resolve) => {
    let signalRelease = () => {};
    const held = new Promise<void>((r) => {
      signalRelease = r;
    });

    try {
      // `request()` chỉ settle SAU khi callback xong và khoá đã thực sự nhả —
      // nên nó là thứ duy nhất cho biết "đã nhả xong", và `release()` phải chờ
      // nó. Trả về khi khoá còn đang giữ sẽ khiến tab kế tiếp thấy "bận" trong
      // khi thật ra chẳng ai làm gì.
      const requested = navigator.locks.request(
        WEB_LOCK_NAME,
        { ifAvailable: true },
        async (lock) => {
          if (!lock) {
            // Tab khác đang giữ — trạng thái BÌNH THƯỜNG, chờ họ là đúng.
            resolve({ ok: true, granted: false, release: async () => {} });
            return;
          }
          resolve({
            ok: true,
            granted: true,
            release: async () => {
              signalRelease();
              await requested;
            },
          });
          await held;
        },
      );
      // API lỗi ≠ tab khác đang giữ. Gộp hai thứ này thành "bận" sẽ khiến ta
      // chờ mãi một tab không tồn tại; phải đi đường fail-closed.
      void requested.catch(() => resolve({ ok: false }));
    } catch {
      resolve({ ok: false });
    }
  });
}

/**
 * Chạy một thao tác trên nhật ký TRONG vùng mutex.
 *
 * Khác `acquireRefreshLock` ở hai điểm: nó CHỜ tới lượt (không `ifAvailable`)
 * vì các thao tác vòng đời không được phép bỏ cuộc giữa chừng, và nó không
 * dựng lease — chỉ mượn mutex.
 *
 * Bắt buộc với kho `localStorage`: kho đó không có giao dịch, nên một
 * `clear()` gọi ngoài mutex sẽ chạy song song với `update()` của tab đang giữ.
 * Với kho IDB thì `mutate()` vốn đã nguyên tử, nhưng đi chung một đường vẫn
 * tốt hơn hai đường sẽ lệch nhau.
 */
export async function withJournalMutex<T>(
  fn: (store: JournalStore) => Promise<T>,
): Promise<{ ok: true; value: T } | { ok: false }> {
  const store = await selectJournalStore();
  if (!store) return { ok: false };

  if (!hasWebLocks()) {
    // Không Web Locks ⇒ kho chắc chắn là IDB (xem `selectJournalStore`), và
    // `mutate()` của nó đã nguyên tử.
    try {
      return { ok: true, value: await fn(store) };
    } catch {
      return { ok: false };
    }
  }

  try {
    const value = await navigator.locks.request(WEB_LOCK_NAME, async () => fn(store));
    return { ok: true, value: value as T };
  } catch {
    return { ok: false };
  }
}

/**
 * Thử giành quyền làm mới phiên.
 *
 * `generationBefore` là fingerprint `csrf_token` NGAY TRƯỚC khi thử — nó là
 * bằng chứng duy nhất cho biết sau này có token mới hay không.
 */
export async function acquireRefreshLock(
  generationBefore: string | null,
  now: number = Date.now(),
): Promise<AcquireOutcome> {
  const store = await selectJournalStore();
  if (!store) return { status: "unavailable" };

  const attemptId = newId();
  const owner = newId().slice(0, 8);

  const build = (): JournalRecord => ({
    attemptId,
    owner,
    phase: "acquired",
    generationBefore,
    until: now + LEASE_TTL_MS,
    updatedAt: now,
  });

  // Nhánh Web Locks: mutex do trình duyệt lo, nên đọc-rồi-ghi là an toàn và
  // dùng được với cả kho `localStorage` (vốn không có giao dịch).
  if (hasWebLocks()) {
    const lock = await holdWebLock();
    if (!lock.ok) return { status: "unavailable" };
    if (!lock.granted) {
      const record = await store.read();
      return record
        ? { status: "busy", record }
        : // Không giành được lock mà cũng chưa có bản ghi: tab kia vừa giành
          // xong và chưa kịp ghi. Coi như bận — thử lại sau là đúng.
          { status: "busy", record: { ...build(), owner: "unknown" } };
    }

    try {
      const current = await store.read();
      const verdict = inspect(current, now);
      if (verdict.blocked) {
        await lock.release();
        return verdict.outcome;
      }
      const record = build();
      await store.write(record);
      return {
        status: "acquired",
        store,
        handle: makeHandle(store, record, lock.release),
      };
    } catch (error) {
      // Ghi hỏng (quota/private mode) ⇒ KHÔNG ghi bền được ⇒ fail-closed.
      await lock.release();
      void error;
      return { status: "unavailable" };
    }
  }

  // Không có Web Locks: kho phải là IDB (xem `selectJournalStore`), và toàn bộ
  // kiểm-tra-rồi-đặt phải nằm trong MỘT giao dịch, nếu không hai tab cùng đọc
  // "trống" rồi cùng ghi.
  let outcome: AcquireOutcome = { status: "unavailable" };
  try {
    await store.mutate((current) => {
      const verdict = inspect(current, now);
      if (verdict.blocked) {
        outcome = verdict.outcome;
        return current;
      }
      const record = build();
      outcome = {
        status: "acquired",
        store,
        handle: makeHandle(store, record, async () => {}),
      };
      return record;
    });
  } catch {
    return { status: "unavailable" };
  }
  return outcome;
}

/** Trường nào một patch KHÔNG bao giờ được đụng tới. */
const IDENTITY_FIELDS = ["attemptId", "owner", "generationBefore"] as const;

function stripIdentity(patch: Partial<JournalRecord>): Partial<JournalRecord> {
  const clean: Partial<JournalRecord> = { ...patch };
  for (const field of IDENTITY_FIELDS) delete clean[field];
  return clean;
}

/** Ném khi tab gọi `update()` sau khi đã mất lease vào tay tab khác. */
export class LeaseLostError extends Error {
  constructor() {
    super("Lease đã mất — tab khác đang giữ quyền làm mới phiên");
    this.name = "LeaseLostError";
  }
}

function makeHandle(
  store: JournalStore,
  initial: JournalRecord,
  releaseLock: () => Promise<void>,
): LockHandle {
  let released = false;
  /**
   * Hàng đợi các lần ghi, nối tiếp nhau.
   *
   * KHÔNG dùng một biến "lần ghi đang chạy": hai heartbeat gọi sát nhau sẽ ghi
   * đè biến đó, và `release()` chỉ chờ lần cuối — lần trước vẫn có thể ghi SAU
   * khi Web Lock đã nhả, tức ghi ngoài vùng mutex. Nối chuỗi vừa giữ đúng thứ
   * tự ghi, vừa cho `release()` một điểm duy nhất để đợi TẤT CẢ.
   */
  let chain: Promise<unknown> = Promise.resolve();
  /** Lời gọi `release()` thứ hai phải đợi cùng promise, không được trả sớm. */
  let releasing: Promise<void> | null = null;

  return {
    attemptId: initial.attemptId,

    /**
     * Ghi bản ghi mới — nhưng CHỈ khi ta vẫn là chủ.
     *
     * Đây là chỗ dễ sai nhất của cả cơ chế. Một tab hết hạn ở `acquired` rồi
     * "tỉnh dậy" (máy vừa ngủ dậy, tab bị treo rồi được đánh thức) sẽ tiếp tục
     * chạy đúng dòng lệnh kế tiếp. Nếu `update()` cứ thế ghi đè thì nó xoá bản
     * ghi của tab đang giữ và cả hai cùng POST — đúng cuộc đua mà lớp này sinh
     * ra để chặn, chỉ khác là giờ ta tự tạo ra nó.
     *
     * Kiểm chủ quyền phải nằm TRONG cùng giao dịch với lần ghi (`mutate`),
     * không phải "đọc rồi so rồi ghi" — nếu tách ra thì lại đúng cửa sổ đua đó.
     */
    async update(patch: Partial<JournalRecord>): Promise<JournalRecord> {
      // Đã nhả khoá thì mọi lần ghi sau đó đều nằm NGOÀI vùng mutex. Nguy hiểm
      // nhất là heartbeat: một nhịp đã lên lịch có thể nổ sau `release()`, và
      // với kho `localStorage` (không giao dịch) nó sẽ ghi đè bản ghi của tab
      // đang giữ mà không ai chặn được.
      if (released) throw new LeaseLostError();

      // Nối tiếp vào chuỗi: hai heartbeat gọi sát nhau phải ghi TUẦN TỰ, và
      // `release()` cần một điểm duy nhất để đợi tất cả.
      const run = chain.then(async () => {
        const now = Date.now();
        let lost = false;

        const next = await store.mutate((current) => {
          if (!current || current.attemptId !== initial.attemptId) {
            lost = true;
            return current;
          }
          return {
            ...current,
            ...stripIdentity(patch),
            // Gia hạn ở MỌI lần ghi: mỗi lần ghi là bằng chứng tab còn sống.
            until: now + LEASE_TTL_MS,
            updatedAt: now,
          };
        });

        if (lost || !next) throw new LeaseLostError();
        return next;
      });

      // Cập nhật chuỗi TRƯỚC khi trả, để `release()` xen vào vẫn thấy và đợi.
      chain = run.catch(() => undefined);
      return run;
    },

    async release(): Promise<void> {
      // Lời gọi thứ hai phải chờ ĐÚNG lần thứ nhất. Trả sớm ở đây nghĩa là
      // caller tưởng khoá đã nhả trong khi lần ghi vẫn đang chạy.
      if (releasing) return releasing;
      released = true;

      releasing = (async () => {
        // Đợi TẤT CẢ lần ghi hoàn tất trước khi nhả Web Lock. Nhả sớm thì tab
        // kế tiếp giành được khoá trong lúc ta vẫn đang ghi — đúng cửa sổ mà
        // mutex sinh ra để đóng.
        await chain;
        // Cố ý KHÔNG xoá bản ghi: tab khác còn phải đọc `resultKind`. Dọn dẹp
        // là việc của vòng đời nhật ký, không phải của release.
        await releaseLock();
      })();

      return releasing;
    },
  };
}
