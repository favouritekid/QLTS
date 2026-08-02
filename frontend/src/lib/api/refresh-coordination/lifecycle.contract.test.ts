// src/lib/api/refresh-coordination/lifecycle.contract.test.ts
/**
 * Vòng đời nhật ký: khi nào được XOÁ.
 *
 * Xoá quá tay là lỗi nguy hiểm nhất của cả lớp phối hợp — nhật ký trống nghĩa
 * là "chưa ai thử refresh", tức cấp phép POST. Một bản ghi `ambiguous` bị xoá
 * nhầm sẽ mở đường cho tab khác trình lại một token mà server có thể đã rotate.
 *
 * Nên quy tắc rất hẹp: chỉ xoá khi có **bằng chứng dương** rằng phiên đã sang
 * thế hệ mới. "Không đọc được generation" KHÔNG phải bằng chứng.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import { acquireRefreshLock } from "./lock";
import { selectJournalStore } from "./storage";
import {
  supersedeIfGenerationChanged,
  clearJournalAfter,
} from "./lifecycle";
import { installFakeIdb, installWebLocks, removeWebLocks } from "./test-harness";

const T0 = 1_800_000_000_000;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(T0);
  window.localStorage.clear();
  installFakeIdb();
  removeWebLocks();
});

afterEach(() => {
  vi.useRealTimers();
});

/** Dựng một nhật ký đang ở trạng thái CẤM (ambiguous) với generation cho trước. */
async function seedBlockingJournal(generationBefore: string | null) {
  const acquired = await acquireRefreshLock(generationBefore, T0);
  if (acquired.status !== "acquired") throw new Error("không giành được lease");
  await acquired.handle.update({ phase: "in-flight" });
  await acquired.handle.update({ resultKind: "ambiguous" });
  await acquired.handle.release();
}

async function journalExists(): Promise<boolean> {
  const store = await selectJournalStore();
  return (await store!.read()) !== null;
}

describe("supersede — chỉ xoá khi có bằng chứng DƯƠNG là phiên đã sang thế hệ mới", () => {
  it("generation ĐỔI ⇒ xoá", async () => {
    await seedBlockingJournal("gen-cũ");

    const outcome = await supersedeIfGenerationChanged("gen-mới");

    expect(outcome.status).toBe("cleared");
    expect(await journalExists()).toBe(false);
  });

  it("generation `null` ⇒ GIỮ (không đọc được ≠ đã đổi)", async () => {
    await seedBlockingJournal("gen-cũ");

    // CSRF cookie hết hạn hoặc bị xoá thì `document.cookie` không còn gì để
    // đọc. Đó là "không biết", không phải "đã có phiên mới" — xoá ở đây sẽ mở
    // đường POST lại một token server có thể đã rotate.
    const outcome = await supersedeIfGenerationChanged(null);

    expect(outcome.status).toBe("kept");
    expect(await journalExists()).toBe(true);
  });

  it("CÙNG generation ⇒ GIỮ", async () => {
    await seedBlockingJournal("gen-cũ");

    const outcome = await supersedeIfGenerationChanged("gen-cũ");

    expect(outcome.status).toBe("kept");
    expect(await journalExists()).toBe(true);
  });

  it("`generationBefore` là null nhưng nay ĐỌC ĐƯỢC generation ⇒ xoá", async () => {
    // Lúc thử refresh thì không đọc được CSRF; giờ đã có một cái. Đó là bằng
    // chứng dương: phiên đã sang thế hệ mới.
    await seedBlockingJournal(null);

    const outcome = await supersedeIfGenerationChanged("gen-mới");

    expect(outcome.status).toBe("cleared");
    expect(await journalExists()).toBe(false);
  });

  it("không có nhật ký ⇒ không có gì để xoá, và không báo nhầm là đã xoá", async () => {
    const outcome = await supersedeIfGenerationChanged("gen-mới");

    expect(outcome.status).toBe("kept");
  });
});

