// src/lib/api/refresh-coordination/lock.contract.test.ts
/**
 * Hai bất biến mà nếu vỡ thì cả lớp phối hợp trở nên vô nghĩa — và cả hai đều
 * vỡ theo kiểu IM LẶNG: mã vẫn chạy, test luồng thuận vẫn xanh, chỉ có phiên
 * của người dùng thỉnh thoảng bốc hơi.
 *
 * 1. Một tab đã MẤT lease không được ghi đè lease của tab đang giữ.
 * 2. Hết hạn KHÔNG biến một kết quả đã hoàn tất thành quyền POST mới.
 *
 * Viết tách khỏi test hành vi thường vì đây là contract, không phải tính năng:
 * chúng phải đỏ ngay khi ai đó "dọn dẹp" một nhánh `if` trông có vẻ thừa.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import { acquireRefreshLock, LEASE_TTL_MS } from "./lock";
import { selectJournalStore } from "./storage";
import { installFakeIdb, removeWebLocks, installWebLocks } from "./test-harness";

const T0 = 1_800_000_000_000;

beforeEach(() => {
  // CHỈ giả lập `Date`. Giả lập luôn `setTimeout` sẽ đóng băng vòng lặp sự kiện
  // mà IndexedDB dựa vào để phát callback — mọi test treo tới timeout thay vì
  // fail, và "đỏ vì treo" thì không nói lên điều gì về contract đang kiểm.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(T0);
  installFakeIdb();
  // Nhánh lease-IDB: không Web Locks, nên toàn bộ việc phân xử nằm ở bản ghi —
  // đúng nhánh mà hai lỗi dưới đây phơi ra rõ nhất.
  removeWebLocks();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("contract 1 — tab đã mất lease không được ghi đè", () => {
  it("T1 hết hạn ở `acquired`, T2 cướp; T1 tỉnh dậy KHÔNG được ghi đè", async () => {
    const first = await acquireRefreshLock("gen-1", T0);
    expect(first.status).toBe("acquired");
    if (first.status !== "acquired") return;

    // T1 chết lặng ở `acquired` (chưa chạm mạng) → quá hạn → T2 cướp hợp lệ.
    const later = T0 + LEASE_TTL_MS + 1_000;
    vi.setSystemTime(later);
    const second = await acquireRefreshLock("gen-1", later);
    expect(second.status).toBe("acquired");
    if (second.status !== "acquired") return;
    expect(second.handle.attemptId).not.toBe(first.handle.attemptId);

    // T1 tỉnh lại và định bước vào `in-flight`. Nếu ghi đè được thì T1 và T2
    // cùng POST — đúng cuộc đua mà toàn bộ lớp này sinh ra để chặn.
    await expect(
      first.handle.update({ phase: "in-flight" }),
    ).rejects.toThrow(/lease/i);

    const store = await selectJournalStore();
    const record = await store!.read();
    expect(record?.attemptId).toBe(second.handle.attemptId);
    expect(record?.phase).toBe("acquired");
  });

  it("patch KHÔNG được sửa danh tính của attempt", async () => {
    const acquired = await acquireRefreshLock("gen-1", T0);
    expect(acquired.status).toBe("acquired");
    if (acquired.status !== "acquired") return;

    await acquired.handle.update({
      phase: "in-flight",
      // Ba trường này định danh attempt; cho phép patch chúng là mở đường cho
      // một tab tự nhận mình là tab khác.
      attemptId: "kẻ-mạo-danh",
      owner: "kẻ-mạo-danh",
      generationBefore: "gen-giả",
    } as never);

    const store = await selectJournalStore();
    const record = await store!.read();
    expect(record?.attemptId).toBe(acquired.handle.attemptId);
    expect(record?.generationBefore).toBe("gen-1");
    expect(record?.owner).not.toBe("kẻ-mạo-danh");
  });
});

describe("contract 2 — hết hạn không giải phóng kết quả đã hoàn tất", () => {
  async function finishWith(
    resultKind: "success" | "terminal" | "safe-retryable",
    extra: Record<string, unknown> = {},
  ) {
    const acquired = await acquireRefreshLock("gen-1", T0);
    if (acquired.status !== "acquired") throw new Error("không giành được lease");
    await acquired.handle.update({ phase: "in-flight" });
    await acquired.handle.update({ resultKind, ...extra });
    await acquired.handle.release();
  }

  it("`success` đã hết hạn ⇒ follower KHÔNG được POST lại", async () => {
    await finishWith("success");

    const later = T0 + LEASE_TTL_MS * 3;
    vi.setSystemTime(later);
    const outcome = await acquireRefreshLock("gen-1", later);

    // Token mới đã có rồi; POST nữa là trình lại token server vừa vô hiệu hoá.
    expect(outcome.status).not.toBe("acquired");
  });

  it("`terminal` đã hết hạn ⇒ KHÔNG được POST lại", async () => {
    await finishWith("terminal", { status: 401 });

    const later = T0 + LEASE_TTL_MS * 3;
    vi.setSystemTime(later);
    const outcome = await acquireRefreshLock("gen-1", later);

    expect(outcome.status).not.toBe("acquired");
  });

  it("`safe-retryable` ⇒ chặn TRƯỚC `retryAt`, cho phép SAU `retryAt`", async () => {
    const retryAt = T0 + 60_000;
    await finishWith("safe-retryable", { status: 429, errorCode: "RATE_LIMITED", retryAt });

    // Lease đã hết hạn nhưng cooldown thì chưa: vẫn không được đụng vào mạng.
    const duringCooldown = T0 + LEASE_TTL_MS + 1_000;
    expect(duringCooldown).toBeLessThan(retryAt);
    vi.setSystemTime(duringCooldown);
    expect((await acquireRefreshLock("gen-1", duringCooldown)).status).not.toBe(
      "acquired",
    );

    // Qua cooldown thì đây là loại DUY NHẤT được phép thử lại — slowapi chặn ở
    // decorator nên chắc chắn chưa chạm rotation.
    const afterCooldown = retryAt + 1;
    vi.setSystemTime(afterCooldown);
    expect((await acquireRefreshLock("gen-1", afterCooldown)).status).toBe(
      "acquired",
    );
  });

  it("`acquired` hết hạn vẫn cướp được vô điều kiện (chết trước khi chạm mạng)", async () => {
    const first = await acquireRefreshLock("gen-1", T0);
    expect(first.status).toBe("acquired");

    const later = T0 + LEASE_TTL_MS + 1;
    vi.setSystemTime(later);
    expect((await acquireRefreshLock("gen-1", later)).status).toBe("acquired");
  });

  it("`in-flight` hết hạn mà không có kết quả ⇒ chặn, không cướp", async () => {
    const first = await acquireRefreshLock("gen-1", T0);
    if (first.status !== "acquired") throw new Error("không giành được lease");
    await first.handle.update({ phase: "in-flight" });

    const later = T0 + LEASE_TTL_MS * 3;
    vi.setSystemTime(later);
    const outcome = await acquireRefreshLock("gen-1", later);

    expect(outcome.status).toBe("blocked");
    if (outcome.status === "blocked") {
      expect(outcome.reason).toBe("stale-in-flight");
    }
  });
});

describe("contract 3 — handle đã nhả thì hết quyền ghi", () => {
  it("`update()` sau `release()` ⇒ reject", async () => {
    const acquired = await acquireRefreshLock("gen-1", T0);
    if (acquired.status !== "acquired") throw new Error("không giành được lease");

    await acquired.handle.update({ phase: "in-flight" });
    await acquired.handle.release();

    // Nguy hiểm nhất là heartbeat: một nhịp đã lên lịch có thể nổ sau khi khoá
    // đã nhả, và khi đó nó ghi NGOÀI vùng mutex.
    await expect(acquired.handle.update({ resultKind: "success" })).rejects.toThrow(
      /lease/i,
    );
  });

  it("`release()` KHÔNG settle chừng nào lần ghi chưa xong, và giữ khoá tới lúc đó", async () => {
    const locks = installWebLocks();
    const acquired = await acquireRefreshLock("gen-1", T0);
    if (acquired.status !== "acquired") throw new Error("không giành được lease");
    expect(locks.held()).toBe(1);

    // Chặn lần ghi giữa chừng để quan sát đúng khoảnh khắc `release()` xen vào.
    let letWriteFinish = () => {};
    const gate = new Promise<void>((r) => {
      letWriteFinish = r;
    });
    const realMutate = acquired.store.mutate.bind(acquired.store);
    const spy = vi
      .spyOn(acquired.store, "mutate")
      .mockImplementation(async (fn) => {
        await gate;
        return realMutate(fn);
      });

    const writing = acquired.handle.update({ phase: "in-flight" });
    const releasing = acquired.handle.release();

    let releaseSettled = false;
    void releasing.then(() => {
      releaseSettled = true;
    });

    // Lần ghi còn treo ⇒ `release()` chưa được settle, và khoá vẫn phải giữ.
    await Promise.resolve();
    expect(releaseSettled).toBe(false);
    expect(locks.held()).toBe(1);

    letWriteFinish();
    await writing;
    await releasing;

    expect(releaseSettled).toBe(true);
    expect(locks.held()).toBe(0);
    spy.mockRestore();
  });

  it("hai lời gọi `release()` cùng lúc ⇒ cùng chờ một lần nhả, không ai trả sớm", async () => {
    const locks = installWebLocks();
    const acquired = await acquireRefreshLock("gen-1", T0);
    if (acquired.status !== "acquired") throw new Error("không giành được lease");

    const [a, b] = [acquired.handle.release(), acquired.handle.release()];
    await Promise.all([a, b]);

    expect(locks.held()).toBe(0);
  });

  it("nhiều `update()` gọi sát nhau ⇒ ghi TUẦN TỰ, và `release()` đợi TẤT CẢ", async () => {
    const locks = installWebLocks();
    const acquired = await acquireRefreshLock("gen-1", T0);
    if (acquired.status !== "acquired") throw new Error("không giành được lease");

    const order: string[] = [];
    const realMutate = acquired.store.mutate.bind(acquired.store);
    const spy = vi.spyOn(acquired.store, "mutate").mockImplementation(async (fn) => {
      order.push("bắt-đầu");
      const out = await realMutate(fn);
      order.push("xong");
      return out;
    });

    // Hai heartbeat gọi sát nhau. Nếu chỉ nhớ "lần ghi mới nhất" thì lần đầu
    // có thể còn đang chạy sau khi khoá đã nhả — ghi ngoài vùng mutex.
    const first = acquired.handle.update({ phase: "in-flight" });
    const second = acquired.handle.update({ status: 200 });
    await acquired.handle.release();
    await Promise.all([first, second]);

    // Tuần tự: không có "bắt-đầu" thứ hai chen vào giữa cặp đầu.
    expect(order).toEqual(["bắt-đầu", "xong", "bắt-đầu", "xong"]);
    expect(locks.held()).toBe(0);
    spy.mockRestore();
  });
});

describe("contract 4 — hai kết quả chặn vĩnh viễn", () => {
  it.each(["ambiguous", "nonterminal-stop"] as const)(
    "`%s` ⇒ chặn ngay cả khi CHƯA hết hạn lẫn khi ĐÃ hết hạn",
    async (resultKind) => {
      const acquired = await acquireRefreshLock("gen-1", T0);
      if (acquired.status !== "acquired") throw new Error("không giành được lease");
      await acquired.handle.update({ phase: "in-flight" });
      await acquired.handle.update({ resultKind });
      await acquired.handle.release();

      // Còn hạn.
      expect((await acquireRefreshLock("gen-1", T0 + 1)).status).not.toBe(
        "acquired",
      );

      // Và sau khi hết hạn — thời gian trôi KHÔNG làm một rotation mơ hồ trở
      // nên an toàn.
      const later = T0 + LEASE_TTL_MS * 5;
      vi.setSystemTime(later);
      const outcome = await acquireRefreshLock("gen-1", later);
      expect(outcome.status).toBe("blocked");
      if (outcome.status === "blocked") expect(outcome.reason).toBe("result");
    },
  );
});

describe("contract 5 — Web Locks hỏng không được giả thành 'bận'", () => {
  it("`navigator.locks.request` ném ⇒ unavailable, không phải busy", async () => {
    const { installBrokenWebLocks } = await import("./test-harness");
    installBrokenWebLocks();

    const outcome = await acquireRefreshLock("gen-1", T0);

    // "busy" nghĩa là "tab khác đang làm, chờ họ" — chờ mãi một tab không tồn
    // tại. Phải là unavailable để đi đường fail-closed.
    expect(outcome.status).toBe("unavailable");
  });

  it("Web Locks lành + IDB lành ⇒ vẫn giành được (không hồi quy ma trận)", async () => {
    installWebLocks();

    const outcome = await acquireRefreshLock("gen-1", T0);

    expect(outcome.status).toBe("acquired");
  });
});