describe("clear — chỉ ba lối, và chỉ khi lối đó THỰC SỰ hoàn tất", () => {
  it("đăng nhập thành công ⇒ xoá", async () => {
    await seedBlockingJournal("gen-cũ");

    expect((await clearJournalAfter("login-success")).status).toBe("cleared");
    expect(await journalExists()).toBe(false);
  });

  it("logout backend thành công ⇒ xoá", async () => {
    await seedBlockingJournal("gen-cũ");

    expect((await clearJournalAfter("logout-success")).status).toBe("cleared");
    expect(await journalExists()).toBe(false);
  });

  it("`force_login` ĐÃ xoá cookie refresh ⇒ xoá", async () => {
    await seedBlockingJournal("gen-cũ");

    expect(
      (await clearJournalAfter("force-login-cookies-cleared")).status,
    ).toBe("cleared");
    expect(await journalExists()).toBe(false);
  });

  it.each([
    ["đăng nhập THẤT BẠI", "login-failed"],
    ["logout backend THẤT BẠI", "logout-failed"],
    ["reauth (cookie refresh còn nguyên)", "reauth"],
    ["chỉ dọn state client", "client-state-only"],
  ] as const)("%s ⇒ GIỮ", async (_label, reason) => {
    await seedBlockingJournal("gen-cũ");

    const outcome = await clearJournalAfter(reason);

    expect(outcome.status).toBe("kept");
    // `reauth` là ca đắt nhất: nó CỐ Ý giữ refresh cookie, nên nhật ký
    // `ambiguous` phải sống tới khi đăng nhập lại thành công.
    expect(await journalExists()).toBe(true);
  });
});

describe("kho lỗi ⇒ báo KHÔNG hoàn tất, không giả vờ đã trống", () => {
  it("`localStorage` ném lúc xoá ⇒ `failed`", async () => {
    installWebLocks();
    // Ép nhánh localStorage: IDB vắng mặt (không phải hỏng).
    Object.defineProperty(globalThis, "indexedDB", {
      configurable: true,
      writable: true,
      value: undefined,
    });
    await seedBlockingJournal("gen-cũ");

    const spy = vi
      .spyOn(Storage.prototype, "removeItem")
      .mockImplementation(() => {
        throw new DOMException("nope", "SecurityError");
      });

    const outcome = await clearJournalAfter("login-success");

    // Báo "đã xoá" trong khi bản ghi còn nguyên sẽ khiến tầng trên tin rằng
    // nhật ký đã sạch và bỏ qua lệnh cấm vẫn đang nằm đó.
    expect(outcome.status).toBe("failed");
    spy.mockRestore();
  });

  it("không có kho nào ⇒ `failed`, không phải `cleared`", async () => {
    removeWebLocks();
    Object.defineProperty(globalThis, "indexedDB", {
      configurable: true,
      writable: true,
      value: undefined,
    });

    expect((await clearJournalAfter("login-success")).status).toBe("failed");
    expect((await supersedeIfGenerationChanged("gen-mới")).status).toBe("failed");
  });
});

describe("hai tab — supersede không được xoá nhầm attempt MỚI", () => {
  it("attempt mới với generation mới đang chạy ⇒ supersede giữ nguyên", async () => {
    // Tab A để lại một nhật ký cấm ở thế hệ cũ.
    await seedBlockingJournal("gen-cũ");

    // Tab B thấy generation đã đổi, supersede, rồi bắt đầu attempt của mình.
    expect((await supersedeIfGenerationChanged("gen-mới")).status).toBe("cleared");
    const b = await acquireRefreshLock("gen-mới", T0);
    if (b.status !== "acquired") throw new Error("tab B không giành được lease");
    await b.handle.update({ phase: "in-flight" });

    // Tab C cũng chạy supersede với CÙNG generation mới. Nó phải thấy bản ghi
    // hiện tại đã thuộc thế hệ đó và để yên — xoá ở đây là xoá một attempt
    // đang bay, và tab kế tiếp sẽ POST chồng lên.
    const outcome = await supersedeIfGenerationChanged("gen-mới");

    expect(outcome.status).toBe("kept");
    const store = await selectJournalStore();
    const record = await store!.read();
    expect(record?.attemptId).toBe(b.handle.attemptId);
    expect(record?.phase).toBe("in-flight");
  });
});
